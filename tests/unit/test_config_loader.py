"""Unit tests for wb.mqtt_zigbee.config_loader."""

import json
import logging

import pytest

from wb.mqtt_zigbee.config_loader import (
    BRIDGE_DEVICE_ID_DEFAULT,
    BRIDGE_DEVICE_NAME_DEFAULT,
    BRIDGE_LOG_MIN_LEVEL_DEFAULT,
    COMMAND_DEBOUNCE_SEC_DEFAULT,
    ConfigLoader,
    _validate_log_level,
    load_config,
)
from wb.mqtt_zigbee.z2m.model import BridgeLogLevel


def write_config(tmp_path, data):
    """Write a config dict as JSON to tmp_path/config.json and return the path."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestLoadConfigSuccess:
    def test_minimal_config_uses_defaults(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "broker_url": "tcp://localhost:1883",
                "zigbee2mqtt_base_topic": "zigbee2mqtt",
            },
        )
        cfg = load_config(path)
        assert isinstance(cfg, ConfigLoader)
        assert cfg.broker_url == "tcp://localhost:1883"
        assert cfg.zigbee2mqtt_base_topic == "zigbee2mqtt"
        assert cfg.device_id == BRIDGE_DEVICE_ID_DEFAULT
        assert cfg.device_name == BRIDGE_DEVICE_NAME_DEFAULT
        assert cfg.bridge_log_min_level == BRIDGE_LOG_MIN_LEVEL_DEFAULT
        assert cfg.command_debounce_sec == COMMAND_DEBOUNCE_SEC_DEFAULT
        assert isinstance(cfg.command_debounce_sec, float)

    def test_full_config_overrides_all_defaults(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "broker_url": "tcp://broker:1883",
                "zigbee2mqtt_base_topic": "z2m",
                "device_id": "my_zigbee",
                "device_name": "My Zigbee Bridge",
                "bridge_log_min_level": BridgeLogLevel.ERROR,
                "command_debounce_sec": 2.5,
            },
        )
        cfg = load_config(path)
        assert cfg.device_id == "my_zigbee"
        assert cfg.device_name == "My Zigbee Bridge"
        assert cfg.bridge_log_min_level == BridgeLogLevel.ERROR
        assert cfg.command_debounce_sec == 2.5

    def test_command_debounce_sec_int_is_converted_to_float(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "broker_url": "tcp://localhost:1883",
                "zigbee2mqtt_base_topic": "z2m",
                "command_debounce_sec": 10,
            },
        )
        cfg = load_config(path)
        assert cfg.command_debounce_sec == 10.0
        assert isinstance(cfg.command_debounce_sec, float)

    @pytest.mark.parametrize(
        "level",
        [BridgeLogLevel.DEBUG, BridgeLogLevel.INFO, BridgeLogLevel.WARNING, BridgeLogLevel.ERROR],
    )
    def test_all_valid_log_levels_accepted(self, tmp_path, level):
        path = write_config(
            tmp_path,
            {
                "broker_url": "tcp://localhost:1883",
                "zigbee2mqtt_base_topic": "z2m",
                "bridge_log_min_level": level,
            },
        )
        cfg = load_config(path)
        assert cfg.bridge_log_min_level == level


class TestLoadConfigErrors:
    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            load_config(str(tmp_path / "missing.json"))

    def test_directory_path_raises_file_not_found(self, tmp_path):
        # os.path.isfile returns False for a directory
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path))

    def test_invalid_json_raises_value_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_config(str(path))

    def test_missing_broker_url_raises_value_error(self, tmp_path):
        path = write_config(tmp_path, {"zigbee2mqtt_base_topic": "z2m"})
        with pytest.raises(ValueError, match="Missing required configuration key.*broker_url"):
            load_config(path)

    def test_missing_base_topic_raises_value_error(self, tmp_path):
        path = write_config(tmp_path, {"broker_url": "tcp://localhost:1883"})
        with pytest.raises(ValueError, match="Missing required configuration key.*zigbee2mqtt_base_topic"):
            load_config(path)

    def test_invalid_command_debounce_sec_raises(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "broker_url": "tcp://localhost:1883",
                "zigbee2mqtt_base_topic": "z2m",
                "command_debounce_sec": "not-a-number",
            },
        )
        with pytest.raises(ValueError):
            load_config(path)


class TestValidateLogLevel:
    @pytest.mark.parametrize(
        "level",
        [BridgeLogLevel.DEBUG, BridgeLogLevel.INFO, BridgeLogLevel.WARNING, BridgeLogLevel.ERROR],
    )
    def test_valid_levels_returned_as_is(self, level):
        assert _validate_log_level(level) == level

    def test_unknown_level_falls_back_to_default(self, caplog):
        with caplog.at_level(logging.WARNING, logger="wb.mqtt_zigbee.config_loader"):
            result = _validate_log_level("verbose")
        assert result == BRIDGE_LOG_MIN_LEVEL_DEFAULT
        assert any("verbose" in rec.message for rec in caplog.records)

    def test_unknown_level_falls_back_via_load_config(self, tmp_path, caplog):
        path = write_config(
            tmp_path,
            {
                "broker_url": "tcp://localhost:1883",
                "zigbee2mqtt_base_topic": "z2m",
                "bridge_log_min_level": "trace",
            },
        )
        with caplog.at_level(logging.WARNING, logger="wb.mqtt_zigbee.config_loader"):
            cfg = load_config(path)
        assert cfg.bridge_log_min_level == BRIDGE_LOG_MIN_LEVEL_DEFAULT

    def test_empty_string_falls_back_to_default(self):
        assert _validate_log_level("") == BRIDGE_LOG_MIN_LEVEL_DEFAULT

    def test_case_sensitive(self):
        # uppercase variant is not valid (z2m uses lowercase)
        assert _validate_log_level("ERROR") == BRIDGE_LOG_MIN_LEVEL_DEFAULT


class TestDefaults:
    def test_default_constants_are_consistent(self):
        assert BRIDGE_DEVICE_ID_DEFAULT == "zigbee2mqtt"
        assert BRIDGE_DEVICE_NAME_DEFAULT == "Zigbee2MQTT"
        assert BRIDGE_LOG_MIN_LEVEL_DEFAULT == BridgeLogLevel.WARNING
        assert COMMAND_DEBOUNCE_SEC_DEFAULT == 5.0
