import json
import logging
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from .z2m.model import BridgeLogLevel

CONFIG_FILEPATH = "/usr/lib/wb-mqtt-zigbee/configs/wb-mqtt-zigbee.conf"

logger = logging.getLogger(__name__)


BRIDGE_DEVICE_ID_DEFAULT = "zigbee2mqtt"
BRIDGE_DEVICE_NAME_DEFAULT = "Zigbee2MQTT"
BRIDGE_LOG_MIN_LEVEL_DEFAULT = BridgeLogLevel.WARNING
COMMAND_DEBOUNCE_SEC_DEFAULT = 5.0

_VALID_LOG_LEVELS = set(BridgeLogLevel.RANK.keys())


@dataclass
class ConfigLoader:
    broker_url: str
    zigbee2mqtt_base_topic: str
    device_id: str = BRIDGE_DEVICE_ID_DEFAULT
    device_name: str = BRIDGE_DEVICE_NAME_DEFAULT
    bridge_log_min_level: str = BRIDGE_LOG_MIN_LEVEL_DEFAULT
    command_debounce_sec: float = COMMAND_DEBOUNCE_SEC_DEFAULT


def check_broker_url(url: str) -> str:
    """
    The broker URL forms wb-common's MQTTClient accepts; anything else is a configuration error.
    The message never repeats the URL: it may carry a password and ends up in the journal.
    """
    try:
        parsed = urlparse(str(url))  # the JSON may hold a number instead of a string
        if parsed.scheme == "unix" and parsed.path:
            return url
        if parsed.scheme in ("tcp", "mqtt-tcp", "ws") and parsed.hostname and parsed.port:
            return url
    except ValueError:  # a non-numeric port
        pass
    raise ValueError("broker URL must be unix:///path or tcp://host:port (also mqtt-tcp://, ws://)")


def load_config(config_path: str) -> ConfigLoader:
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as config_file:
        try:
            config = json.load(config_file)
        except json.JSONDecodeError as e:
            raise ValueError(f"Configuration file is not valid JSON: {e}") from e

    try:
        return ConfigLoader(
            broker_url=check_broker_url(config["broker_url"]),
            zigbee2mqtt_base_topic=config["zigbee2mqtt_base_topic"],
            device_id=config.get("device_id", BRIDGE_DEVICE_ID_DEFAULT),
            device_name=config.get("device_name", BRIDGE_DEVICE_NAME_DEFAULT),
            bridge_log_min_level=_validate_log_level(
                config.get("bridge_log_min_level", BRIDGE_LOG_MIN_LEVEL_DEFAULT)
            ),
            command_debounce_sec=float(config.get("command_debounce_sec", COMMAND_DEBOUNCE_SEC_DEFAULT)),
        )
    except KeyError as e:
        raise ValueError(f"Missing required configuration key: {e}") from e


def _validate_log_level(level: str) -> str:
    if level not in _VALID_LOG_LEVELS:
        logger.warning("Unknown bridge_log_min_level '%s', using '%s'", level, BRIDGE_LOG_MIN_LEVEL_DEFAULT)
        return BRIDGE_LOG_MIN_LEVEL_DEFAULT
    return level
