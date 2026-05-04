"""Integration tests for `wb.mqtt_zigbee.app.WbZigbee2Mqtt` lifecycle.

Exercises the MQTT connect/disconnect flow at the application level: the
real `MQTTClient` constructor is replaced with one returning the per-test
`FakeMqttClient`, and `signal.signal` is stubbed to a no-op so the test
process is not affected by SIGINT/SIGTERM/SIGHUP handlers.

Connection events are triggered by calling `FakeMqttClient.connect(rc=...)`
and `FakeMqttClient.disconnect()`, which dispatch the `on_connect` /
`on_disconnect` callbacks `WbZigbee2Mqtt` registers in its constructor.

`fake_clock` is included so any time-based logic in `Bridge` (stats
throttling, command debounce) is deterministic.
"""

import pytest
from wb.mqtt_zigbee import app as app_module
from wb.mqtt_zigbee import bridge as bridge_module
from wb.mqtt_zigbee.app import (
    EXIT_NOSTART,
    EXIT_SUCCESS,
    MQTT_RC_AUTH_FAILURE,
    WbZigbee2Mqtt,
)
from wb.mqtt_zigbee.config_loader import ConfigLoader
from wb.mqtt_zigbee.wb_converter.controls import BridgeControl, WbBoolValue
from wb.mqtt_zigbee.wb_converter.publisher import DEVICES_PREFIX, DRIVER_NAME

from .fakes.client import FakeMqttClient
from .helpers.wb_observer import WbObserver
from .helpers.z2m_emulator import Z2mEmulator

BASE = "zigbee2mqtt"
BRIDGE_ID = "zigbee2mqtt"
BRIDGE_NAME = "Zigbee2MQTT bridge"


# Fixtures
@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> "list[float]":
    """Mutable single-element holder driving patched `time.monotonic` in Bridge."""
    holder = [0.0]
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: holder[0])
    return holder


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch,
    fake_mqtt_client: FakeMqttClient,
    fake_clock: "list[float]",
) -> WbZigbee2Mqtt:
    """Construct WbZigbee2Mqtt with `MQTTClient` and `signal.signal` stubbed.

    The `MQTTClient(...)` call inside `WbZigbee2Mqtt.__init__` is rerouted to
    return the shared `FakeMqttClient` from the test fixtures. `signal.signal`
    is replaced with a no-op so installing SIGINT/SIGTERM/SIGHUP handlers
    cannot interfere with the test runner.
    """
    _ = fake_clock  # keeps the time patch active for Bridge internals
    monkeypatch.setattr(app_module, "MQTTClient", lambda *args, **kwargs: fake_mqtt_client)
    monkeypatch.setattr(app_module.signal, "signal", lambda *args, **kwargs: None)
    config = ConfigLoader(
        broker_url="tcp://localhost:1883",
        zigbee2mqtt_base_topic=BASE,
        device_id=BRIDGE_ID,
        device_name=BRIDGE_NAME,
        bridge_log_min_level="warning",
        command_debounce_sec=5.0,
    )
    return WbZigbee2Mqtt(config)


# First connect
def test_first_connect_publishes_bridge_meta(
    app: WbZigbee2Mqtt,
    fake_mqtt_client: FakeMqttClient,
    wb_observer: WbObserver,
) -> None:
    fake_mqtt_client.connect(rc=0)

    meta = wb_observer.last_json_on(f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta")
    assert meta == {"driver": DRIVER_NAME, "title": {"en": BRIDGE_NAME, "ru": BRIDGE_NAME}}


def test_first_connect_subscribes_to_z2m_bridge_topics(
    app: WbZigbee2Mqtt,
    fake_mqtt_client: FakeMqttClient,
) -> None:
    fake_mqtt_client.connect(rc=0)

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


# Reconnect
def test_reconnect_increments_reconnect_counter(
    app: WbZigbee2Mqtt,
    fake_mqtt_client: FakeMqttClient,
    wb_observer: WbObserver,
) -> None:
    """connect → disconnect → connect must trigger Bridge.republish (not subscribe)."""
    fake_mqtt_client.connect(rc=0)
    fake_mqtt_client.disconnect()
    fake_mqtt_client.connect(rc=0)

    reconnects_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.RECONNECTS}"
    assert wb_observer.retained(reconnects_topic) == "1"

    # Another disconnect/connect cycle — counter advances.
    fake_mqtt_client.disconnect()
    fake_mqtt_client.connect(rc=0)
    assert wb_observer.retained(reconnects_topic) == "2"


def test_disconnect_marks_known_devices_unavailable(
    app: WbZigbee2Mqtt,
    fake_mqtt_client: FakeMqttClient,
    wb_observer: WbObserver,
    z2m_emu: Z2mEmulator,
) -> None:
    fake_mqtt_client.connect(rc=0)
    z2m_emu.devices(
        [
            {
                "ieee_address": "0x0001",
                "friendly_name": "sensor-1",
                "type": "EndDevice",
                "definition": {
                    "model": "M1",
                    "vendor": "V1",
                    "exposes": [
                        {
                            "type": "numeric",
                            "name": "temperature",
                            "property": "temperature",
                            "access": 1,
                        },
                    ],
                },
            },
        ]
    )
    available_topic = f"{DEVICES_PREFIX}/sensor-1/controls/available"

    fake_mqtt_client.disconnect()

    assert wb_observer.retained(available_topic) == WbBoolValue.FALSE


# Connect failure modes
def test_auth_failure_stops_client_and_sets_exit_code(
    app: WbZigbee2Mqtt,
    fake_mqtt_client: FakeMqttClient,
    wb_observer: WbObserver,
) -> None:
    """rc == 5 (auth failure) is terminal: the client is stopped and exit
    code is EXIT_NOSTART. The Bridge must not subscribe and must not publish
    any controls.
    """
    fake_mqtt_client.connect(rc=MQTT_RC_AUTH_FAILURE)

    # FakeMqttClient.stop() flips the internal flag (see fakes/client.py).
    assert fake_mqtt_client._stopped is True  # pylint: disable=protected-access
    assert app._exit_code == EXIT_NOSTART  # pylint: disable=protected-access
    # No bridge meta was published — auth failure aborts before subscribe().
    assert wb_observer.retained(f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta") is None


def test_non_auth_connect_failure_does_not_subscribe(
    app: WbZigbee2Mqtt,
    fake_mqtt_client: FakeMqttClient,
    wb_observer: WbObserver,
) -> None:
    """Generic connect rc != 0, != 5: log and wait; do not subscribe yet."""
    fake_mqtt_client.connect(rc=1)

    # Bridge.subscribe() did not run → no z2m bridge subscriptions, no meta.
    assert f"{BASE}/bridge/state" not in fake_mqtt_client.subscriptions
    assert wb_observer.retained(f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta") is None
    # Client was not stopped (only auth failure stops it).
    assert fake_mqtt_client._stopped is False  # pylint: disable=protected-access
    assert app._exit_code == EXIT_SUCCESS
