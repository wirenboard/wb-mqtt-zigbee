import logging

from paho.mqtt.client import MQTTMessage

logger = logging.getLogger(__name__)

# Upper bound for a payload we will decode/parse. A real bridge/devices dump is ~30 KB
# for a handful of devices and grows slowly; this cap is far above any genuine payload
# and rejects pathological input before json.loads can allocate unboundedly (OOM).
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024

_MQTT_UNSAFE_CHARS = ("+", "#", "/")


def payload_too_large(message: MQTTMessage, topic_name: str) -> bool:
    """Return True (and log) if the raw payload exceeds MAX_PAYLOAD_BYTES.

    Checked on the raw bytes before decoding/parsing, so an oversized retained message
    cannot force an unbounded allocation. len(message.payload) is O(1).
    """
    size = len(message.payload)
    if size > MAX_PAYLOAD_BYTES:
        logger.warning("Ignoring oversized %s payload (%d bytes)", topic_name, size)
        return True
    return False


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
