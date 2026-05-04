"""FakeMqttClient — drop-in replacement for `wb_common.mqtt_client.MQTTClient`.

Implements only the subset of API used by `wb.mqtt_zigbee` production code:
  - subscribe / unsubscribe
  - publish(topic, payload, retain=False, qos=0)
  - message_callback_add / message_callback_remove
  - on_connect / on_disconnect attribute callbacks
  - start / stop / loop_forever — no-op (network loop is irrelevant in tests)

All operations are routed to a shared `FakeMqttBroker`. Tests can simulate
network events with `connect()` / `disconnect()` helpers (not part of the
production API).
"""

import itertools
from typing import Any, Callable, Optional

from .broker import FakeMqttBroker, MockMqttMessage

_id_counter = itertools.count(1)


class FakeMqttClient:
    """In-process MQTT client backed by FakeMqttBroker."""

    def __init__(self, broker: FakeMqttBroker, client_id: Optional[str] = None) -> None:
        self._broker = broker
        self._client_id = client_id or f"fake-client-{next(_id_counter)}"
        # Per-client tracking lets tests inspect what this particular client
        # subscribed to without scanning the global broker state.
        self._subscriptions: list[str] = []
        self._unsubscriptions: list[str] = []
        self.on_connect: Optional[Callable[[Any, Any, dict, int], None]] = None
        self.on_disconnect: Optional[Callable[[Any, Any, dict], None]] = None
        self._started = False
        self._stopped = False

    # Production API
    def subscribe(self, topic: str) -> None:
        self._subscriptions.append(topic)
        self._broker.subscribe(self._client_id, topic)

    def unsubscribe(self, topic: str) -> None:
        self._unsubscriptions.append(topic)
        self._broker.unsubscribe(self._client_id, topic)

    def publish(self, topic: str, payload: Any = "", retain: bool = False, qos: int = 0) -> None:
        self._broker.publish_from_client(self._client_id, topic, payload, retain=retain, qos=qos)

    def message_callback_add(
        self,
        topic_filter: str,
        handler: Callable[[Any, Any, MockMqttMessage], None],
    ) -> None:
        self._broker.set_callback(self._client_id, topic_filter, handler)

    def message_callback_remove(self, topic_filter: str) -> None:
        self._broker.remove_callback(self._client_id, topic_filter)

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._stopped = True

    def loop_forever(self) -> None:  # pragma: no cover - never invoked in tests
        return None

    # Test helpers
    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def subscriptions(self) -> list[str]:
        """Topics this client has subscribed to (in call order, with duplicates)."""
        return list(self._subscriptions)

    @property
    def unsubscriptions(self) -> list[str]:
        return list(self._unsubscriptions)

    def connect(self, rc: int = 0) -> None:
        """Simulate a successful broker connect — invokes on_connect callback."""
        if self.on_connect is not None:
            self.on_connect(self, None, {}, rc)

    def disconnect(self) -> None:
        """Simulate a broker disconnect — invokes on_disconnect callback."""
        if self.on_disconnect is not None:
            self.on_disconnect(self, None, {})


__all__ = ["FakeMqttClient"]
