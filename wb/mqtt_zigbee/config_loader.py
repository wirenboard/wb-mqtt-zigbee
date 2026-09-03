import json
import math
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from .z2m.model import BridgeLogLevel

CONFIG_FILEPATH = "/usr/share/wb-mqtt-zigbee/wb-mqtt-zigbee.conf"


BRIDGE_DEVICE_ID_DEFAULT = "zigbee2mqtt"
BRIDGE_DEVICE_NAME_DEFAULT = "Zigbee2MQTT"
BRIDGE_LOG_MIN_LEVEL_DEFAULT = BridgeLogLevel.WARNING
COMMAND_DEBOUNCE_SEC_DEFAULT = 5.0

_VALID_LOG_LEVELS = set(BridgeLogLevel.RANK.keys())
_BROKER_URL_SCHEMES_WITH_PORT = {"mqtt-tcp", "tcp", "ws"}


@dataclass
class ConfigLoader:
    broker_url: str
    zigbee2mqtt_base_topic: str
    device_id: str = BRIDGE_DEVICE_ID_DEFAULT
    device_name: str = BRIDGE_DEVICE_NAME_DEFAULT
    bridge_log_min_level: str = BRIDGE_LOG_MIN_LEVEL_DEFAULT
    command_debounce_sec: float = COMMAND_DEBOUNCE_SEC_DEFAULT


def load_config(config_path: str) -> ConfigLoader:
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as config_file:
        try:
            config = json.load(config_file)
        except json.JSONDecodeError as e:
            raise ValueError(f"Configuration file is not valid JSON: {e}") from e

    if not isinstance(config, dict):
        raise ValueError("Configuration root must be an object")

    try:
        return ConfigLoader(
            broker_url=_validate_broker_url(config["broker_url"]),
            zigbee2mqtt_base_topic=_validate_nonempty_string(
                "zigbee2mqtt_base_topic", config["zigbee2mqtt_base_topic"]
            ),
            device_id=_validate_nonempty_string(
                "device_id", config.get("device_id", BRIDGE_DEVICE_ID_DEFAULT)
            ),
            device_name=_validate_nonempty_string(
                "device_name", config.get("device_name", BRIDGE_DEVICE_NAME_DEFAULT)
            ),
            bridge_log_min_level=_validate_log_level(
                config.get("bridge_log_min_level", BRIDGE_LOG_MIN_LEVEL_DEFAULT)
            ),
            command_debounce_sec=_validate_command_debounce_sec(
                config.get("command_debounce_sec", COMMAND_DEBOUNCE_SEC_DEFAULT)
            ),
        )
    except KeyError as e:
        raise ValueError(f"Missing required configuration key: {e}") from e


def _validate_log_level(level: str) -> str:
    if level not in _VALID_LOG_LEVELS:
        raise ValueError(f"Unknown bridge_log_min_level: {level!r}")
    return level


def _validate_nonempty_string(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_command_debounce_sec(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("command_debounce_sec must be a non-negative number")
    try:
        result = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError("command_debounce_sec must be a non-negative number") from e
    if not math.isfinite(result) or result < 0:
        raise ValueError("command_debounce_sec must be a non-negative number")
    return result


def _validate_broker_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.scheme == "unix":
            if not parsed.path:
                raise ValueError("unix socket path is missing")
        elif parsed.scheme in _BROKER_URL_SCHEMES_WITH_PORT:
            if not parsed.hostname or not parsed.port:
                raise ValueError("host and port are required")
        else:
            raise ValueError(f"unknown scheme {parsed.scheme!r}")
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid broker_url {url!r}: {e}") from e
    return url
