import logging
import signal
import threading
from typing import Any, Optional

from paho.mqtt.client import Client
from wb_common.mqtt_client import MQTTClient

from .bridge import Bridge
from .config_loader import ConfigLoader

logger = logging.getLogger(__name__)

EXIT_FAILURE = 1
EXIT_NOSTART = 2
EXIT_CONFIG_ERROR = 6
EXIT_SIGNAL = 7

MQTT_RC_BAD_CREDENTIALS = 4
MQTT_RC_AUTH_FAILURE = 5
MQTT_RC_SUCCESS = 0
SHUTDOWN_TIMEOUT_SEC = 5.0


class WbZigbee2Mqtt:  # pylint: disable=too-few-public-methods
    """Main service class: manages MQTT connection lifecycle, signal handling, and exit codes.

    On first connect, subscribes to zigbee2mqtt topics and publishes bridge controls.
    On reconnect, republishes bridge controls to restore retained state.
    Handles SIGINT/SIGTERM for graceful shutdown.
    """

    def __init__(self, config: ConfigLoader) -> None:
        self._connected_once = False
        self._mqtt_connected = False
        # A daemon returning from its network loop without an explicit stop is a
        # failure and must be restarted by systemd.
        self._exit_code = EXIT_FAILURE
        self._shutdown_mids: set[int] = set()
        self._shutdown_timer: Optional[threading.Timer] = None
        self._shutdown_lock = threading.Lock()
        self._shutdown_finished = False
        self._shutdown_error_reported = False

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGHUP, self._signal_handler)

        self._client = MQTTClient("wb-mqtt-zigbee", broker_url=config.broker_url, is_threaded=False)
        # Route paho's internal logs (connect/reconnect/disconnect) into our logger.
        self._client.enable_logger(logger)
        # Message callbacks are individually wrapped with log_callback_errors so a bad
        # message can't crash the loop. on_connect stays unguarded on purpose: a failed
        # subscribe() must exit non-zero (run's except) so systemd restarts us.
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_publish = self._on_publish

        self._bridge = Bridge(
            self._client,
            config.zigbee2mqtt_base_topic,
            config.device_id,
            config.device_name,
            config.bridge_log_min_level,
            config.command_debounce_sec,
        )

    def _on_connect(self, _client: Client, _userdata: Any, _flags: dict, rc: int) -> None:
        """Handle MQTT connect: subscribe on first connect, republish on reconnect"""
        if rc in (MQTT_RC_BAD_CREDENTIALS, MQTT_RC_AUTH_FAILURE):
            logger.error("MQTT authentication failed, stopping")
            self._exit_code = EXIT_NOSTART
            self._client.stop()
            return

        if rc != 0:
            logger.error("MQTT connection failed with rc=%d", rc)
            return

        logger.info("MQTT connected")
        self._mqtt_connected = True

        if self._connected_once:
            logger.info("Reconnected, republishing controls")
            self._bridge.republish()
        else:
            self._bridge.subscribe()
            self._connected_once = True

    def _on_disconnect(self, _client: Client, _userdata: Any, _flags: dict) -> None:
        """Mark connection as lost so next connect triggers republish"""
        was_connected = self._mqtt_connected
        self._mqtt_connected = False
        if self._exit_code == EXIT_SIGNAL:
            if self._shutdown_mids:
                self._report_shutdown_error("MQTT disconnected before retained topics were removed")
            self._finish_shutdown()
            return
        if self._exit_code == EXIT_NOSTART:
            return
        if was_connected:
            logger.warning("MQTT disconnected")

    def _on_publish(self, _client: Client, _userdata: Any, mid: int) -> None:
        """Stop the client after every retained-topic removal is acknowledged."""
        if self._exit_code != EXIT_SIGNAL:
            return
        with self._shutdown_lock:
            self._shutdown_mids.discard(mid)
            cleanup_finished = not self._shutdown_mids
        if cleanup_finished:
            self._finish_shutdown()

    def _signal_handler(self, _signum: int, _frame: object) -> None:
        """Handle termination: remove retained topics, then stop the MQTT client."""
        if self._exit_code == EXIT_SIGNAL:
            self._report_shutdown_error("Retained-topic cleanup interrupted by another signal")
            self._finish_shutdown()
            return
        logger.info("Termination signal received, stopping")
        self._exit_code = EXIT_SIGNAL
        try:
            published = self._bridge.shutdown()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to remove retained topics during shutdown")
            self._shutdown_error_reported = True
            self._finish_shutdown()
            return

        failed = [info for info in published if getattr(info, "rc", 1) != MQTT_RC_SUCCESS]
        if failed:
            self._report_shutdown_error(f"Failed to publish {len(failed)} retained-topic removals")

        with self._shutdown_lock:
            self._shutdown_mids = {
                info.mid
                for info in published
                if getattr(info, "rc", 1) == MQTT_RC_SUCCESS and not info.is_published()
            }
        if failed or not self._shutdown_mids:
            self._finish_shutdown()
            return

        self._shutdown_timer = threading.Timer(SHUTDOWN_TIMEOUT_SEC, self._shutdown_timeout)
        self._shutdown_timer.daemon = True
        self._shutdown_timer.start()

    def _shutdown_timeout(self) -> None:
        with self._shutdown_lock:
            pending_count = len(self._shutdown_mids)
        if pending_count:
            self._report_shutdown_error(
                f"Timed out with {pending_count} retained-topic removals unacknowledged"
            )
        self._finish_shutdown()

    def _report_shutdown_error(self, message: str) -> None:
        if self._shutdown_error_reported:
            return
        self._shutdown_error_reported = True
        logger.error("%s", message)

    def _finish_shutdown(self) -> None:
        """Stop once after cleanup delivery, disconnect, or timeout."""
        with self._shutdown_lock:
            if self._shutdown_finished:
                return
            self._shutdown_finished = True
            timer = self._shutdown_timer
        if timer is not None:
            timer.cancel()
        self._client.stop()

    def run(self) -> int:
        """Start MQTT client and block until stopped. Returns exit code"""
        try:
            logger.info("Starting MQTT client")
            self._client.start()
            self._client.loop_forever()
        except ConnectionError:
            logger.exception("MQTT connection error")
            return EXIT_FAILURE
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unexpected error in MQTT loop")
            return EXIT_FAILURE
        return self._exit_code
