"""Unit tests for wb.mqtt_zigbee.z2m.client."""

import logging
import sys
from types import ModuleType
from unittest.mock import MagicMock

if "wb_common" not in sys.modules:
    wb_common = ModuleType("wb_common")
    wb_common_mqtt = ModuleType("wb_common.mqtt_client")
    wb_common_mqtt.MQTTClient = MagicMock  # type: ignore[attr-defined]
    sys.modules["wb_common"] = wb_common
    sys.modules["wb_common.mqtt_client"] = wb_common_mqtt

from wb.mqtt_zigbee.z2m.client import _parse_json_payload  # noqa: E402


def _make_message(payload: str) -> MagicMock:
    msg = MagicMock()
    msg.payload = payload.encode("utf-8")
    return msg


class TestParseJsonPayload:
    def test_valid_dict(self):
        assert _parse_json_payload(_make_message('{"a": 1}'), "test") == {"a": 1}

    def test_valid_list(self):
        assert _parse_json_payload(_make_message("[1, 2]"), "test") == [1, 2]

    def test_empty_payload_returns_none_silently(self, caplog):
        with caplog.at_level(logging.WARNING, logger="wb.mqtt_zigbee.z2m.client"):
            result = _parse_json_payload(_make_message(""), "test")
        assert result is None
        assert "Failed to parse" not in caplog.text

    def test_invalid_json_returns_none_with_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="wb.mqtt_zigbee.z2m.client"):
            result = _parse_json_payload(_make_message("not-json"), "my/topic")
        assert result is None
        assert "Failed to parse my/topic payload" in caplog.text
