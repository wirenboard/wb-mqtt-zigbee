"""Integration tests for `wb.mqtt_zigbee.z2m.client.Z2MClient`.

Wires Z2MClient to a FakeMqttClient/FakeMqttBroker, asserts that
zigbee2mqtt-shaped MQTT messages reach the right typed callbacks and that
outgoing commands publish the expected JSON to the expected topics.
"""

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from wb.mqtt_zigbee.z2m.client import Z2MClient
from wb.mqtt_zigbee.z2m.model import BridgeInfo, DeviceEvent, DeviceEventType, Z2MDevice

from .fakes.client import FakeMqttClient
from .helpers.wb_observer import WbObserver
from .helpers.z2m_emulator import Z2mEmulator

BASE = "zigbee2mqtt"


@dataclass
class _Recorder:
    """Captures every Z2MClient callback invocation for assertions."""

    bridge_states: list[str] = field(default_factory=list)
    bridge_infos: list[BridgeInfo] = field(default_factory=list)
    bridge_logs: list[tuple[str, str]] = field(default_factory=list)
    devices_calls: list[list[Z2MDevice]] = field(default_factory=list)
    device_events: list[DeviceEvent] = field(default_factory=list)
    device_states: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    availability: list[tuple[str, bool]] = field(default_factory=list)


def _make_client(fake_mqtt_client: FakeMqttClient) -> tuple[Z2MClient, _Recorder]:
    rec = _Recorder()
    client = Z2MClient(
        mqtt_client=fake_mqtt_client,
        base_topic=BASE,
        on_bridge_state=rec.bridge_states.append,
        on_bridge_info=rec.bridge_infos.append,
        on_bridge_log=lambda lvl, msg: rec.bridge_logs.append((lvl, msg)),
        on_devices=rec.devices_calls.append,
        on_device_event=rec.device_events.append,
        on_device_state=lambda name, state: rec.device_states.append((name, state)),
        on_device_availability=lambda name, online: rec.availability.append((name, online)),
    )
    client.subscribe()
    return client, rec


