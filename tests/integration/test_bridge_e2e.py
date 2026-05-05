"""
End-to-end integration tests for `wb.mqtt_zigbee.bridge.Bridge`.

Exercises the full MQTT ↔ Bridge ↔ MQTT data path through a single
`FakeMqttBroker`: zigbee2mqtt-shaped messages enter the bridge via the
broker, get translated to Wiren Board MQTT Conventions topics, and any WB
commands are forwarded back to the corresponding zigbee2mqtt request topic.

Time-dependent paths (1Hz stats throttling, command debounce) are tested
by monkey-patching `time.monotonic` in `wb.mqtt_zigbee.bridge`.
"""

import json
from typing import Any

import pytest

from wb.mqtt_zigbee import bridge as bridge_module
from wb.mqtt_zigbee.bridge import Bridge
from wb.mqtt_zigbee.wb_converter.controls import BridgeControl, WbBoolValue
from wb.mqtt_zigbee.wb_converter.publisher import DEVICES_PREFIX, DRIVER_NAME

from .fakes.broker import FakeMqttBroker
from .fakes.client import FakeMqttClient
from .helpers.wb_observer import WbObserver
from .helpers.z2m_emulator import Z2mEmulator

BASE = "zigbee2mqtt"
BRIDGE_ID = "zigbee2mqtt"
BRIDGE_NAME = "Zigbee2MQTT bridge"


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> "list[float]":
    """
    A mutable list whose [0] item is returned by patched `time.monotonic`.

    Tests advance time by mutating the list:
        fake_clock[0] += 2.0
    """
    holder = [0.0]
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: holder[0])
    return holder


@pytest.fixture
def bridge(fake_mqtt_client: FakeMqttClient, fake_clock: "list[float]") -> Bridge:
    """
    Bridge wired to fakes with a deterministic monotonic clock.

    `fake_clock` is included in the dependency chain so it always patches
    `time.monotonic` before any Bridge code runs.
    """
    _ = fake_clock  # Keeps clock patch active for the lifetime of the fixture.
    return Bridge(
        mqtt_client=fake_mqtt_client,
        base_topic=BASE,
        device_id=BRIDGE_ID,
        device_name=BRIDGE_NAME,
        bridge_log_min_level="warning",
        command_debounce_sec=5.0,
    )


def _z2m_sensor(friendly_name: str, ieee: str = "0x0001") -> dict[str, Any]:
    """
    Z2M-shaped device dict for a simple temperature sensor
    """
    return {
        "ieee_address": ieee,
        "friendly_name": friendly_name,
        "type": "EndDevice",
        "definition": {
            "model": "MODEL-1",
            "vendor": "Vendor",
            "description": "Temp sensor",
            "exposes": [
                {
                    "type": "numeric",
                    "name": "temperature",
                    "property": "temperature",
                    "access": 1,
                    "unit": "°C",
                },
            ],
        },
    }


def _z2m_switch(friendly_name: str, ieee: str = "0x0002") -> dict[str, Any]:
    """
    Z2M-shaped device dict for a writable on/off switch
    """
    return {
        "ieee_address": ieee,
        "friendly_name": friendly_name,
        "type": "Router",
        "definition": {
            "model": "MODEL-2",
            "vendor": "Vendor",
            "description": "Switch",
            "exposes": [
                {
                    "type": "switch",
                    "features": [
                        {
                            "type": "binary",
                            "name": "state",
                            "property": "state",
                            "access": 0b111,
                            "value_on": "ON",
                            "value_off": "OFF",
                        },
                    ],
                },
            ],
        },
    }


