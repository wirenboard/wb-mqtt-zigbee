import json
import logging
import os
from dataclasses import dataclass

CONFIG_FILEPATH = "/usr/lib/wb-zigbee2mqtt/configs/wb-zigbee2mqtt.conf"

logger = logging.getLogger(__name__)


BRIDGE_DEVICE_ID_DEFAULT = "zigbee2mqtt"
BRIDGE_DEVICE_NAME_DEFAULT = "Zigbee2MQTT"
BRIDGE_LOG_MIN_LEVEL_DEFAULT = "warning"


@dataclass
class ConfigLoader:
    broker_url: str
    zigbee2mqtt_base_topic: str
    device_id: str = BRIDGE_DEVICE_ID_DEFAULT
    device_name: str = BRIDGE_DEVICE_NAME_DEFAULT
    bridge_log_min_level: str = BRIDGE_LOG_MIN_LEVEL_DEFAULT


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
            broker_url=config["broker_url"],
            zigbee2mqtt_base_topic=config["zigbee2mqtt_base_topic"],
            device_id=config.get("device_id", BRIDGE_DEVICE_ID_DEFAULT),
            device_name=config.get("device_name", BRIDGE_DEVICE_NAME_DEFAULT),
            bridge_log_min_level=config.get("bridge_log_min_level", BRIDGE_LOG_MIN_LEVEL_DEFAULT),
        )
    except KeyError as e:
        raise ValueError(f"Missing required configuration key: {e}") from e
