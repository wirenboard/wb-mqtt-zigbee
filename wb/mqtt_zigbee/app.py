import logging
import signal
import threading
from typing import Any

from paho.mqtt.client import Client
from wb_common.mqtt_client import MQTTClient

from .bridge import Bridge
from .config_loader import ConfigLoader

logger = logging.getLogger(__name__)

# Exit codes from the WB service guideline; 2 and 6 are RestartPreventExitStatus in the unit.
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_INVALIDARGUMENT = 2
EXIT_CONFIG_ERROR = 6

# CONNACK codes for a rejected login: bad user name or password, not authorized
MQTT_AUTH_ERRORS = (4, 5)

# How long the stop waits for the broker to confirm the last topic removal; well under systemd's
# default 90 s stop timeout
REMOVAL_TIMEOUT_S = 10


class WbZigbee2Mqtt:  # pylint: disable=too-few-public-methods
    """
    Main service class: manages MQTT connection lifecycle, signal handling, and exit codes.

    The MQTT loop runs on paho's network thread, and so does all the bridge work, in its callbacks:
    subscribe on the first connect, republish on every reconnect. A reconnect may or may not be a
    broker restart (a network blip leaves every retained topic in place; mosquitto on WB runs
    without persistence, so a restart loses them all), and the two are indistinguishable here, so
    we republish unconditionally rather than guess. The session is not persistent (clean session),
    so paho restores no subscriptions and we re-subscribe. The main thread only waits for the
    stop request, which SIGINT/SIGTERM/SIGHUP and a rejected login set; it then removes our
    retained topics, waits for the broker to confirm them and stops the client.
    """

    def __init__(self, config: ConfigLoader) -> None:
        self._connected_once = False
        self._stop_requested = threading.Event()
        self._exit_code = EXIT_SUCCESS

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGHUP, self._signal_handler)

        self._client = MQTTClient("wb-mqtt-zigbee", broker_url=config.broker_url)
        # Route paho's internal logs (connect/reconnect/disconnect) into our logger.
        self._client.enable_logger(logger)
        # Message callbacks are individually wrapped with log_callback_errors so a bad
        # message can't crash the loop. on_connect reports a failed subscribe() to the main
        # thread instead, which exits non-zero so systemd restarts us.
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        self._bridge = Bridge(
            self._client,
            config.zigbee2mqtt_base_topic,
            config.device_id,
            config.device_name,
            config.bridge_log_min_level,
            config.command_debounce_sec,
        )

    def _on_connect(self, _client: Client, _userdata: Any, _flags: dict, rc: int) -> None:
        """Handle MQTT connect: subscribe on the first connect, republish on every later one"""
        if rc != 0:
            logger.error("MQTT connection failed with rc=%d", rc)
            if rc in MQTT_AUTH_ERRORS:
                # a rejected login is a configuration problem paho would retry forever: exit with 2,
                # at startup and after a reconnect alike; the main thread stops the client
                self._exit_code = EXIT_INVALIDARGUMENT
                self._stop_requested.set()
            return

        if self._stop_requested.is_set():
            return  # a reconnect inside the stop window must not republish what is being removed
        logger.info("MQTT connected")
        try:
            if self._connected_once:
                logger.info("Reconnected, republishing controls")
                self._bridge.republish()
            else:
                self._bridge.subscribe()
        except Exception:  # pylint: disable=broad-except
            # raised on paho's thread, it would only kill that thread and leave a live but idle
            # daemon: hand it to the main thread, which exits non-zero so that systemd restarts us
            logger.exception("MQTT setup failed")
            self._exit_code = EXIT_FAILURE
            self._stop_requested.set()
            return
        self._connected_once = True

    def _on_disconnect(self, _client: Client, _userdata: Any, _rc: int) -> None:
        """Mark every device unavailable until the reconnect republishes it"""
        if self._stop_requested.is_set():
            return  # our own DISCONNECT, or a loss nothing can be done about any more
        self._bridge.set_all_unavailable()
        logger.warning("MQTT disconnected")

    def _signal_handler(self, _signum: int, _frame: object) -> None:
        """Handle SIGINT/SIGTERM/SIGHUP: only wake the main thread, which does the stop work itself"""
        if self._stop_requested.is_set():
            return
        logger.info("Termination signal received, stopping")
        self._stop_requested.set()

    def _remove_retained_topics(self) -> None:
        """Take our retained topics off the broker; wait, bounded, for it to confirm the last one"""
        last = self._bridge.remove_all()
        try:
            last.wait_for_publish(timeout=REMOVAL_TIMEOUT_S)
            confirmed = last.is_published()
        except (RuntimeError, ValueError):  # paho: publish failed (no connection) or queue full
            confirmed = False
        if confirmed:
            return
        logger.error("MQTT broker did not confirm the retained topic removal, disconnecting anyway")
        # state DISCONNECTING lets paho's thread exit even with unacknowledged messages
        self._client.disconnect()

    def run(self) -> int:
        """Connect and block until stopped. Returns the exit code"""
        try:
            logger.info("Starting MQTT client")
            # an unavailable broker is retried by paho's thread until it answers or a signal ends the wait
            self._client.start(retry_first_connection=True)
            self._client.wait_for_connection(self._stop_requested)
            self._stop_requested.wait()  # the daemon's whole life happens in paho's callbacks
            if self._client.is_connected():
                self._remove_retained_topics()
            elif self._exit_code == EXIT_SUCCESS:
                # a rejected login (exit 2) got nothing of ours onto the broker: nothing to report
                logger.error("MQTT broker is not connected, retained topics cannot be removed")
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unexpected error in MQTT loop")
            return EXIT_FAILURE
        finally:
            self._client.stop()
        return self._exit_code
