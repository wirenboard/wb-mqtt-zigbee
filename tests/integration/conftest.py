"""Integration test fixtures: MockMQTTClient and Bridge setup."""

import json
from dataclasses import dataclass, field

import pytest

from wb.zigbee2mqtt.bridge import Bridge




# ---------------------------------------------------------------------------
# Mock MQTT client
# ---------------------------------------------------------------------------

@dataclass
class FakeMessage:
    """Minimal MQTT message compatible with paho-mqtt interface."""
    payload: bytes


class MockMQTTClient:
    """In-process mock of wb_common.MQTTClient.

    Tracks all publish/subscribe calls and allows injecting messages
    to trigger registered callbacks synchronously.
    """

    def __init__(self):
        self.retained: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []  # all (topic, payload) in order
        self.subscriptions: set[str] = set()
        self.callbacks: dict[str, object] = {}

    def publish(self, topic: str, payload: str, retain: bool = False, qos: int = 0) -> None:
        self.published.append((topic, payload))
        if retain:
            self.retained[topic] = payload

    def subscribe(self, topic: str) -> None:
        self.subscriptions.add(topic)

    def unsubscribe(self, topic: str) -> None:
        self.subscriptions.discard(topic)

    def message_callback_add(self, topic: str, callback: object) -> None:
        self.callbacks[topic] = callback

    def message_callback_remove(self, topic: str) -> None:
        self.callbacks.pop(topic, None)

    def inject_message(self, topic: str, payload: str) -> None:
        """Simulate an incoming MQTT message by calling the registered callback."""
        cb = self.callbacks.get(topic)
        if cb is None:
            raise KeyError(f"No callback registered for topic '{topic}'. "
                           f"Registered: {sorted(self.callbacks.keys())}")
        cb(None, None, FakeMessage(payload=payload.encode("utf-8")))

    def find_published(self, topic: str) -> list[str]:
        """Return all payloads published to a given topic (any retain)."""
        return [p for t, p in self.published if t == topic]

    def get_control_value(self, device_id: str, control_id: str) -> str:
        return self.retained.get(f"/devices/{device_id}/controls/{control_id}", "")

    def get_control_meta(self, device_id: str, control_id: str) -> dict:
        raw = self.retained.get(f"/devices/{device_id}/controls/{control_id}/meta", "{}")
        return json.loads(raw)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mqtt():
    return MockMQTTClient()


@pytest.fixture
def bridge(mock_mqtt):
    b = Bridge(
        mqtt_client=mock_mqtt,
        base_topic="zigbee2mqtt",
        device_id="zigbee2mqtt",
        device_name="Zigbee2MQTT",
        bridge_log_min_level="warning",
    )
    b.subscribe()
    return b


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

def make_bridge_devices_payload(devices: list[dict]) -> str:
    """Build a bridge/devices JSON string from a list of device dicts."""
    return json.dumps(devices)


RELAY_DEVICE = {
    "ieee_address": "0x00158d0001234567",
    "friendly_name": "test_relay",
    "type": "Router",
    "definition": {
        "model": "MCCGQ11LM",
        "vendor": "Xiaomi",
        "description": "Test relay",
        "exposes": [
            {
                "type": "switch",
                "features": [
                    {
                        "type": "binary",
                        "name": "state",
                        "property": "state",
                        "access": 7,
                        "value_on": "ON",
                        "value_off": "OFF",
                    }
                ],
            }
        ],
    },
}

TEMP_SENSOR_DEVICE = {
    "ieee_address": "0xa4c1381b020a8ced",
    "friendly_name": "temp_sensor",
    "type": "EndDevice",
    "definition": {
        "model": "WSDCGQ11LM",
        "vendor": "Xiaomi",
        "description": "Temperature sensor",
        "exposes": [
            {"type": "numeric", "name": "temperature", "property": "temperature", "access": 1, "unit": "°C"},
            {"type": "numeric", "name": "humidity", "property": "humidity", "access": 1, "unit": "%"},
        ],
    },
}

COLOR_LAMP_DEVICE = {
    "ieee_address": "0x001788010badf00d",
    "friendly_name": "color_lamp",
    "type": "Router",
    "definition": {
        "model": "LCT015",
        "vendor": "Philips",
        "description": "Color lamp",
        "exposes": [
            {
                "type": "light",
                "features": [
                    {"type": "binary", "name": "state", "property": "state", "access": 7, "value_on": "ON", "value_off": "OFF"},
                    {"type": "numeric", "name": "brightness", "property": "brightness", "access": 7, "value_min": 0, "value_max": 254},
                    {
                        "type": "composite",
                        "name": "color_hs",
                        "property": "color",
                        "features": [
                            {"type": "numeric", "name": "hue", "property": "", "access": 3},
                            {"type": "numeric", "name": "saturation", "property": "", "access": 3},
                        ],
                    },
                ],
            }
        ],
    },
}