class TestBridgeInitialization:
    """
    `Bridge.subscribe()` initial publishes and bridge/state, bridge/info, bridge/log handling
    """

    def test_publishes_bridge_device_meta(
        self,
        bridge: Bridge,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()

        meta = wb_observer.last_json_on(f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta")
        assert meta == {"driver": DRIVER_NAME, "title": {"en": BRIDGE_NAME, "ru": BRIDGE_NAME}}

    def test_publishes_log_level_control(
        self,
        bridge: Bridge,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()

        topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.LOG_LEVEL}"
        assert wb_observer.retained(topic) == "warning"

    def test_bridge_state_is_forwarded_to_state_control(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()

        z2m_emu.online()

        topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.STATE}"
        assert wb_observer.retained(topic) == "online"

    def test_bridge_info_publishes_version_and_permit_join(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()

        z2m_emu.info(version="1.42.0", permit_join=True)

        version_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.VERSION}"
        permit_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.PERMIT_JOIN}"
        assert wb_observer.retained(version_topic) == "1.42.0"
        assert wb_observer.retained(permit_topic) == WbBoolValue.TRUE

    def test_bridge_log_below_min_level_is_suppressed(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        log_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.LOG}"
        # `subscribe()` publishes a blank initial value to every control. The
        # below-min-level log must NOT add another publish on the Log topic.
        publishes_before = len(wb_observer.messages_on(log_topic))

        z2m_emu.log("info", "this is below warning")

        assert len(wb_observer.messages_on(log_topic)) == publishes_before

    def test_bridge_log_at_min_level_is_published(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        log_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.LOG}"

        z2m_emu.log("warning", "warn message")

        assert wb_observer.retained(log_topic) == "warn message"


class TestDeviceRegistration:
    """
    Device discovery via `bridge/devices`.
    """

    def test_device_is_registered_in_wb(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()

        z2m_emu.devices([_z2m_sensor("sensor-1")])

        meta = wb_observer.last_json_on(f"{DEVICES_PREFIX}/sensor-1/meta")
        assert isinstance(meta, dict)
        assert meta["driver"] == DRIVER_NAME
        temp_meta = wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/controls/temperature/meta")
        assert temp_meta is not None

    def test_device_count_is_published(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()

        z2m_emu.devices([_z2m_sensor("sensor-1"), _z2m_switch("switch-1")])

        topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.DEVICE_COUNT}"
        assert wb_observer.retained(topic) == "2"

    def test_device_with_unsafe_name_is_skipped(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()

        z2m_emu.devices([_z2m_sensor("bad/name")])

        assert wb_observer.retained(f"{DEVICES_PREFIX}/bad_name/meta") is None


class TestDeviceStatePropagation:
    """
    z2m → WB state and availability forwarding.
    """

    def test_state_is_forwarded_to_wb_control(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("sensor-1")])

        z2m_emu.device_state("sensor-1", {"temperature": 21.5})

        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/controls/temperature") == "21.5"

    def test_availability_is_forwarded(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("sensor-1")])

        z2m_emu.device_availability("sensor-1", online=True)

        available_topic = f"{DEVICES_PREFIX}/sensor-1/controls/available"
        assert wb_observer.retained(available_topic) == WbBoolValue.TRUE


class TestWbToZ2mCommands:
    """
    WB commands on `/on` topics forwarded to z2m `*/set`.
    """

    def test_command_is_forwarded_to_z2m_set_topic(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        fake_broker: FakeMqttBroker,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_switch("switch-1")])

        fake_broker.inject(f"{DEVICES_PREFIX}/switch-1/controls/state/on", WbBoolValue.TRUE)

        set_topic = f"{BASE}/switch-1/set"
        last_set = wb_observer.last_payload_on(set_topic)
        assert last_set is not None
        assert json.loads(last_set) == {"state": "ON"}

    def test_command_publishes_optimistic_value_on_control_topic(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        fake_broker: FakeMqttBroker,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_switch("switch-1")])

        fake_broker.inject(f"{DEVICES_PREFIX}/switch-1/controls/state/on", WbBoolValue.TRUE)

        assert wb_observer.retained(f"{DEVICES_PREFIX}/switch-1/controls/state") == WbBoolValue.TRUE


