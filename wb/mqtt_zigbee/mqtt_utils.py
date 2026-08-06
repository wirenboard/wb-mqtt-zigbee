from paho.mqtt.client import MQTTMessage


def decode_payload(message: MQTTMessage) -> str:
    """Decode an MQTT payload to text, replacing invalid bytes.

    Uses errors="replace" so a malformed (non-UTF-8) payload on any subscribed
    topic degrades to replacement characters instead of raising UnicodeDecodeError
    out of the message callback and taking down the MQTT loop (crash-loop on
    retained poison). Malformed JSON then fails gracefully in the callers' parsing.
    """
    return message.payload.decode("utf-8", errors="replace")
