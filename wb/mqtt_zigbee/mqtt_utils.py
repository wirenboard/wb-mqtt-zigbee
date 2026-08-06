from paho.mqtt.client import MQTTMessage

_MQTT_UNSAFE_CHARS = ("+", "#", "/")


def is_safe_topic_name(name: str) -> bool:
    """Check that a device name is safe to embed in an MQTT topic path.

    Rejects empty names and names containing the MQTT wildcard/separator characters
    ('+', '#', '/'). An unchecked name (e.g. a zigbee2mqtt rename to "#") would turn a
    device topic into a wildcard subscription or inject an extra topic level.
    """
    if not name:
        return False
    return not any(ch in name for ch in _MQTT_UNSAFE_CHARS)


def decode_payload(message: MQTTMessage) -> str:
    """Decode an MQTT payload to text, replacing invalid bytes.

    Uses errors="replace" so a malformed (non-UTF-8) payload on any subscribed
    topic degrades to replacement characters instead of raising UnicodeDecodeError
    out of the message callback and taking down the MQTT loop (crash-loop on
    retained poison). Malformed JSON then fails gracefully in the callers' parsing.
    """
    return message.payload.decode("utf-8", errors="replace")
