"""Unit tests for wb.mqtt_zigbee.main."""

from types import SimpleNamespace

import pytest

import wb.mqtt_zigbee.main as main_module


def test_no_arguments_loads_packaged_config(monkeypatch):
    config = SimpleNamespace(broker_url="unix:///var/run/mosquitto/mosquitto.sock")
    loaded_paths = []

    def fake_load_config(path):
        loaded_paths.append(path)
        return config

    class FakeService:  # pylint: disable=too-few-public-methods
        def __init__(self, loaded_config):
            assert loaded_config is config

        def run(self):
            return 7

    monkeypatch.setattr(main_module, "load_config", fake_load_config)
    monkeypatch.setattr(main_module, "WbZigbee2Mqtt", FakeService)

    assert main_module.main(["wb-mqtt-zigbee"]) == 7
    assert loaded_paths == [main_module.CONFIG_FILEPATH]


def test_config_option_is_rejected():
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["wb-mqtt-zigbee", "-c", "/tmp/config.json"])

    assert exc_info.value.code == 2
