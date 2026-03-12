import argparse
import logging
import signal
import sys

from wb_common.mqtt_client import MQTTClient

from .config import CONFIG_FILEPATH, load_config

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_NOSTART = 2
EXIT_CONFIG_ERROR = 6
EXIT_SIGNAL = 7

MQTT_RC_AUTH_FAILURE = 5


class WbZigbee2Mqtt:  # pylint: disable=too-few-public-methods
    def __init__(self, broker_url: str) -> None:
        self._mqtt_was_disconnected = False
        self._exit_code = EXIT_SUCCESS

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._client = MQTTClient("wb-zigbee2mqtt", broker_url=broker_url, is_threaded=False)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(self, _client: object, _userdata: object, _flags: dict, rc: int) -> None:
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
            # TODO(victor.fedorov): Stage 2+ — republish all controls after reconnect

    def _on_disconnect(self, _client: object, _userdata: object, _flags: object) -> None:
        self._mqtt_was_disconnected = True
        logger.warning("MQTT disconnected")

    def _signal_handler(self, _signum: int, _frame: object) -> None:
        logger.info("Termination signal received, stopping")
        self._exit_code = EXIT_SIGNAL
        self._client.stop()

    def run(self) -> int:
        try:
            logger.info("Starting MQTT client")
            self._client.start()
            self._client.loop_forever()
        except ConnectionError:
            logger.exception("MQTT connection error")
            return EXIT_FAILURE
        return self._exit_code


def main(argv: list) -> int:
    setup_logging()

    parser = argparse.ArgumentParser(description="Wiren Board Zigbee2MQTT bridge v2")
    parser.add_argument(
        "-c",
        "--config",
        default=CONFIG_FILEPATH,
        help=f"Path to configuration file (default: {CONFIG_FILEPATH})",
    )
    args = parser.parse_args(argv[1:])

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        logger.error("%s", e)
        return EXIT_CONFIG_ERROR

    logger.info("Starting wb-zigbee2mqtt-v2, broker: %s", config.broker_url)
    service = WbZigbee2Mqtt(broker_url=config.broker_url)
    return service.run()
