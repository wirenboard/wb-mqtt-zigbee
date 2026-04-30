"""In-process MQTT broker mock for integration tests.

Replaces a real MQTT broker with a deterministic, single-threaded fake. Tracks
retained messages, supports MQTT wildcards (`+`, `#`), and routes published
messages to all matching subscriptions, including the publisher's own
subscriptions (mirrors paho/mosquitto behavior).
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional


def topic_matches(topic_filter: str, topic: str) -> bool:
    """Return True if `topic` matches MQTT `topic_filter`.

    Rules (per MQTT 3.1.1 spec):
        - `+` matches exactly one topic level (no `/`).
        - `#` matches the rest of the topic, including zero levels;
          must be the last segment of the filter.
        - All other segments must match literally.
    """
    filter_parts = topic_filter.split("/")
    topic_parts = topic.split("/")
    for i, fp in enumerate(filter_parts):
        if fp == "#":
            return i == len(filter_parts) - 1
        if i >= len(topic_parts):
            return False
        if fp == "+":
            continue
        if fp != topic_parts[i]:
            return False
    return len(filter_parts) == len(topic_parts)


@dataclass(frozen=True)
class MockMqttMessage:
    """Minimal stand-in for paho.mqtt.client.MQTTMessage used by handlers."""

    topic: str
    payload: bytes
    retain: bool = False
    qos: int = 0


@dataclass(frozen=True)
class PublishedMessage:
    """Record of a single client.publish() call captured by the broker."""

    topic: str
    payload: bytes
    retain: bool
    qos: int
    client_id: str


@dataclass
class _Subscription:
    client_id: str
    topic_filter: str
    handler: Optional[Callable[[Any, Any, MockMqttMessage], None]]


def _to_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    if payload is None:
        return b""
    return str(payload).encode("utf-8")


class FakeMqttBroker:
    """In-process MQTT broker mock.

    Deterministic, no networking, no threads. All callbacks are invoked
    synchronously from publish()/inject().

    Used through FakeMqttClient: tests publish via `inject(...)` (acts "as
    zigbee2mqtt"), production code publishes via `client.publish(...)`. Both
    paths route messages to all matching subscriptions on this broker.

    Attributes:
        retained: map of topic → last retained payload. Empty payload deletes.
        subscriptions: list of active subscriptions across all clients.
        publish_log: ordered log of all client.publish() calls (NOT inject).
    """

    def __init__(self) -> None:
        self.retained: dict[str, bytes] = {}
        self.subscriptions: list[_Subscription] = []
        self.publish_log: list[PublishedMessage] = []

    # -- Subscription management ----------------------------------------------

    def subscribe(self, client_id: str, topic_filter: str) -> None:
        """Add a subscription for client_id.

        Retained messages are replayed when a callback is bound (see
        `set_callback`), not here, because production code follows the
        order `subscribe(...)` → `message_callback_add(...)`.
        """
        self.subscriptions.append(_Subscription(client_id, topic_filter, handler=None))

    def unsubscribe(self, client_id: str, topic_filter: str) -> None:
        """Remove the most recent subscription for (client_id, topic_filter)."""
        for i in range(len(self.subscriptions) - 1, -1, -1):
            sub = self.subscriptions[i]
            if sub.client_id == client_id and sub.topic_filter == topic_filter:
                del self.subscriptions[i]
                return

    def set_callback(
        self,
        client_id: str,
        topic_filter: str,
        handler: Callable[[Any, Any, MockMqttMessage], None],
    ) -> None:
        """Attach `handler` to the most recent subscription for (client_id, topic_filter).

        Replays any retained messages matching `topic_filter` to the new
        handler. This matches the practical effect of paho's subscribe + a
        per-topic callback registration.
        """
        for sub in reversed(self.subscriptions):
            if sub.client_id == client_id and sub.topic_filter == topic_filter:
                sub.handler = handler
                for topic, payload in list(self.retained.items()):
                    if topic_matches(topic_filter, topic):
                        handler(
                            None,
                            None,
                            MockMqttMessage(topic=topic, payload=payload, retain=True),
                        )
                return

    def remove_callback(self, client_id: str, topic_filter: str) -> None:
        """Detach handler from the most recent subscription for (client_id, topic_filter)."""
        for sub in reversed(self.subscriptions):
            if sub.client_id == client_id and sub.topic_filter == topic_filter:
                sub.handler = None
                return

    # -- Publishing -----------------------------------------------------------

    def publish_from_client(
        self,
        client_id: str,
        topic: str,
        payload: Any,
        retain: bool = False,
        qos: int = 0,
    ) -> None:
        """Record a client.publish() call and route the message."""
        data = _to_bytes(payload)
        self.publish_log.append(
            PublishedMessage(topic=topic, payload=data, retain=retain, qos=qos, client_id=client_id)
        )
        self._apply_retain(topic, data, retain)
        self._route(MockMqttMessage(topic=topic, payload=data, retain=retain, qos=qos))

    def inject(
        self,
        topic: str,
        payload: Any,
        retain: bool = False,
        qos: int = 0,
    ) -> None:
        """Inject a message "from outside" (no record in publish_log)."""
        data = _to_bytes(payload)
        self._apply_retain(topic, data, retain)
        self._route(MockMqttMessage(topic=topic, payload=data, retain=retain, qos=qos))

    # -- Internals ------------------------------------------------------------

    def _apply_retain(self, topic: str, data: bytes, retain: bool) -> None:
        if not retain:
            return
        if data == b"":
            self.retained.pop(topic, None)
        else:
            self.retained[topic] = data

    def _route(self, message: MockMqttMessage) -> None:
        for sub in list(self.subscriptions):
            if sub.handler is None:
                continue
            if topic_matches(sub.topic_filter, message.topic):
                sub.handler(None, None, message)


__all__ = [
    "FakeMqttBroker",
    "MockMqttMessage",
    "PublishedMessage",
    "topic_matches",
]