class TestBridgeState:
    """`zigbee2mqtt/bridge/state` parsing."""

    @pytest.mark.parametrize("state", ["online", "offline", "error"])
    def test_plain_string(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator, state: str) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.state_raw(state, retain=True)
        assert rec.bridge_states == [state]

    def test_json_object(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.state_raw(json.dumps({"state": "online"}), retain=True)
        assert rec.bridge_states == ["online"]

    def test_unknown_value_ignored(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.state_raw("starting", retain=True)
        assert not rec.bridge_states


class TestBridgeInfo:
    """`zigbee2mqtt/bridge/info` parsing."""

    def test_full_payload(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.info(version="1.42.0", permit_join=True, permit_join_end=1700000000)
        assert rec.bridge_infos == [
            BridgeInfo(version="1.42.0", permit_join=True, permit_join_end=1700000000)
        ]

    def test_empty_payload_uses_defaults(
        self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
    ) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.info_raw(json.dumps({}))
        assert rec.bridge_infos == [BridgeInfo(version="", permit_join=False, permit_join_end=None)]

    def test_invalid_json_skipped(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.info_raw("not json")
        assert not rec.bridge_infos


class TestBridgeLog:
    """`zigbee2mqtt/bridge/logging` parsing."""

    def test_valid_payload(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.log("warning", "something happened")
        assert rec.bridge_logs == [("warning", "something happened")]

    def test_invalid_json_falls_back_to_raw(
        self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
    ) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.log_raw("not json at all")
        assert rec.bridge_logs == [("info", "not json at all")]


class TestBridgeDevices:
    """`zigbee2mqtt/bridge/devices` parsing."""

    def test_excludes_coordinator_and_parses_rest(
        self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
    ) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.devices(
            [
                {"ieee_address": "0x000c", "friendly_name": "Coordinator", "type": "Coordinator"},
                {
                    "ieee_address": "0xaabb",
                    "friendly_name": "lamp",
                    "type": "Router",
                    "definition": {"model": "M1", "vendor": "V1", "exposes": []},
                },
            ]
        )
        assert len(rec.devices_calls) == 1
        devices = rec.devices_calls[0]
        assert [device.friendly_name for device in devices] == ["lamp"]
        assert devices[0].vendor == "V1"

    def test_one_broken_does_not_affect_others(
        self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
    ) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        # First device has `definition` of a wrong shape (str instead of dict) — would
        # raise during from_dict; the second one must still be parsed.
        z2m_emu.devices_raw(
            json.dumps(
                [
                    {
                        "ieee_address": "0x1",
                        "friendly_name": "broken",
                        "type": "Router",
                        "definition": "oops",
                    },
                    {"ieee_address": "0x2", "friendly_name": "ok", "type": "Router"},
                ]
            )
        )
        assert len(rec.devices_calls) == 1
        assert [device.friendly_name for device in rec.devices_calls[0]] == ["ok"]


class TestBridgeEvent:
    """`zigbee2mqtt/bridge/event` parsing."""

    @pytest.mark.parametrize(
        ("z2m_type", "expected_internal"),
        [
            ("device_joined", DeviceEventType.JOINED),
            ("device_leave", DeviceEventType.LEFT),
        ],
    )
    def test_join_leave_mapped(
        self,
        fake_mqtt_client: FakeMqttClient,
        z2m_emu: Z2mEmulator,
        z2m_type: str,
        expected_internal: str,
    ) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.event(z2m_type, {"friendly_name": "lamp", "ieee_address": "0xaa"})
        assert rec.device_events == [DeviceEvent(type=expected_internal, name="lamp")]

    def test_renamed_carries_old_and_new_name(
        self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
    ) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.device_renamed(from_name="old", to_name="new")
        assert rec.device_events == [DeviceEvent(type=DeviceEventType.RENAMED, name="new", old_name="old")]

    def test_unknown_type_ignored(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.event("device_announce", {"friendly_name": "lamp"})
        assert not rec.device_events


class TestRemoveResponse:
    """`zigbee2mqtt/bridge/response/device/remove` parsing."""

    def test_ok_emits_removed_event(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.remove_response(status="ok", id_="lamp")
        assert rec.device_events == [DeviceEvent(type=DeviceEventType.REMOVED, name="lamp")]

    def test_error_status_ignored(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.remove_response(status="error", id_="lamp")
        assert not rec.device_events


class TestDeviceAvailability:
    """`zigbee2mqtt/+/availability` parsing."""

    def test_online(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.device_availability("lamp", online=True)
        assert rec.availability == [("lamp", True)]

    def test_offline(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.device_availability("lamp", online=False)
        assert rec.availability == [("lamp", False)]

    def test_for_bridge_is_ignored(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.device_availability("bridge", online=True)
        assert not rec.availability

    def test_invalid_json_skipped(self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
        _client, rec = _make_client(fake_mqtt_client)
        z2m_emu.device_availability_raw("lamp", "not json")
        assert not rec.availability


class TestPerDeviceState:
    """Per-device `zigbee2mqtt/<name>` subscribe/unsubscribe and state delivery."""

    def test_received_after_subscribe_device(
        self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
    ) -> None:
        client, rec = _make_client(fake_mqtt_client)
        client.subscribe_device("lamp")
        z2m_emu.device_state("lamp", {"state": "ON", "brightness": 200})
        assert rec.device_states == [("lamp", {"state": "ON", "brightness": 200})]

    def test_unsubscribe_stops_state_callbacks(
        self, fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
    ) -> None:
        client, rec = _make_client(fake_mqtt_client)
        client.subscribe_device("lamp")
        client.unsubscribe_device("lamp")
        z2m_emu.device_state("lamp", {"state": "ON"})
        assert not rec.device_states

    def test_subscribe_device_is_idempotent(self, fake_mqtt_client: FakeMqttClient) -> None:
        client, _rec = _make_client(fake_mqtt_client)
        client.subscribe_device("lamp")
        subs_after_first = list(fake_mqtt_client.subscriptions)
        client.subscribe_device("lamp")
        # Second call must NOT add another `zigbee2mqtt/lamp` subscription
        assert fake_mqtt_client.subscriptions == subs_after_first


class TestOutgoingCommands:
    """`set_permit_join`, `request_device_state`, `set_device_state` publishes."""

    def test_set_permit_join_enabled_publishes_254(
        self, fake_mqtt_client: FakeMqttClient, wb_observer: WbObserver
    ) -> None:
        client, _rec = _make_client(fake_mqtt_client)
        client.set_permit_join(True)
        msg = wb_observer.last_on(f"{BASE}/bridge/request/permit_join")
        assert msg is not None
        assert json.loads(msg.payload.decode("utf-8")) == {"time": 254}

    def test_set_permit_join_disabled_publishes_zero(
        self, fake_mqtt_client: FakeMqttClient, wb_observer: WbObserver
    ) -> None:
        client, _rec = _make_client(fake_mqtt_client)
        client.set_permit_join(False)
        msg = wb_observer.last_on(f"{BASE}/bridge/request/permit_join")
        assert msg is not None
        assert json.loads(msg.payload.decode("utf-8")) == {"time": 0}

    def test_request_device_state_publishes_empty_object(
        self, fake_mqtt_client: FakeMqttClient, wb_observer: WbObserver
    ) -> None:
        client, _rec = _make_client(fake_mqtt_client)
        client.request_device_state("lamp")
        msg = wb_observer.last_on(f"{BASE}/lamp/get")
        assert msg is not None
        assert msg.payload == b"{}"

    def test_set_device_state_publishes_payload_json(
        self, fake_mqtt_client: FakeMqttClient, wb_observer: WbObserver
    ) -> None:
        client, _rec = _make_client(fake_mqtt_client)
        client.set_device_state("lamp", {"state": "ON", "brightness": 128})
        msg = wb_observer.last_on(f"{BASE}/lamp/set")
        assert msg is not None
        assert json.loads(msg.payload.decode("utf-8")) == {"state": "ON", "brightness": 128}


class TestSubscriptionTopology:
    """High-level subscribe/refresh API contracts."""

    def test_subscribe_subscribes_to_expected_bridge_topics(self, fake_mqtt_client: FakeMqttClient) -> None:
        """Locks the set of topics Z2MClient.subscribe() registers on the broker.

        Other tests assert behavior via retained-message replay, which can mask a
        silently dropped subscription. This test pins the topology directly.
        """
        _client, _rec = _make_client(fake_mqtt_client)
        expected = {
            f"{BASE}/bridge/state",
            f"{BASE}/bridge/info",
            f"{BASE}/bridge/logging",
            f"{BASE}/bridge/devices",
            f"{BASE}/bridge/event",
            f"{BASE}/bridge/response/device/remove",
            f"{BASE}/+/availability",
        }
        assert expected.issubset(set(fake_mqtt_client.subscriptions))

    def test_refresh_device_list_re_subscribes(
        self,
        fake_mqtt_client: FakeMqttClient,
        z2m_emu: Z2mEmulator,
    ) -> None:
        client, rec = _make_client(fake_mqtt_client)
        z2m_emu.devices([{"ieee_address": "0x1", "friendly_name": "lamp", "type": "Router"}])
        assert len(rec.devices_calls) == 1

        client.refresh_device_list()
        devices_topic = f"{BASE}/bridge/devices"
        # Production API contract: refresh must drop and re-add the bridge/devices subscription.
        assert fake_mqtt_client.unsubscriptions.count(devices_topic) == 1
        # The most recent subscribe call must target bridge/devices.
        assert fake_mqtt_client.subscriptions[-1] == devices_topic
        # And after re-subscribe, the retained payload is replayed.
        assert len(rec.devices_calls) == 2
