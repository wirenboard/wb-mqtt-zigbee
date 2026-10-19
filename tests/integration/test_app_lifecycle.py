"""
Integration tests for `wb.mqtt_zigbee.app.WbZigbee2Mqtt` lifecycle.

Exercises the MQTT connect/disconnect flow at the application level: the real `MQTTClient`
constructor is replaced with one returning the per-test `FakeMqttClient`, and `signal.signal` is
stubbed to a no-op so the test process is not affected by SIGINT/SIGTERM/SIGHUP handlers.

In production the MQTT loop runs on paho's network thread; here the test plays that thread.
Connection events are `FakeMqttClient.connect(rc=...)` and `lose_connection()`, which dispatch the
`on_connect` / `on_disconnect` callbacks `WbZigbee2Mqtt` registers in its constructor. A test that
calls `run()` requests the stop first — by calling the app's signal handler directly, or from a side
effect of `wait_for_connection()` standing for what paho's thread delivered while the main thread
waited — otherwise `run()` would block forever.

`fake_clock` is included so any time-based logic in `Bridge` (stats throttling, command debounce)
is deterministic.
"""

import json
import logging
import signal
from typing import Callable

import pytest

from wb.mqtt_zigbee import app as app_module
from wb.mqtt_zigbee.app import (
    EXIT_FAILURE,
    EXIT_INVALIDARGUMENT,
    EXIT_SUCCESS,
    MQTT_AUTH_ERRORS,
    REMOVAL_TIMEOUT_S,
    WbZigbee2Mqtt,
)
from wb.mqtt_zigbee.config_loader import ConfigLoader
from wb.mqtt_zigbee.wb_converter.controls import BridgeControl, WbBoolValue
from wb.mqtt_zigbee.wb_converter.publisher import DEVICES_PREFIX, DRIVER_NAME

from .fakes.broker import FakeMqttBroker
from .fakes.client import FakeMqttClient
from .helpers.wb_observer import WbObserver
from .helpers.z2m_emulator import Z2mEmulator

BASE = "zigbee2mqtt"
BRIDGE_ID = "zigbee2mqtt"
BRIDGE_NAME = "Zigbee2MQTT bridge"
SENSOR = {
    "ieee_address": "0x0001",
    "friendly_name": "sensor-1",
    "type": "EndDevice",
    "definition": {
        "model": "M1",
        "vendor": "V1",
        "exposes": [{"type": "numeric", "name": "temperature", "property": "temperature", "access": 1}],
    },
}
SENSOR_2 = {**SENSOR, "ieee_address": "0x0002", "friendly_name": "sensor-2"}


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch,
    fake_mqtt_client: FakeMqttClient,
    fake_clock: "list[float]",
) -> WbZigbee2Mqtt:
    """
    Construct WbZigbee2Mqtt with `MQTTClient` and `signal.signal` stubbed.

    The `MQTTClient(...)` call inside `WbZigbee2Mqtt.__init__` is rerouted to return the shared
    `FakeMqttClient`; the factory also checks that the app asks for the threaded client, whose
    network thread runs the loop while the main thread only waits. `signal.signal` is replaced
    with a no-op so installing SIGINT/SIGTERM/SIGHUP handlers cannot interfere with the test runner.
    """
    _ = fake_clock  # keeps the time patch active for Bridge internals

    def make_client(*_args: object, **kwargs: object) -> FakeMqttClient:
        assert kwargs.get("is_threaded", True), "the MQTT loop must run on paho's network thread"
        return fake_mqtt_client

    monkeypatch.setattr(app_module, "MQTTClient", make_client)
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


def _sigterm(app: WbZigbee2Mqtt) -> None:
    """
    What systemd's stop does to the process: the handler must only wake the main thread
    """
    app._signal_handler(signal.SIGTERM, None)  # pylint: disable=protected-access


def _while_waiting_for_connection(fake_mqtt_client: FakeMqttClient, *events: Callable[[], None]) -> None:
    """
    Play paho's network thread during run(): the events happen while the main thread waits in
    wait_for_connection(), which then reports whether the client ended up connected. Set on the
    per-test fake instance, so nothing outlives the test.
    """

    def wait_for_connection(_stop_requested: object) -> bool:
        for event in events:
            event()
        return fake_mqtt_client.is_connected()

    fake_mqtt_client.wait_for_connection = wait_for_connection


