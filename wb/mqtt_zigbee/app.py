import logging
import signal

from wb_common.mqtt_client import MQTTClient

from .bridge import Bridge
from .config_loader import ConfigLoader

logger = logging.getLogger(__name__)

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_NOSTART = 2
EXIT_CONFIG_ERROR = 6
EXIT_SIGNAL = 7

MQTT_RC_AUTH_FAILURE = 5


class WbZigbee2Mqtt:  # pylint: disable=too-few-public-methods
    """Main service class: manages MQTT connection lifecycle, signal handling, and exit codes.

    On first connect, subscribes to zigbee2mqtt topics and publishes bridge controls.
    On reconnect, republishes bridge controls to restore retained state.
    Handles SIGINT/SIGTERM for graceful shutdown.
    """

    def __init__(self, config: ConfigLoader) -> None:
        self._mqtt_was_disconnected = False
        self._exit_code = EXIT_SUCCESS

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGHUP, self._signal_handler)

        self._client = MQTTClient("wb-mqtt-zigbee", broker_url=config.broker_url, is_threaded=False)
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

    def _on_connect(self, _client: object, _userdata: object, _flags: dict, rc: int) -> None:
        """Handle MQTT connect: subscribe on first connect, republish on reconnect"""
        if rc == MQTT_RC_AUTH_FAILURE:
            logger.error("MQTT authentication failed, stopping")
            self._exit_code = EXIT_NOSTART
            self._client.stop()
            return

        if rc != 0:
            logger.error("MQTT connection failed with rc=%d", rc)
            return

        logger.info("MQTT connected")

        if self._mqtt_was_disconnected:
            logger.info("Reconnected, republishing controls")
            self._bridge.republish()
        else:
            self._bridge.subscribe()

        self._mqtt_was_disconnected = False

    def _on_disconnect(self, _client: object, _userdata: object, _flags: object) -> None:
        """Mark connection as lost so next connect triggers republish"""
        self._mqtt_was_disconnected = True
        logger.warning("MQTT disconnected")

    def _signal_handler(self, _signum: int, _frame: object) -> None:
        """Handle SIGINT/SIGTERM: set exit code and stop MQTT client"""
        logger.info("Termination signal received, stopping")
        self._exit_code = EXIT_SIGNAL
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
        return self._exit_code
