"""Unit tests for wb.mqtt_zigbee.mqtt_utils."""

from wb.mqtt_zigbee.mqtt_utils import decode_payload


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
