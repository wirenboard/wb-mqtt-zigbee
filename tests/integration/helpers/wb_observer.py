"""
WbObserver — query helpers over `FakeMqttBroker.publish_log` and `retained`.

Reads only — never modifies broker state.
"""

import json
from typing import Optional

from ..fakes.broker import FakeMqttBroker, PublishedMessage


class WbObserver:
    """
    Convenience wrapper over the broker's publish log and retained map
    """

    def __init__(self, broker: FakeMqttBroker) -> None:
        self._broker = broker

    # publish_log queries
    def all_messages(self) -> list[PublishedMessage]:
        return list(self._broker.publish_log)

    def messages_on(self, topic: str) -> list[PublishedMessage]:
        return [msg for msg in self._broker.publish_log if msg.topic == topic]

    def messages_under(self, prefix: str) -> list[PublishedMessage]:
        return [msg for msg in self._broker.publish_log if msg.topic.startswith(prefix)]

    def topics(self) -> list[str]:
        return [msg.topic for msg in self._broker.publish_log]

    def last_on(self, topic: str) -> Optional[PublishedMessage]:
        msgs = self.messages_on(topic)
        return msgs[-1] if msgs else None

    def last_payload_on(self, topic: str) -> Optional[str]:
        msg = self.last_on(topic)
        return None if msg is None else msg.payload.decode("utf-8")

    def last_json_on(self, topic: str) -> Optional[object]:
        text = self.last_payload_on(topic)
        return None if text is None else json.loads(text)

    def has_publish_on(self, topic: str) -> bool:
        return any(msg.topic == topic for msg in self._broker.publish_log)

    # retained queries
    def retained(self, topic: str) -> Optional[str]:
        data = self._broker.retained.get(topic)
        return None if data is None else data.decode("utf-8")

    def retained_topics(self) -> list[str]:
        return list(self._broker.retained.keys())

    def retained_under(self, prefix: str) -> dict[str, str]:
        return {t: v.decode("utf-8") for t, v in self._broker.retained.items() if t.startswith(prefix)}


__all__ = ["WbObserver"]