def _removals_of(wb_observer: WbObserver, topic: str) -> int:
    """
    How many times the topic was cleared (an empty retained publish)
    """
    return sum(1 for message in wb_observer.messages_on(topic) if message.retain and message.payload == b"")


class TestFirstConnect:
    """
    Initial successful MQTT connection (rc == 0)
    """

    def test_publishes_bridge_meta(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        fake_mqtt_client.connect(rc=0)

        meta = wb_observer.last_json_on(f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta")
        assert meta == {"driver": DRIVER_NAME, "title": {"en": BRIDGE_NAME, "ru": BRIDGE_NAME}}

    def test_subscribes_to_z2m_bridge_topics(
        self,
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


class TestReconnect:
    """
    Behaviour after a connect → disconnect → connect cycle
    """

    def test_increments_reconnect_counter(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        """connect → disconnect → connect must trigger Bridge.republish (not subscribe)."""
        fake_mqtt_client.connect(rc=0)
        fake_mqtt_client.lose_connection()
        fake_mqtt_client.connect(rc=0)

        reconnects_topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.RECONNECTS}"
        assert wb_observer.retained(reconnects_topic) == "1"

        # Another disconnect/connect cycle — counter advances.
        fake_mqtt_client.lose_connection()
        fake_mqtt_client.connect(rc=0)
        assert wb_observer.retained(reconnects_topic) == "2"

    def test_disconnect_marks_known_devices_unavailable(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
        z2m_emu: Z2mEmulator,
    ) -> None:
        fake_mqtt_client.connect(rc=0)
        z2m_emu.devices([SENSOR])
        available_topic = f"{DEVICES_PREFIX}/sensor-1/controls/available"

        fake_mqtt_client.lose_connection()

        assert wb_observer.retained(available_topic) == WbBoolValue.FALSE


class TestConnectFailureModes:
    """
    Non-zero `rc` codes from MQTT CONNACK
    """

    @pytest.mark.parametrize("rc", MQTT_AUTH_ERRORS)
    def test_rejected_login_exits_2_with_no_removal_and_no_error_line(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
        caplog: pytest.LogCaptureFixture,
        rc: int,
    ) -> None:
        """
        A rejected login (bad credentials, not authorized) is terminal: on_connect only requests
        the stop, the main thread stops the client once, and run() returns EXIT_INVALIDARGUMENT,
        which the unit does not restart. Nothing of ours reached the broker, so there is nothing
        to remove and no "cannot be removed" line in the journal; the Bridge must not subscribe.
        """
        _while_waiting_for_connection(fake_mqtt_client, lambda: fake_mqtt_client.connect(rc=rc))

        with caplog.at_level(logging.ERROR):
            assert app.run() == EXIT_INVALIDARGUMENT

        assert fake_mqtt_client.calls == ["start", "stop"]
        assert wb_observer.all_messages() == []
        assert f"{BASE}/bridge/state" not in fake_mqtt_client.subscriptions
        assert "retained topics cannot be removed" not in caplog.text

    def test_auth_failure_after_a_reconnect_is_terminal_too(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
    ) -> None:
        """
        The broker came back with another password file: the rejected reconnect ends the daemon
        with exit code 2 just like a rejected first login does.
        """
        _while_waiting_for_connection(
            fake_mqtt_client,
            lambda: fake_mqtt_client.connect(rc=0),
            fake_mqtt_client.lose_connection,
            lambda: fake_mqtt_client.connect(rc=5),
        )

        assert app.run() == EXIT_INVALIDARGUMENT
        assert fake_mqtt_client.calls == ["start", "stop"]

    def test_non_auth_failure_does_not_subscribe(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        """
        Generic connect rc != 0, != 5: log and wait; do not subscribe yet.
        """
        fake_mqtt_client.connect(rc=1)

        # Bridge.subscribe() did not run → no z2m bridge subscriptions, no meta.
        assert f"{BASE}/bridge/state" not in fake_mqtt_client.subscriptions
        assert wb_observer.retained(f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta") is None
        # Only a rejected login asks for the stop; paho keeps retrying this one.
        assert not app._stop_requested.is_set()  # pylint: disable=protected-access
        assert app._exit_code == EXIT_SUCCESS  # pylint: disable=protected-access

    def test_subscribe_failure_exits_1_so_systemd_restarts_us(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        A failure inside on_connect (here Bridge.subscribe) happens on paho's network thread, where
        an escaping exception would only kill that thread and leave a live-but-idle daemon. It must
        reach run() instead, which returns EXIT_FAILURE with the traceback in the journal.
        """

        def boom() -> None:
            raise RuntimeError("subscribe failed")

        monkeypatch.setattr(app._bridge, "subscribe", boom)  # pylint: disable=protected-access
        _while_waiting_for_connection(fake_mqtt_client, lambda: fake_mqtt_client.connect(rc=0))

        with caplog.at_level(logging.ERROR):
            assert app.run() == EXIT_FAILURE

        assert "subscribe failed" in caplog.text
        assert fake_mqtt_client.stopped


class TestStop:
    """
    SIGINT/SIGTERM/SIGHUP: our retained topics are removed, confirmed by the broker, and run()
    returns 0
    """

    def test_signal_removes_the_bridge_and_every_device_once_and_exits_0(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
        z2m_emu: Z2mEmulator,
    ) -> None:
        """
        The handler itself publishes nothing; the main thread removes every device and the bridge
        exactly once, waits for the last removal with the bounded timeout and stops the client
        only once the broker acknowledged it. sensor-1 was published while the startup scan was
        still open, so the scan saw it too and it must not be removed a second time; sensor-2
        joined after the scan closed, so only the known-devices pass can remove it. The clean
        DISCONNECT that stop() reports must not republish anything.
        """
        fake_mqtt_client.connect(rc=0)
        z2m_emu.devices([SENSOR])
        z2m_emu.devices([SENSOR, SENSOR_2])
        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-2/meta") is not None

        _sigterm(app)
        assert wb_observer.retained(f"{DEVICES_PREFIX}/sensor-1/meta") is not None
        assert not fake_mqtt_client.stopped

        assert app.run() == EXIT_SUCCESS

        assert wb_observer.retained_under(DEVICES_PREFIX) == {}
        assert _removals_of(wb_observer, f"{DEVICES_PREFIX}/sensor-1/meta") == 1
        assert _removals_of(wb_observer, f"{DEVICES_PREFIX}/sensor-2/meta") == 1
        assert _removals_of(wb_observer, f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta") == 1
        assert fake_mqtt_client.last_publish.waited_with_timeout == REMOVAL_TIMEOUT_S
        assert fake_mqtt_client.calls == ["start", "stop"]
        assert not fake_mqtt_client.stopped_with_unacknowledged

    def test_ghost_of_a_previous_run_is_removed_too(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
        fake_broker: FakeMqttBroker,
    ) -> None:
        """
        A device left retained by a previous run and not yet scrubbed (zigbee2mqtt never sent its
        device list this time) is still ours: the stop takes it off the broker as well.
        """
        ghost_meta = json.dumps({"driver": DRIVER_NAME, "title": {"en": "G", "ru": "G"}})
        fake_broker.inject(f"{DEVICES_PREFIX}/ghost/meta", ghost_meta, retain=True)
        fake_broker.inject(f"{DEVICES_PREFIX}/ghost/controls/temperature/meta", "{}", retain=True)
        fake_mqtt_client.connect(rc=0)

        _sigterm(app)
        assert app.run() == EXIT_SUCCESS

        assert wb_observer.retained_under(f"{DEVICES_PREFIX}/ghost") == {}
        assert _removals_of(wb_observer, f"{DEVICES_PREFIX}/ghost/meta") == 1

    def test_z2m_traffic_during_the_removal_is_ignored(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
        z2m_emu: Z2mEmulator,
        fake_clock: "list[float]",
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        While the main thread waits for the broker to confirm the removals, paho's thread keeps
        delivering zigbee2mqtt traffic to the bridge. None of it may republish a topic that has
        just been removed — the bridge state, device state and availability, the stats counters —
        and neither may a broker reconnect inside that window republish everything.
        """
        fake_mqtt_client.connect(rc=0)
        z2m_emu.devices([SENSOR])
        bridge = app._bridge  # pylint: disable=protected-access
        remove_all = bridge.remove_all

        def remove_all_then_traffic_arrives() -> object:
            last = remove_all()
            fake_clock[0] += 2.0  # the stats throttle is over: _update_stats would publish
            z2m_emu.online()
            z2m_emu.info()
            z2m_emu.log("error", "a line")
            z2m_emu.device_state("sensor-1", {"temperature": 21.5})
            z2m_emu.device_availability("sensor-1", online=True)
            z2m_emu.devices([SENSOR])
            fake_mqtt_client.lose_connection()
            fake_mqtt_client.connect(rc=0)  # paho reconnected: no republish either
            return last

        monkeypatch.setattr(bridge, "remove_all", remove_all_then_traffic_arrives)

        _sigterm(app)
        assert app.run() == EXIT_SUCCESS

        assert wb_observer.retained_under(DEVICES_PREFIX) == {}

    def test_unconfirmed_removal_logs_an_error_and_disconnects_before_the_stop(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        z2m_emu: Z2mEmulator,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        The connection is up but the broker never acknowledges (out of memory, stuck): the stop must
        not hang until systemd kills us. After the timeout it says so in the journal and forces the
        DISCONNECT before stop(), so paho's thread can exit with the unacknowledged removals.
        """
        fake_mqtt_client.connect(rc=0)
        z2m_emu.devices([SENSOR])
        fake_mqtt_client.broker_acknowledges = False

        _sigterm(app)
        with caplog.at_level(logging.ERROR):
            assert app.run() == EXIT_SUCCESS

        assert "did not confirm the retained topic removal" in caplog.text
        assert fake_mqtt_client.calls == ["start", "disconnect", "stop"]

    def test_signal_without_a_broker_logs_an_error_and_exits_0(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        The broker is away and paho's thread is still retrying when the signal lands: nothing of
        ours can be removed, the stop says so once in the journal and still ends cleanly.
        """
        _while_waiting_for_connection(fake_mqtt_client, lambda: _sigterm(app))

        with caplog.at_level(logging.ERROR):
            assert app.run() == EXIT_SUCCESS

        assert "retained topics cannot be removed" in caplog.text
        assert wb_observer.all_messages() == []
        assert fake_mqtt_client.calls == ["start", "stop"]


class TestRun:
    """
    WbZigbee2Mqtt.run(): the daemon shape and its error handling
    """

    def test_clean_start_enters_the_daemon_life(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
        z2m_emu: Z2mEmulator,
    ) -> None:
        """
        The production sequence, start to finish: start() returns before the CONNACK, the
        connection and the whole life of the daemon happen while the main thread waits, and the
        signal ends it with the removal and the stop. run() must not return before that.
        """
        _while_waiting_for_connection(
            fake_mqtt_client,
            lambda: fake_mqtt_client.connect(rc=0),
            lambda: z2m_emu.devices([SENSOR]),
            lambda: _sigterm(app),
        )

        assert app.run() == EXIT_SUCCESS

        assert fake_mqtt_client.retry_first_connection is True
        assert _removals_of(wb_observer, f"{DEVICES_PREFIX}/sensor-1/meta") == 1
        assert _removals_of(wb_observer, f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta") == 1
        assert fake_mqtt_client.calls == ["start", "stop"]

    @pytest.mark.parametrize("error", [RuntimeError("client blew up"), ConnectionError("no broker")])
    def test_start_error_returns_exit_failure_and_still_stops(
        self,
        app: WbZigbee2Mqtt,
        fake_mqtt_client: FakeMqttClient,
        monkeypatch: pytest.MonkeyPatch,
        error: Exception,
    ) -> None:
        """
        An unexpected error in the MQTT client is caught and mapped to EXIT_FAILURE; the client
        is stopped all the same.
        """

        def boom(**_kwargs: object) -> None:
            raise error

        monkeypatch.setattr(fake_mqtt_client, "start", boom)

        assert app.run() == EXIT_FAILURE
        assert fake_mqtt_client.stopped
