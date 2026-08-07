"""Unit tests for wb.mqtt_zigbee.mqtt_utils."""

import pytest

from wb.mqtt_zigbee.mqtt_utils import (
    MAX_PAYLOAD_BYTES,
    decode_payload,
    is_safe_topic_name,
    payload_too_large,
)


class _Msg:
    """Minimal duck-typed stand-in for MQTTMessage (only .payload is used)."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload


class TestDecodePayload:
    def test_decode_valid_utf8(self):
        assert decode_payload(_Msg(b"hello")) == "hello"

    def test_decode_invalid_bytes_are_replaced_not_raised(self):
        # A non-UTF-8 payload must degrade to replacement chars, never raise
        # UnicodeDecodeError (which would kill the MQTT loop).
        result = decode_payload(_Msg(b"\xff\xfe\x00"))
        assert isinstance(result, str)
        assert "�" in result


class TestIsSafeTopicName:
    @pytest.mark.parametrize("name", ["sensor-1", "living room", "Дверь_в_ванной", "a.b"])
    def test_safe_topic_names_accepted(self, name):
        assert is_safe_topic_name(name) is True

    @pytest.mark.parametrize("name", ["", "#", "+", "a/b", "foo#", "a+b", "x/#"])
    def test_unsafe_topic_names_rejected(self, name):
        # Empty names and MQTT wildcard/separator chars must be rejected so a z2m
        # rename to e.g. "#" cannot inject a wildcard subscription.
        assert is_safe_topic_name(name) is False


class TestPayloadTooLarge:
    def test_boundary(self):
        # At the limit is allowed; one byte over is rejected (guards json.loads OOM).
        assert payload_too_large(_Msg(b"x" * MAX_PAYLOAD_BYTES), "t") is False
        assert payload_too_large(_Msg(b"x" * (MAX_PAYLOAD_BYTES + 1)), "t") is True
