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
import logging
from typing import Any

import pytest

from wb.mqtt_zigbee.bridge import Bridge
from wb.mqtt_zigbee.wb_converter.controls import (
    BridgeControl,
    WbBoolValue,
    WbControlError,
)
from wb.mqtt_zigbee.wb_converter.publisher import DEVICES_PREFIX, DRIVER_NAME

from .fakes.broker import FakeMqttBroker
from .fakes.client import FakeMqttClient
from .helpers.wb_observer import WbObserver
from .helpers.z2m_emulator import Z2mEmulator

BASE = "zigbee2mqtt"
BRIDGE_ID = "zigbee2mqtt"
BRIDGE_NAME = "Zigbee2MQTT bridge"


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


def _z2m_broken_sensor(friendly_name: str, ieee: str) -> dict[str, Any]:
    """
    Z2M device that survives the JSON-shape check and Z2MDevice.from_dict but breaks
    control mapping: a numeric expose with a non-numeric value_min. from_dict stores
    "low" verbatim; expose_mapper then evaluates "low" * scale -> TypeError.
    """
    dev = _z2m_sensor(friendly_name, ieee=ieee)
    dev["definition"]["exposes"][0]["value_min"] = "low"
    return dev


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

    def test_registers_last_will_for_bridge_error(
        self,
        bridge: Bridge,
        fake_mqtt_client: FakeMqttClient,
    ) -> None:
        """
        Constructing the bridge registers an MQTT LWT flagging the bridge on a crash
        """
        _ = bridge  # Bridge.__init__ sets the will (before connect)
        assert fake_mqtt_client.will == (
            f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta/error",
            WbControlError.READ_WRITE,
            0,
            True,
        )

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

    def test_bridge_offline_sets_bridge_meta_error_and_online_clears(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """
        z2m down → the bridge device gets meta/error "rw"; back online clears it
        """
        bridge.subscribe()
        error_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta/error"

        z2m_emu.online()
        assert wb_observer.retained(error_topic) is None
        z2m_emu.offline()
        assert wb_observer.retained(error_topic) == WbControlError.READ_WRITE
        z2m_emu.online()
        assert wb_observer.retained(error_topic) is None

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

    def test_bridge_log_control_chars_are_stripped(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """
        z2m log text is forwarded verbatim into the retained "Log" control; control
        characters (CR/LF/NUL/...) must be replaced so they cannot corrupt the value.
        """
        bridge.subscribe()
        log_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.LOG}"

        z2m_emu.log("warning", "line1\r\nline2\tval\x00end")

        assert wb_observer.retained(log_topic) == "line1  line2 val end"


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

    def test_broken_device_is_isolated_and_later_devices_still_register(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        A device whose field types break control mapping must not abort the loop: the
        devices before AND after it still register (list order must not decide who
        appears), and only one error is logged (arc42 "Устойчивость к ошибкам").
        """
        bridge.subscribe()

        with caplog.at_level(logging.ERROR):
            z2m_emu.devices(
                [
                    _z2m_sensor("sensor-1", ieee="0x0001"),
                    _z2m_broken_sensor("sensor-bad", ieee="0x0002"),
                    _z2m_sensor("sensor-3", ieee="0x0003"),
                ]
            )

        # The device AFTER the broken one is the regression: it must still register.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/meta") is not None
        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-3/meta") is not None
        # The broken device is skipped, not registered.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-bad/meta") is None
        # The failure is logged and names the culprit.
        assert "sensor-bad" in caplog.text

    def test_malformed_device_field_type_does_not_abort_batch(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        A device with a malformed field type (non-string friendly_name) is rejected in
        Z2MDevice.from_dict and dropped by _handle_bridge_devices, so it never reaches the
        bridge loop. The valid device still registers AND the post-loop stale removal
        still runs. Regression guard: an unhashable name would otherwise crash
        _remove_stale_devices (which builds a set of names) outside any isolation, leaving
        the removed device stranded in WB. The bridge/devices shape check passes such payloads.
        """
        bridge.subscribe()
        # A device that must be stale-removed once it drops out of the next batch.
        z2m_emu.devices([_z2m_sensor("gone-later", ieee="0x00e0")])
        assert wb_observer.retained(f"{DEVICES_PREFIX}/gone-later/meta") is not None

        bad = _z2m_sensor("placeholder", ieee="0x00e2")
        bad["friendly_name"] = ["not", "a", "string"]  # unhashable: would crash the batch pre-fix

        with caplog.at_level(logging.WARNING):
            z2m_emu.devices([_z2m_sensor("keep-me", ieee="0x00e1"), bad])

        # The valid device registers; the malformed one is dropped at parse time.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/keep-me/meta") is not None
        assert "Failed to parse device" in caplog.text
        # Post-loop stale removal ran: the device absent from this batch is gone.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/gone-later/meta") is None

    def test_unnamed_device_carries_model_in_id_and_title(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """friendly_name == ieee (device not renamed in z2m) → id/title = "{model} {ieee}"."""
        bridge.subscribe()

        z2m_emu.devices([_z2m_sensor("0xabc", ieee="0xabc")])

        meta = wb_observer.last_json_on(f"{DEVICES_PREFIX}/MODEL-1_0xabc/meta")
        assert isinstance(meta, dict)
        assert meta["title"] == {"en": "MODEL-1 0xabc", "ru": "MODEL-1 0xabc"}
        # Not published under the bare ieee.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/0xabc/meta") is None

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

    def test_sanitizer_id_collision_is_disambiguated_by_ieee(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """
        Two distinct z2m names that sanitize to the same id ("lamp.1" and "lamp 1"
        both -> "lamp_1") must not clobber each other: the smaller ieee_address keeps
        the clean id, the larger is disambiguated with its ieee. Both stay registered.
        """
        bridge.subscribe()

        z2m_emu.devices(
            [
                _z2m_sensor("lamp.1", ieee="0x0001"),
                _z2m_sensor("lamp 1", ieee="0x0009"),
            ]
        )

        # Smaller ieee (0x0001) keeps the clean sanitized id.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/lamp_1/meta") is not None
        # Larger ieee (0x0009) is disambiguated, not lost or clobbered.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/lamp_1_0x0009/meta") is not None
        # Both are counted — two separate WB devices.
        count_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.DEVICE_COUNT}"
        assert wb_observer.retained(count_topic) == "2"

    @pytest.mark.parametrize("order", [("0x0001", "0x0009"), ("0x0009", "0x0001")])
    def test_id_collision_owner_is_independent_of_list_order(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
        order: "tuple[str, str]",
    ) -> None:
        """
        The clean id always goes to the smaller ieee_address regardless of the order z2m
        lists the two colliding devices. Otherwise a remove+re-add that flips the ordering
        would swap their retained topics and orphan the previous owner into ghost cleanup.
        """
        bridge.subscribe()
        by_ieee = {
            "0x0001": _z2m_sensor("lamp.1", ieee="0x0001"),
            "0x0009": _z2m_sensor("lamp 1", ieee="0x0009"),
        }

        z2m_emu.devices([by_ieee[order[0]], by_ieee[order[1]]])

        # "lamp.1" (ieee 0x0001, the smaller) owns the clean id in either ordering.
        clean = wb_observer.last_json_on(f"{DEVICES_PREFIX}/lamp_1/meta")
        assert clean["title"]["en"] == "lamp.1"
        assert wb_observer.retained(f"{DEVICES_PREFIX}/lamp_1_0x0009/meta") is not None

    def test_id_collision_existing_device_keeps_clean_id_across_batches(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """
        A device already holding the clean id keeps it when a colliding NEW device arrives
        in a later batch — even if the newcomer has the smaller ieee_address. The
        already-registered device wins over the min-ieee rule; a live device's id is
        never reassigned.
        """
        bridge.subscribe()
        # First batch: lamp.1 alone -> clean "lamp_1".
        z2m_emu.devices([_z2m_sensor("lamp.1", ieee="0x0005")])
        assert wb_observer.last_json_on(f"{DEVICES_PREFIX}/lamp_1/meta")["title"]["en"] == "lamp.1"

        # Second batch: already-registered lamp.1 plus a NEW colliding "lamp 1", smaller ieee.
        z2m_emu.devices(
            [
                _z2m_sensor("lamp.1", ieee="0x0005"),
                _z2m_sensor("lamp 1", ieee="0x0001"),
            ]
        )

        # The existing device (0x0005) keeps the clean id despite the newcomer's smaller ieee.
        assert wb_observer.last_json_on(f"{DEVICES_PREFIX}/lamp_1/meta")["title"]["en"] == "lamp.1"
        # Newcomer is suffixed, not given the base id.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/lamp_1_0x0001/meta") is not None

    def test_rename_into_colliding_id_is_disambiguated(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """
        Renaming a device to a name that sanitizes to another live device's id must be
        disambiguated by ieee (the rename path uses _resolve_device_id), not clobber the
        existing device's retained topics.
        """
        bridge.subscribe()
        z2m_emu.devices(
            [
                _z2m_sensor("lamp.1", ieee="0x000a"),
                _z2m_sensor("lamp.2", ieee="0x000b"),
            ]
        )
        assert wb_observer.retained(f"{DEVICES_PREFIX}/lamp_1/meta") is not None
        assert wb_observer.retained(f"{DEVICES_PREFIX}/lamp_2/meta") is not None

        # Rename lamp.2 -> "lamp 1", which sanitizes to "lamp_1" and collides with lamp.1.
        z2m_emu.device_renamed("lamp.2", "lamp 1")

        # The existing device keeps the clean id; the renamed device is disambiguated by ieee.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/lamp_1/meta") is not None
        assert wb_observer.retained(f"{DEVICES_PREFIX}/lamp_1_0x000b/meta") is not None
        # The renamed device's old id is cleared.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/lamp_2/meta") is None


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

    def test_readonly_device_offline_gets_r_error(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """
        Read-only device (sensor) offline → meta/error "r" (nothing to write)
        """
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("sensor-1")])  # temperature only → all controls readonly
        error_topic = f"{DEVICES_PREFIX}/sensor-1/meta/error"

        # Clear first (isolate the offline branch from the registration default), then offline.
        z2m_emu.device_availability("sensor-1", online=True)
        assert wb_observer.retained(error_topic) is None
        z2m_emu.device_availability("sensor-1", online=False)
        assert wb_observer.retained(error_topic) == WbControlError.READ

    def test_writable_device_offline_gets_rw_error_and_online_clears(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """
        Device with a writable control (switch) offline → "rw"; back online clears it
        """
        bridge.subscribe()
        z2m_emu.devices([_z2m_switch("switch-1")])  # writable "state" → "rw"
        error_topic = f"{DEVICES_PREFIX}/switch-1/meta/error"

        z2m_emu.device_availability("switch-1", online=True)
        assert wb_observer.retained(error_topic) is None
        z2m_emu.device_availability("switch-1", online=False)
        assert wb_observer.retained(error_topic) == WbControlError.READ_WRITE

        z2m_emu.device_availability("switch-1", online=True)
        # Empty retained payload clears the topic.
        assert wb_observer.retained(error_topic) is None

    def test_first_state_clears_device_meta_error(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """
        A freshly registered device is flagged unreachable until it reports; the first
        state message (with no availability message) assumes it online and clears the error
        """
        bridge.subscribe()
        z2m_emu.devices([_z2m_switch("switch-1")])
        error_topic = f"{DEVICES_PREFIX}/switch-1/meta/error"

        # Registration default: assumed unreachable → "rw".
        assert wb_observer.retained(error_topic) == WbControlError.READ_WRITE

        z2m_emu.device_state("switch-1", {"state": "ON"})
        assert wb_observer.retained(error_topic) is None


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
        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/meta/error") is None  # error cleared too
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

    def test_device_renamed_to_unsafe_name_is_rejected(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
        fake_mqtt_client: FakeMqttClient,
    ) -> None:
        """
        A bridge/event rename delivers new_name straight from the z2m payload. A name
        with an MQTT wildcard/separator ('#', '+', '/') must be rejected: no wildcard
        subscription, and the device keeps its original safe registration.
        """
        bridge.subscribe()
        z2m_emu.devices([_z2m_sensor("old-name")])
        assert wb_observer.retained(f"{DEVICES_PREFIX}/old-name/meta") is not None

        z2m_emu.device_renamed("old-name", "#")

        # No wildcard subscription was created from the injected name.
        assert f"{BASE}/#" not in fake_mqtt_client.subscriptions
        assert not any(s.endswith("/#") or s.endswith("/+") for s in fake_mqtt_client.subscriptions)
        # The original device is untouched — still registered under its safe name.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/old-name/meta") is not None

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

    def test_present_but_skipped_device_is_not_ghosted(
        self,
        bridge: Bridge,
        fake_broker: FakeMqttBroker,
        z2m_emu: Z2mEmulator,
        wb_observer: WbObserver,
    ) -> None:
        """
        A device present in bridge/devices but skipped at registration this cycle (e.g.
        mid-interview: empty exposes) must NOT be wiped as a ghost — its prior-run
        retained topics survive until it reports exposes and registers.
        """
        prior_meta = json.dumps({"driver": DRIVER_NAME, "title": {"en": "S", "ru": "S"}})
        fake_broker.inject(f"{DEVICES_PREFIX}/sensor-1/meta", prior_meta, retain=True)

        bridge.subscribe()
        skipped = _z2m_sensor("sensor-1")
        skipped["definition"]["exposes"] = []  # still interviewing -> skipped, not gone
        z2m_emu.devices([skipped])

        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/meta") is not None


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
        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/meta/error") == WbControlError.READ


class TestMalformedPayloads:
    """
    Non-UTF-8 / garbage payloads on any subscribed topic must not crash the daemon.
    """

    def test_non_utf8_payload_does_not_crash_and_bridge_stays_functional(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        fake_broker: FakeMqttBroker,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_switch("switch-1")])

        # Invalid UTF-8 on a JSON topic, a plain-string topic, and a command topic —
        # none may raise UnicodeDecodeError out of the handler.
        garbage = b"\xff\xfe\x00"
        fake_broker.inject(f"{BASE}/bridge/devices", garbage, retain=True)
        fake_broker.inject(f"{BASE}/bridge/state", garbage, retain=True)
        fake_broker.inject(f"{BASE}/bridge/info", garbage, retain=True)
        fake_broker.inject(f"{DEVICES_PREFIX}/switch-1/controls/state/on", garbage)

        # Reaching here proves no inject raised. The bridge is still alive and
        # processing valid messages afterwards.
        z2m_emu.online()
        state_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.STATE}"
        assert wb_observer.retained(state_topic) == "online"

    def test_wrong_top_level_json_type_does_not_crash(
        self,
        bridge: Bridge,
        z2m_emu: Z2mEmulator,
        fake_broker: FakeMqttBroker,
        wb_observer: WbObserver,
    ) -> None:
        bridge.subscribe()
        z2m_emu.devices([_z2m_switch("switch-1")])

        # Valid JSON but the wrong top-level shape for each handler (object where a
        # list is expected, bare scalar/array where a dict is expected) must not raise
        # AttributeError/TypeError out of the callback.
        for payload in (b"{}", b"5", b'"x"', b"[1, 2, 3]", b"null", b"[{}]", b'[{"x": 1}]'):
            fake_broker.inject(f"{BASE}/bridge/devices", payload, retain=True)
            fake_broker.inject(f"{BASE}/bridge/info", payload, retain=True)
            fake_broker.inject(f"{BASE}/bridge/event", payload)
            fake_broker.inject(f"{BASE}/bridge/logging", payload)
            fake_broker.inject(f"{BASE}/bridge/response/device/remove", payload)
            fake_broker.inject(f"{BASE}/switch-1/availability", payload)

        # Top-level-valid dicts whose nested "data" field is the wrong shape must not
        # raise out of the event / remove-response handlers either.
        fake_broker.inject(f"{BASE}/bridge/event", b'{"type": "deviceLeave", "data": "x"}')
        fake_broker.inject(f"{BASE}/bridge/response/device/remove", b'{"status": "ok", "data": 5}')

        # A malformed bridge/devices — including a list of objects that are not real
        # device descriptors (no ieee_address, e.g. "[{}]") — must NOT be treated as an
        # authoritative list and wipe the registered device.
        assert wb_observer.retained(f"{DEVICES_PREFIX}/switch-1/meta") is not None

        # Still alive and processing valid messages.
        z2m_emu.online()
        state_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.STATE}"
        assert wb_observer.retained(state_topic) == "online"
