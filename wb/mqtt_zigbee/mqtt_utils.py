import functools
import logging
from typing import Any, Callable

from paho.mqtt.client import MQTTMessage

logger = logging.getLogger(__name__)

# Upper bound for a payload we will decode/parse. A real bridge/devices dump is ~30 KB
# for a handful of devices and grows slowly; this cap is far above any genuine payload
# and rejects pathological input before json.loads can allocate unboundedly (OOM).
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024

_MQTT_UNSAFE_CHARS = ("+", "#", "/")


def payload_too_large(message: MQTTMessage, topic_name: str) -> bool:
    """
    Return True (and log) if the raw payload exceeds MAX_PAYLOAD_BYTES

    Checked on the raw bytes before decoding/parsing, so an oversized retained message
    cannot force an unbounded allocation. len(message.payload) is O(1).
    """
    size = len(message.payload)
    if size > MAX_PAYLOAD_BYTES:
        logger.warning("Ignoring oversized %s payload (%d bytes)", topic_name, size)
        return True
    return False


def is_safe_topic_name(name: str) -> bool:
    """
    Check that a device name is safe to embed in an MQTT topic path

    Rejects non-string, empty, and names containing the MQTT wildcard/separator
    characters ('+', '#', '/'). An unchecked name (e.g. a zigbee2mqtt rename to "#")
    would turn a device topic into a wildcard subscription or inject an extra topic
    level; a non-string friendly_name (malformed payload) is likewise never a safe topic.
    """
    if not isinstance(name, str) or not name:
        return False
    return not any(ch in name for ch in _MQTT_UNSAFE_CHARS)


def log_callback_errors(callback: Callable[..., None]) -> Callable[..., None]:
    """
    Wrap an MQTT message callback so an exception is logged with a full traceback
    instead of escaping into paho's loop.

    A raising callback would otherwise either crash the daemon (paho re-raises out of
    loop_forever) or, with suppress_exceptions, be swallowed as a single line with no
    traceback or topic. Here we log the traceback plus the offending topic and carry on:
    the message itself is unrecoverable, correct data arrives with the next one.

    Wrap only message callbacks. Lifecycle callbacks (on_connect/on_disconnect) are left
    bare on purpose, so a genuine setup failure (e.g. subscribe()) still exits the process
    non-zero and lets systemd restart it, instead of leaving a live-but-idle daemon.
    """

    @functools.wraps(callback)
    def wrapper(*args: Any) -> None:
        try:
            callback(*args)
        except Exception:  # pylint: disable=broad-except
            # paho invokes message callbacks as (client, userdata, message); the message
            # (with its .topic) is the last positional arg.
            topic = getattr(args[-1], "topic", "<unknown>") if args else "<unknown>"
            logger.exception("Unhandled error in MQTT callback for topic '%s'", topic)

    return wrapper


def decode_payload(message: MQTTMessage) -> str:
    """
    Decode an MQTT payload to text, replacing invalid bytes

    Uses errors="replace" so a malformed (non-UTF-8) payload on any subscribed
    topic degrades to replacement characters instead of raising UnicodeDecodeError
    out of the message callback and taking down the MQTT loop (crash-loop on
    retained poison). Malformed JSON then fails gracefully in the callers' parsing.
    """
    return message.payload.decode("utf-8", errors="replace")
