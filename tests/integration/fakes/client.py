"""
FakeMqttClient — drop-in replacement for `wb_common.mqtt_client.MQTTClient`, the threaded client.

Implements only the subset of API used by `wb.mqtt_zigbee` production code:
  - subscribe / unsubscribe, message_callback_add / message_callback_remove
  - publish(topic, payload, retain=False, qos=0) → FakeMessageInfo, shaped like paho's MQTTMessageInfo
  - on_connect / on_disconnect attribute callbacks
  - start / wait_for_connection / is_connected / disconnect / stop

Nothing runs concurrently: the test plays paho's network thread. A CONNACK is `connect(rc=...)`,
a dropped connection is `lose_connection()`, and the broker's acknowledgements arrive in
`wait_for_publish()` — unless the test holds them back with `broker_acknowledges = False` — and in
`stop()`, which drains the outgoing queue the way paho's thread does before it exits. The lifecycle
calls of the production code are recorded in `calls`, in order.

All operations are routed to a shared `FakeMqttBroker`.
"""

import itertools
import threading
from typing import Any, Callable, Optional

from .broker import FakeMqttBroker, MockMqttMessage

_id_counter = itertools.count(1)


class FakeMessageInfo:
    """
    What publish() returns, with the part of paho's MQTTMessageInfo the production code uses:
    rc, mid, wait_for_publish() and is_published(). The client marks it published when the
    broker's acknowledgement arrives.
    """

    def __init__(self, mid: int, client: "FakeMqttClient") -> None:
        self.mid = mid
        self.rc = 0
        self.waited_with_timeout: Optional[float] = None
        self._published = False
        self._client = client

    def wait_for_publish(self, timeout: Optional[float] = None) -> None:
        """
        Where the main thread yields to paho's network thread: the acknowledgements up to this
        message arrive now, unless the test told the broker to stay silent (a timeout then)
        """
        self.waited_with_timeout = timeout
        if self._client.broker_acknowledges:
            self._client.acknowledge_through(self)

    def is_published(self) -> bool:
        return self._published

    def mark_published(self) -> None:
        self._published = True


class FakeMqttClient:
    """
    In-process MQTT client backed by FakeMqttBroker
    """

    def __init__(self, broker: FakeMqttBroker, client_id: Optional[str] = None) -> None:
        self._broker = broker
        self._client_id = client_id or f"fake-client-{next(_id_counter)}"
        # Per-client tracking lets tests inspect what this particular client
        # subscribed to without scanning the global broker state.
        self._subscriptions: list[str] = []
        self._unsubscriptions: list[str] = []
        self.on_connect: Optional[Callable[[Any, Any, dict, int], None]] = None
        self.on_disconnect: Optional[Callable[[Any, Any, int], None]] = None
        self._mids = itertools.count(1)
        self._unacknowledged: list[FakeMessageInfo] = []  # publishes the broker has not acknowledged
        self._connected = False
        self.will: Optional[tuple[str, Any, int, bool]] = None
        # What a test reads back
        self.calls: list[str] = []  # start / disconnect / stop, in call order
        self.retry_first_connection: Optional[bool] = None
        self.last_publish: Optional[FakeMessageInfo] = None
        self.stopped_with_unacknowledged = False  # stop() had to drain publishes nobody waited for
        self.broker_acknowledges = True  # False: no acknowledgement ever comes, waits time out

    # Production API
    def will_set(self, topic: str, payload: Any = "", qos: int = 0, retain: bool = False) -> None:
        self.will = (topic, payload, qos, retain)

    def enable_logger(self, logger: Any = None) -> None:
        pass

    def subscribe(self, topic: str) -> None:
        self._subscriptions.append(topic)
        self._broker.subscribe(self._client_id, topic)

    def unsubscribe(self, topic: str) -> None:
        self._unsubscriptions.append(topic)
        self._broker.unsubscribe(self._client_id, topic)

    def publish(self, topic: str, payload: Any = "", retain: bool = False, qos: int = 0) -> FakeMessageInfo:
        self._broker.publish_from_client(self._client_id, topic, payload, retain=retain, qos=qos)
        self.last_publish = FakeMessageInfo(next(self._mids), self)
        self._unacknowledged.append(self.last_publish)
        return self.last_publish

    def message_callback_add(
        self,
        topic_filter: str,
        handler: Callable[[Any, Any, MockMqttMessage], None],
    ) -> None:
        self._broker.set_callback(self._client_id, topic_filter, handler)

    def message_callback_remove(self, topic_filter: str) -> None:
        self._broker.remove_callback(self._client_id, topic_filter)

    def start(self, retry_first_connection: bool = False) -> None:
        """
        Returns at once, as the threaded client does: the CONNACK comes later, from connect()
        """
        self.calls.append("start")
        self.retry_first_connection = retry_first_connection

    def wait_for_connection(self, _stop_requested: Optional[threading.Event] = None) -> bool:
        """
        Nothing happens meanwhile; a test that wants paho's thread to deliver something during the
        wait (a CONNACK, z2m traffic, a signal) gives this method a side effect
        """
        return self._connected

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        """
        Close the connection cleanly: paho reports it to on_disconnect with rc 0
        """
        self.calls.append("disconnect")
        self._close(rc=0)

    def stop(self) -> None:
        """
        wb-common's stop(): paho's network thread exits only once the outgoing queue is empty, so
        every pending publish is acknowledged here — stopped_with_unacknowledged tells a test whether
        the production code left that to the drain instead of waiting itself — then the DISCONNECT.
        """
        self.calls.append("stop")
        if self._unacknowledged:
            self.stopped_with_unacknowledged = True
            self.acknowledge_through(self._unacknowledged[-1])
        self._close(rc=0)

    # Test helpers
    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def subscriptions(self) -> list[str]:
        """
        Topics this client has subscribed to (in call order, with duplicates)
        """
        return list(self._subscriptions)

    @property
    def unsubscriptions(self) -> list[str]:
        """
        Topics this client has unsubscribed from (in call order, with duplicates)
        """
        return list(self._unsubscriptions)

    @property
    def stopped(self) -> bool:
        return "stop" in self.calls

    def connect(self, rc: int = 0) -> None:
        """
        Simulate a broker CONNACK — invokes on_connect callback; connected only on rc == 0
        """
        self._connected = rc == 0
        if self.on_connect is not None:
            self.on_connect(self, None, {}, rc)

    def lose_connection(self) -> None:
        """
        The broker went away: on_disconnect with rc 7 (MQTT_ERR_CONN_LOST)
        """
        self._close(rc=7)

    def acknowledge_through(self, info: FakeMessageInfo) -> None:
        """
        The broker's acknowledgements up to and including `info` arrive, in publish order
        """
        while info in self._unacknowledged:
            self._unacknowledged.pop(0).mark_published()

    def _close(self, rc: int) -> None:
        if not self._connected:
            return  # paho reports nothing for a client that has no connection to close
        self._connected = False
        if self.on_disconnect is not None:
            self.on_disconnect(self, None, rc)


__all__ = ["FakeMessageInfo", "FakeMqttClient"]