class TestPendingCommandDebounce:
    """
    `command_debounce_sec` interaction with stale state values from z2m.
    """

    def test_stale_state_during_window_is_suppressed(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        fake_broker: FakeMqttBroker,
        wb_observer: WbObserver,
        fake_clock: "list[float]",
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_switch("switch-1")])
        state_topic = f"{DEVICES_PREFIX}/switch-1/controls/state"

        fake_clock[0] = 100.0
        fake_broker.inject(f"{DEVICES_PREFIX}/switch-1/controls/state/on", WbBoolValue.TRUE)
        assert wb_observer.retained(state_topic) == WbBoolValue.TRUE

        # Stale "OFF" state arrives 1 second later (well within 5s debounce).
        fake_clock[0] = 101.0
        z2m_emu.device_state("switch-1", {"state": "OFF"})

        # The optimistic TRUE must remain — stale value is suppressed.
        assert wb_observer.retained(state_topic) == WbBoolValue.TRUE

    def test_state_after_debounce_expires_is_published(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        fake_broker: FakeMqttBroker,
        wb_observer: WbObserver,
        fake_clock: "list[float]",
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_switch("switch-1")])
        state_topic = f"{DEVICES_PREFIX}/switch-1/controls/state"

        fake_clock[0] = 100.0
        fake_broker.inject(f"{DEVICES_PREFIX}/switch-1/controls/state/on", WbBoolValue.TRUE)

        fake_clock[0] = 200.0  # well past 5s debounce
        z2m_emu.device_state("switch-1", {"state": "OFF"})

        assert wb_observer.retained(state_topic) == WbBoolValue.FALSE

    def test_confirming_state_clears_pending_command(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        fake_broker: FakeMqttBroker,
        wb_observer: WbObserver,
        fake_clock: "list[float]",
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_switch("switch-1")])
        state_topic = f"{DEVICES_PREFIX}/switch-1/controls/state"

        fake_clock[0] = 100.0
        fake_broker.inject(f"{DEVICES_PREFIX}/switch-1/controls/state/on", WbBoolValue.TRUE)

        # Confirming state arrives within debounce window with the same value.
        fake_clock[0] = 100.5
        z2m_emu.device_state("switch-1", {"state": "ON"})

        # After confirmation, a real OFF before debounce expires must publish
        # immediately (pending was cleared by the matching confirmation).
        fake_clock[0] = 101.0
        z2m_emu.device_state("switch-1", {"state": "OFF"})

        assert wb_observer.retained(state_topic) == WbBoolValue.FALSE


class TestStatsThrottling:
    """
    1Hz throttling of bridge stats counters
    """

    def test_messages_received_throttled_to_once_per_second(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
        fake_clock: "list[float]",
    ) -> None:
        bridge.subscribe()
        msg_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.MESSAGES_RECEIVED}"

        fake_clock[0] = 1000.0
        z2m_emu.online()
        first = wb_observer.retained(msg_topic)

        # Three more events within the same second — no further publishes.
        fake_clock[0] = 1000.5
        z2m_emu.info(version="1.0", permit_join=False)
        z2m_emu.log("warning", "x")
        z2m_emu.log("error", "y")
        after_burst = wb_observer.retained(msg_topic)

        # One second later, stats publish again.
        fake_clock[0] = 1002.0
        z2m_emu.online()
        after_window = wb_observer.retained(msg_topic)

        # The exact stored counter is "messages seen so far"; we don't pin its
        # absolute value (other handlers in subscribe() may also count). We do pin:
        #   - first publish must produce a numeric value;
        #   - bursts within the 1Hz window do NOT change the retained value;
        #   - past the window, the value strictly increases.
        assert first is not None and first.isdigit()
        assert after_burst == first
        assert after_window is not None and after_window.isdigit()
        assert int(after_window) > int(first)


