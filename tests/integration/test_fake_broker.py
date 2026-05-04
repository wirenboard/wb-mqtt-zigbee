"""Self-tests for the FakeMqttBroker mock.

These tests pin the mock's behavior to the subset of MQTT spec that production
code relies on. If they fail, no other integration test can be trusted.
"""

import pytest

from .fakes.broker import FakeMqttBroker, MockMqttMessage, topic_matches
from .fakes.client import FakeMqttClient


# topic_matches
@pytest.mark.parametrize(
    ("topic_filter", "topic", "expected"),
    [
        # Exact match
        ("a/b/c", "a/b/c", True),
        ("a/b/c", "a/b/d", False),
        ("a/b", "a/b/c", False),
        ("a/b/c", "a/b", False),
        # Single-level wildcard `+`
        ("a/+/c", "a/b/c", True),
        ("a/+/c", "a/x/c", True),
        ("a/+/c", "a/b/d", False),
        ("a/+/c", "a/b/c/d", False),
        ("+/+", "a/b", True),
        ("+", "a", True),
        ("+", "a/b", False),  # `+` is exactly one level
        # Multi-level wildcard `#`
        ("a/#", "a", True),  # `#` matches zero levels too
        ("a/#", "a/b", True),
        ("a/#", "a/b/c/d", True),
        ("#", "anything", True),
        ("#", "a/b/c", True),
        ("a/#", "b/c", False),
        # Mixed
        ("a/+/#", "a/b/c/d", True),
        ("a/+/#", "a/b", True),
        ("a/+/#", "a", False),  # `+` requires one level
    ],
)
def test_topic_matches(topic_filter: str, topic: str, expected: bool) -> None:
    assert topic_matches(topic_filter, topic) is expected


# retained
def test_publish_without_retain_does_not_store() -> None:
    broker = FakeMqttBroker()
    client = FakeMqttClient(broker)
    client.publish("a/b", "hello", retain=False)
    assert not broker.retained


def test_publish_with_retain_stores_and_overwrites() -> None:
    broker = FakeMqttBroker()
    client = FakeMqttClient(broker)
    client.publish("a/b", "first", retain=True)
    client.publish("a/b", "second", retain=True)
    assert broker.retained["a/b"] == b"second"


def test_publish_retain_empty_payload_clears_topic() -> None:
    broker = FakeMqttBroker()
    client = FakeMqttClient(broker)
    client.publish("a/b", "value", retain=True)
    assert "a/b" in broker.retained

    client.publish("a/b", "", retain=True)
    assert "a/b" not in broker.retained


# new subscriptions receive retained
def test_subscriber_with_callback_replays_matching_retained_messages() -> None:
    """Production order: subscribe(topic) -> message_callback_add(topic, handler).
    Retained messages must reach the handler at the moment it is bound.
    """
    broker = FakeMqttBroker()
    publisher = FakeMqttClient(broker)
    publisher.publish("devices/foo/meta", "retained-foo", retain=True)
    publisher.publish("devices/bar/meta", "retained-bar", retain=True)
    publisher.publish("other/topic", "ignored", retain=True)

    received: list[MockMqttMessage] = []
    subscriber = FakeMqttClient(broker)
    subscriber.subscribe("devices/+/meta")
    subscriber.message_callback_add("devices/+/meta", lambda _c, _u, msg: received.append(msg))

    topics = sorted(msg.topic for msg in received)
    assert topics == ["devices/bar/meta", "devices/foo/meta"]
    assert all(msg.retain is True for msg in received)


# routing
def test_publish_routes_to_matching_subscribers_including_self() -> None:
    broker = FakeMqttBroker()
    client = FakeMqttClient(broker)
    received: list[str] = []
    client.subscribe("devices/+/meta")
    client.message_callback_add("devices/+/meta", lambda _c, _u, msg: received.append(msg.topic))

    client.publish("devices/foo/meta", "x", retain=True)
    client.publish("other/topic", "y", retain=True)

    assert received == ["devices/foo/meta"]


def test_inject_routes_but_does_not_log_publish() -> None:
    broker = FakeMqttBroker()
    client = FakeMqttClient(broker)
    received: list[str] = []
    client.subscribe("a/+")
    client.message_callback_add("a/+", lambda _c, _u, msg: received.append(msg.payload.decode()))

    broker.inject("a/b", "from-outside")
    assert received == ["from-outside"]
    assert not broker.publish_log  # inject() must not pollute the publish log


def test_unsubscribe_stops_routing() -> None:
    broker = FakeMqttBroker()
    client = FakeMqttClient(broker)
    received: list[str] = []
    client.subscribe("a/b")
    client.message_callback_add("a/b", lambda _c, _u, msg: received.append(msg.topic))

    broker.inject("a/b", "1")
    client.message_callback_remove("a/b")
    client.unsubscribe("a/b")
    broker.inject("a/b", "2")

    assert received == ["a/b"]


def test_multiple_matching_subscriptions_all_fire() -> None:
    broker = FakeMqttBroker()
    client = FakeMqttClient(broker)
    seen_specific: list[str] = []
    seen_wildcard: list[str] = []
    client.subscribe("a/b")
    client.message_callback_add("a/b", lambda _c, _u, msg: seen_specific.append(msg.topic))
    client.subscribe("a/+")
    client.message_callback_add("a/+", lambda _c, _u, msg: seen_wildcard.append(msg.topic))

    broker.inject("a/b", "x")

    assert seen_specific == ["a/b"]
    assert seen_wildcard == ["a/b"]


def test_publish_log_records_topic_payload_retain_qos() -> None:
    broker = FakeMqttBroker()
    client = FakeMqttClient(broker)
    client.publish("a/b", "v1", retain=True, qos=1)
    client.publish("c/d", b"binary", retain=False, qos=0)

    assert len(broker.publish_log) == 2
    first, second = broker.publish_log
    assert (first.topic, first.payload, first.retain, first.qos) == ("a/b", b"v1", True, 1)
    assert (second.topic, second.payload, second.retain, second.qos) == ("c/d", b"binary", False, 0)
