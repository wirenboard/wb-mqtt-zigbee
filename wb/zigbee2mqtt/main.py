import argparse
import logging
import sys

from .app import EXIT_CONFIG_ERROR, WbZigbee2Mqtt
from .config_loader import CONFIG_FILEPATH, load_config

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main(argv: list) -> int:
    setup_logging()

    parser = argparse.ArgumentParser(description="Wiren Board Zigbee2MQTT bridge")
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

    logger.info("Starting wb-mqtt-zigbee, broker: %s", config.broker_url)
    service = WbZigbee2Mqtt(config)
    return service.run()
