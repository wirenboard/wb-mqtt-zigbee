import json

import pytest

from wb.zigbee2mqtt.config import Config, load_config


def test_load_config_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.conf")


def test_load_config_invalid_json(tmp_path) -> None:
    config_file = tmp_path / "config.conf"
    config_file.write_text("not a json{{{", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        load_config(str(config_file))


def test_load_config_missing_key(tmp_path) -> None:
    config_file = tmp_path / "config.conf"
    config_file.write_text(
        json.dumps({"broker_url": "unix:///var/run/mosquitto/mosquitto.sock"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Missing required configuration key"):
        load_config(str(config_file))


def test_load_config_custom_values(tmp_path) -> None:
    config_file = tmp_path / "config.conf"
    config_file.write_text(
        json.dumps(
            {
                "broker_url": "mqtt-tcp://localhost:1883",
                "zigbee2mqtt_base_topic": "z2m",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_file))

    assert config.broker_url == "mqtt-tcp://localhost:1883"
    assert config.zigbee2mqtt_base_topic == "z2m"


def test_load_config_returns_config_instance(tmp_path) -> None:
    config_file = tmp_path / "config.conf"
    config_file.write_text(
        json.dumps(
            {
                "broker_url": "unix:///var/run/mosquitto/mosquitto.sock",
                "zigbee2mqtt_base_topic": "zigbee2mqtt",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_file))

    assert isinstance(config, Config)
