"""Unit tests for wb.mqtt_zigbee.mqtt_utils."""

import pytest

from wb.mqtt_zigbee.mqtt_utils import decode_payload, is_safe_topic_name


class _Msg:
    """Minimal duck-typed stand-in for MQTTMessage (only .payload is used)."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload


def test_decode_valid_utf8():
    assert decode_payload(_Msg(b"hello")) == "hello"


def test_decode_invalid_bytes_are_replaced_not_raised():
    # A non-UTF-8 payload must degrade to replacement chars, never raise
    # UnicodeDecodeError (which would kill the MQTT loop).
    result = decode_payload(_Msg(b"\xff\xfe\x00"))
    assert isinstance(result, str)
    assert "�" in result


@pytest.mark.parametrize("name", ["sensor-1", "living room", "Дверь_в_ванной", "a.b"])
def test_safe_topic_names_accepted(name):
    assert is_safe_topic_name(name) is True


@pytest.mark.parametrize("name", ["", "#", "+", "a/b", "foo#", "a+b", "x/#"])
def test_unsafe_topic_names_rejected(name):
    # Empty names and MQTT wildcard/separator chars must be rejected so a z2m
    # rename to e.g. "#" cannot inject a wildcard subscription.
    assert is_safe_topic_name(name) is False
