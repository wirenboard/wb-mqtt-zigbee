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


# -- Test harness ---------------------------------------------------------------


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


# -- bridge/state ---------------------------------------------------------------


@pytest.mark.parametrize("state", ["online", "offline", "error"])
def test_bridge_state_plain_string(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator, state: str
) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.state_raw(state, retain=True)
    assert rec.bridge_states == [state]


def test_bridge_state_json_object(fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.state_raw(json.dumps({"state": "online"}), retain=True)
    assert rec.bridge_states == ["online"]


def test_bridge_state_unknown_value_ignored(fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.state_raw("starting", retain=True)
    assert not rec.bridge_states


# -- bridge/info ----------------------------------------------------------------


def test_bridge_info_full_payload(fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.info(version="1.42.0", permit_join=True, permit_join_end=1700000000)
    assert rec.bridge_infos == [BridgeInfo(version="1.42.0", permit_join=True, permit_join_end=1700000000)]


def test_bridge_info_empty_payload_uses_defaults(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.info_raw(json.dumps({}))
    assert rec.bridge_infos == [BridgeInfo(version="", permit_join=False, permit_join_end=None)]


def test_bridge_info_invalid_json_skipped(fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.info_raw("not json")
    assert not rec.bridge_infos


# -- bridge/logging -------------------------------------------------------------


def test_bridge_log_valid_payload(fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.log("warning", "something happened")
    assert rec.bridge_logs == [("warning", "something happened")]


def test_bridge_log_invalid_json_falls_back_to_raw(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.log_raw("not json at all")
    assert rec.bridge_logs == [("info", "not json at all")]


# -- bridge/devices -------------------------------------------------------------


def test_bridge_devices_excludes_coordinator_and_parses_rest(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
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
    assert [d.friendly_name for d in devices] == ["lamp"]
    assert devices[0].vendor == "V1"


def test_bridge_devices_one_broken_does_not_affect_others(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    # First device has `definition` of a wrong shape (str instead of dict) — would
    # raise during from_dict; the second one must still be parsed.
    z2m_emu.devices_raw(
        json.dumps(
            [
                {"ieee_address": "0x1", "friendly_name": "broken", "type": "Router", "definition": "oops"},
                {"ieee_address": "0x2", "friendly_name": "ok", "type": "Router"},
            ]
        )
    )
    assert len(rec.devices_calls) == 1
    assert [d.friendly_name for d in rec.devices_calls[0]] == ["ok"]


# -- bridge/event ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("z2m_type", "expected_internal"),
    [
        ("device_joined", DeviceEventType.JOINED),
        ("device_leave", DeviceEventType.LEFT),
    ],
)
def test_bridge_event_join_leave_mapped(
    fake_mqtt_client: FakeMqttClient,
    z2m_emu: Z2mEmulator,
    z2m_type: str,
    expected_internal: str,
) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.event(z2m_type, {"friendly_name": "lamp", "ieee_address": "0xaa"})
    assert rec.device_events == [DeviceEvent(type=expected_internal, name="lamp")]


def test_bridge_event_renamed_carries_old_and_new_name(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.device_renamed(from_name="old", to_name="new")
    assert rec.device_events == [DeviceEvent(type=DeviceEventType.RENAMED, name="new", old_name="old")]


def test_bridge_event_unknown_type_ignored(fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.event("device_announce", {"friendly_name": "lamp"})
    assert not rec.device_events


# -- bridge/response/device/remove ---------------------------------------------


def test_remove_response_ok_emits_removed_event(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.remove_response(status="ok", id_="lamp")
    assert rec.device_events == [DeviceEvent(type=DeviceEventType.REMOVED, name="lamp")]


def test_remove_response_error_status_ignored(fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.remove_response(status="error", id_="lamp")
    assert not rec.device_events


# -- +/availability -------------------------------------------------------------


def test_device_availability_online(fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.device_availability("lamp", online=True)
    assert rec.availability == [("lamp", True)]


def test_device_availability_offline(fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.device_availability("lamp", online=False)
    assert rec.availability == [("lamp", False)]


def test_device_availability_for_bridge_is_ignored(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.device_availability("bridge", online=True)
    assert not rec.availability


def test_device_availability_invalid_json_skipped(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
) -> None:
    _client, rec = _make_client(fake_mqtt_client)
    z2m_emu.device_availability_raw("lamp", "not json")
    assert not rec.availability


# -- per-device state -----------------------------------------------------------


def test_device_state_received_after_subscribe_device(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
) -> None:
    client, rec = _make_client(fake_mqtt_client)
    client.subscribe_device("lamp")
    z2m_emu.device_state("lamp", {"state": "ON", "brightness": 200})
    assert rec.device_states == [("lamp", {"state": "ON", "brightness": 200})]


def test_unsubscribe_device_stops_state_callbacks(
    fake_mqtt_client: FakeMqttClient, z2m_emu: Z2mEmulator
) -> None:
    client, rec = _make_client(fake_mqtt_client)
    client.subscribe_device("lamp")
    client.unsubscribe_device("lamp")
    z2m_emu.device_state("lamp", {"state": "ON"})
    assert not rec.device_states


def test_subscribe_device_is_idempotent(fake_mqtt_client: FakeMqttClient) -> None:
    client, _rec = _make_client(fake_mqtt_client)
    client.subscribe_device("lamp")
    subs_after_first = list(fake_mqtt_client.subscriptions)
    client.subscribe_device("lamp")
    # Second call must NOT add another `zigbee2mqtt/lamp` subscription
    assert fake_mqtt_client.subscriptions == subs_after_first


# -- outgoing commands ----------------------------------------------------------


def test_set_permit_join_enabled_publishes_254(
    fake_mqtt_client: FakeMqttClient, wb_observer: WbObserver
) -> None:
    client, _rec = _make_client(fake_mqtt_client)
    client.set_permit_join(True)
    msg = wb_observer.last_on(f"{BASE}/bridge/request/permit_join")
    assert msg is not None
    assert json.loads(msg.payload.decode("utf-8")) == {"time": 254}


def test_set_permit_join_disabled_publishes_zero(
    fake_mqtt_client: FakeMqttClient, wb_observer: WbObserver
) -> None:
    client, _rec = _make_client(fake_mqtt_client)
    client.set_permit_join(False)
    msg = wb_observer.last_on(f"{BASE}/bridge/request/permit_join")
    assert msg is not None
    assert json.loads(msg.payload.decode("utf-8")) == {"time": 0}


def test_request_device_state_publishes_empty_object(
    fake_mqtt_client: FakeMqttClient, wb_observer: WbObserver
) -> None:
    client, _rec = _make_client(fake_mqtt_client)
    client.request_device_state("lamp")
    msg = wb_observer.last_on(f"{BASE}/lamp/get")
    assert msg is not None
    assert msg.payload == b"{}"


def test_set_device_state_publishes_payload_json(
    fake_mqtt_client: FakeMqttClient, wb_observer: WbObserver
) -> None:
    client, _rec = _make_client(fake_mqtt_client)
    client.set_device_state("lamp", {"state": "ON", "brightness": 128})
    msg = wb_observer.last_on(f"{BASE}/lamp/set")
    assert msg is not None
    assert json.loads(msg.payload.decode("utf-8")) == {"state": "ON", "brightness": 128}


def test_refresh_device_list_re_subscribes(
    fake_mqtt_client: FakeMqttClient,
    z2m_emu: Z2mEmulator,
) -> None:
    client, rec = _make_client(fake_mqtt_client)
    z2m_emu.devices([{"ieee_address": "0x1", "friendly_name": "lamp", "type": "Router"}])
    assert len(rec.devices_calls) == 1

    client.refresh_device_list()
    # After re-subscribe, retained `bridge/devices` is replayed by the broker
    assert len(rec.devices_calls) == 2