class TestDeviceEvents:
    """
    `bridge/event` and `bridge/response/device/remove` handling
    """

    def test_device_left_removes_wb_device(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("sensor-1")])
        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/meta") is not None

        z2m_emu.device_left("sensor-1", ieee_address="0x0001")

        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/meta") is None
        assert (
            wb_observer.retained(f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.LAST_LEFT}")
            == "sensor-1"
        )

    def test_device_renamed_moves_wb_device(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("old-name")])
        assert wb_observer.retained(f"{DEVICES_PREFIX}/old-name/meta") is not None

        z2m_emu.device_renamed("old-name", "new-name")

        assert wb_observer.retained(f"{DEVICES_PREFIX}/old-name/meta") is None
        assert wb_observer.retained(f"{DEVICES_PREFIX}/new-name/meta") is not None

    def test_device_renamed_resubscribes_state_topic(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
        fake_mqtt_client: FakeMqttClient,
    ) -> None:
        """
        After rename, state coming on the new z2m topic must reach the new WB device,
        and the old per-device subscription must be dropped from the broker.
        """
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("old-name")])

        z2m_emu.device_renamed("old-name", "new-name")

        # Old per-device subscription is dropped.
        assert f"{BASE}/old-name" in fake_mqtt_client.unsubscriptions
        # New per-device state reaches the new WB control.
        z2m_emu.device_state("new-name", {"temperature": 22.5})
        assert wb_observer.retained(f"{DEVICES_PREFIX}/new-name/controls/temperature") == "22.5"

    def test_device_remove_response_removes_wb_device(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("sensor-1")])

        z2m_emu.remove_response(status="ok", id_="sensor-1")

        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/meta") is None


class TestStaleDeviceCleanup:
    """
    Devices missing from a refreshed `bridge/devices` list are removed
    """

    def test_devices_missing_from_new_list_are_removed(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("sensor-1"), _z2m_switch("switch-1")])
        assert wb_observer.retained(f"{DEVICES_PREFIX}/switch-1/meta") is not None

        z2m_emu.devices([_z2m_sensor("sensor-1")])

        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/meta") is not None
        assert wb_observer.retained(f"{DEVICES_PREFIX}/switch-1/meta") is None


class TestGhostCleanup:
    """
    Retained ghost devices from previous runs are scrubbed on startup
    """

    def test_empty_devices_list_clears_all_devices(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """
        Edge case: zigbee2mqtt may publish an empty `bridge/devices` array
        (e.g. after factory reset of the coordinator). All known devices must
        be removed and Device count must drop to 0.
        """
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("sensor-1"), _z2m_switch("switch-1")])
        device_count_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.DEVICE_COUNT}"
        assert wb_observer.retained(device_count_topic) == "2"

        z2m_emu.devices([])

        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/meta") is None
        assert wb_observer.retained(f"{DEVICES_PREFIX}/switch-1/meta") is None
        assert wb_observer.retained(device_count_topic) == "0"

    def test_ghost_devices_from_previous_run_are_cleaned_up(
        self,
        bridge: Bridge,
        fake_broker: FakeMqttBroker,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        # Simulate retained ghost device from a previous run.
        ghost_meta = json.dumps({"driver": DRIVER_NAME, "title": {"en": "G", "ru": "G"}})
        fake_broker.inject(f"{DEVICES_PREFIX}/ghost/meta", ghost_meta, retain=True)
        fake_broker.inject(f"{DEVICES_PREFIX}/ghost/controls/temperature/meta", "{}", retain=True)

        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("sensor-1")])

        assert wb_observer.retained(f"{DEVICES_PREFIX}/ghost/meta") is None


class TestReconnectFlow:
    """
    `Bridge.republish()` and `Bridge.set_all_unavailable()` after reconnect.
    """

    def test_republish_increments_reconnect_counter(
        self,
        bridge: Bridge,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        reconnects_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.RECONNECTS}"

        bridge.republish()
        bridge.republish()

        assert wb_observer.retained(reconnects_topic) == "2"

    def test_set_all_unavailable_marks_known_devices_offline(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("sensor-1")])

        bridge.set_all_unavailable()

        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/controls/available") == WbBoolValue.FALSE
