import json
import logging
import os
from dataclasses import dataclass

CONFIG_FILEPATH = "/etc/wb-zigbee2mqtt/wb-zigbee2mqtt.conf"

logger = logging.getLogger(__name__)


@dataclass
class Config:
    broker_url: str
    zigbee2mqtt_base_topic: str


def load_config(config_path: str) -> Config:
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as config_file:
        try:
            config = json.load(config_file)
        except json.JSONDecodeError as e:
            raise ValueError(f"Configuration file is not valid JSON: {e}") from e

    try:
        return Config(
            broker_url=config["broker_url"],
            zigbee2mqtt_base_topic=config["zigbee2mqtt_base_topic"],
        )
    except KeyError as e:
        raise ValueError(f"Missing required configuration key: {e}") from e
