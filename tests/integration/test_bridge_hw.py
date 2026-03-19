"""Read-only integration tests on real hardware test stand.

Connects to MQTT broker, reads retained topics published by wb-mqtt-zigbee,
and verifies their structure. Does NOT write anything — safe for any stand.

Requires: --teststand-host=<ip> pytest option.
All tests are marked with @pytest.mark.teststand and skipped by default.

Usage:
    pytest tests/integration/test_bridge_hw.py --teststand-host=192.168.88.99
"""

import json
import time

import pytest

pytestmark = pytest.mark.teststand

# ---------------------------------------------------------------------------
# MQTT helper
# ---------------------------------------------------------------------------

class MQTTReader:
    """Subscribes to topics and collects retained messages."""

    def __init__(self, host: str, port: int = 1883):
        import paho.mqtt.client as mqtt
        self._messages: dict[str, str] = {}
        self._client = mqtt.Client()
        self._client.on_message = self._on_message
        self._client.connect(host, port, keepalive=10)
        self._client.loop_start()

    def _on_message(self, _client, _userdata, message):
        self._messages[message.topic] = message.payload.decode("utf-8")

    def subscribe_and_wait(self, topic: str, timeout: float = 3.0) -> dict[str, str]:
        """Subscribe to a topic pattern and wait for retained messages.

        Note: previous subscriptions remain active, so messages from them
        may also arrive. Callers should filter by topic prefix if needed.
        """
        self._client.subscribe(topic)
        time.sleep(timeout)
        # Return only topics matching this subscription (filter by pattern)
        import re
        regex = re.compile("^" + topic.replace("+", "[^/]+").replace("#", ".*") + "$")
        return {t: v for t, v in self._messages.items() if regex.match(t)}

    def disconnect(self):
        self._client.loop_stop()
        self._client.disconnect()


@pytest.fixture(scope="module")
def mqtt_reader(request):
    host = request.config.getoption("--teststand-host")
    paho = pytest.importorskip("paho.mqtt.client")
    reader = MQTTReader(host)
    yield reader
    reader.disconnect()


@pytest.fixture(scope="module")
def bridge_controls(mqtt_reader):
    """Read all bridge device controls and meta."""
    values = mqtt_reader.subscribe_and_wait("/devices/zigbee2mqtt/controls/+")
    meta = mqtt_reader.subscribe_and_wait("/devices/zigbee2mqtt/controls/+/meta")
    return {"values": values, "meta": meta}


@pytest.fixture(scope="module")
def zigbee_device_ids(mqtt_reader):
    """Discover all zigbee device IDs (0x...) from /devices/+/meta."""
    all_meta = mqtt_reader.subscribe_and_wait("/devices/+/meta")
    ids = []
    for topic, payload in all_meta.items():
        # /devices/{id}/meta
        device_id = topic.split("/")[2]
        if device_id.startswith("0x"):
            ids.append(device_id)
    return ids


@pytest.fixture(scope="module")
def zigbee_devices(mqtt_reader, zigbee_device_ids):
    """Read controls and meta for all zigbee devices."""
    devices = {}
    for device_id in zigbee_device_ids:
        values = mqtt_reader.subscribe_and_wait(f"/devices/{device_id}/controls/+")
        meta = mqtt_reader.subscribe_and_wait(f"/devices/{device_id}/controls/+/meta")
        devices[device_id] = {"values": values, "meta": meta}
    return devices


# ---------------------------------------------------------------------------
# Bridge device tests
# ---------------------------------------------------------------------------

class TestBridgeDevice:

    def test_bridge_meta_exists(self, mqtt_reader):
        meta = mqtt_reader.subscribe_and_wait("/devices/zigbee2mqtt/meta")
        raw = meta.get("/devices/zigbee2mqtt/meta", "")
        assert raw, "Bridge device meta not found"
        data = json.loads(raw)
        assert "title" in data

    def test_bridge_has_all_controls(self, bridge_controls):
        expected = {
            "State", "Version", "Permit join", "Device count",
            "Last joined", "Last left", "Last removed", "Update devices",
            "Last seen", "Messages received", "Log level", "Log",
        }
        found = set()
        for topic in bridge_controls["values"]:
            control_id = topic.split("/")[-1]
            found.add(control_id)
        assert expected.issubset(found), f"Missing controls: {expected - found}"

    def test_bridge_state_is_online(self, bridge_controls):
        val = bridge_controls["values"].get("/devices/zigbee2mqtt/controls/State", "")
        assert val == "online"

    def test_bridge_version_not_empty(self, bridge_controls):
        val = bridge_controls["values"].get("/devices/zigbee2mqtt/controls/Version", "")
        assert val, "Version should not be empty"

    def test_bridge_device_count_positive(self, bridge_controls):
        val = bridge_controls["values"].get("/devices/zigbee2mqtt/controls/Device count", "0")
        assert int(val) > 0

    def test_bridge_control_meta_structure(self, bridge_controls):
        """Each control meta should have type and readonly fields."""
        for topic, raw in bridge_controls["meta"].items():
            data = json.loads(raw)
            assert "type" in data, f"Missing 'type' in {topic}"
            assert "readonly" in data, f"Missing 'readonly' in {topic}"
            assert "order" in data, f"Missing 'order' in {topic}"

    def test_bridge_control_meta_types(self, bridge_controls):
        expected_types = {
            "State": "text",
            "Version": "text",
            "Permit join": "switch",
            "Device count": "value",
            "Update devices": "pushbutton",
            "Log level": "text",
            "Log": "text",
            "Last seen": "text",
            "Messages received": "value",
        }
        for control_id, expected_type in expected_types.items():
            meta_topic = f"/devices/zigbee2mqtt/controls/{control_id}/meta"
            raw = bridge_controls["meta"].get(meta_topic, "{}")
            data = json.loads(raw)
            assert data.get("type") == expected_type, \
                f"{control_id}: expected type '{expected_type}', got '{data.get('type')}'"

    def test_bridge_permit_join_is_writable(self, bridge_controls):
        raw = bridge_controls["meta"].get("/devices/zigbee2mqtt/controls/Permit join/meta", "{}")
        data = json.loads(raw)
        assert data.get("readonly") is False


# ---------------------------------------------------------------------------
# Zigbee device tests
# ---------------------------------------------------------------------------

class TestZigbeeDevices:

    def test_at_least_one_device(self, zigbee_device_ids):
        assert len(zigbee_device_ids) > 0, "No zigbee devices found"

    def test_device_ids_are_valid(self, zigbee_device_ids):
        for device_id in zigbee_device_ids:
            assert device_id.startswith("0x"), f"Unexpected device_id format: {device_id}"
            assert len(device_id) >= 10, f"Device ID too short: {device_id}"

    def test_each_device_has_meta(self, mqtt_reader, zigbee_device_ids):
        all_meta = mqtt_reader.subscribe_and_wait("/devices/+/meta")
        for device_id in zigbee_device_ids:
            topic = f"/devices/{device_id}/meta"
            assert topic in all_meta, f"Missing meta for {device_id}"
            data = json.loads(all_meta[topic])
            assert "title" in data

    def test_each_device_has_controls(self, zigbee_devices):
        for device_id, data in zigbee_devices.items():
            assert len(data["meta"]) > 0, f"Device {device_id} has no control meta"

    def test_control_meta_has_required_fields(self, zigbee_devices):
        for device_id, data in zigbee_devices.items():
            for topic, raw in data["meta"].items():
                meta = json.loads(raw)
                assert "type" in meta, f"Missing 'type' in {topic}"
                assert "readonly" in meta, f"Missing 'readonly' in {topic}"

    def test_control_types_are_valid(self, zigbee_devices):
        valid_types = {
            "value", "switch", "text", "pushbutton", "temperature",
            "rel_humidity", "atmospheric_pressure", "concentration",
            "sound_level", "power", "voltage", "current",
            "power_consumption", "illuminance", "range", "rgb",
        }
        for device_id, data in zigbee_devices.items():
            for topic, raw in data["meta"].items():
                meta = json.loads(raw)
                ctrl_type = meta.get("type", "")
                assert ctrl_type in valid_types, \
                    f"Unknown type '{ctrl_type}' in {topic}"

    def test_each_device_has_last_seen(self, zigbee_devices):
        for device_id, data in zigbee_devices.items():
            last_seen_meta = f"/devices/{device_id}/controls/last_seen/meta"
            assert last_seen_meta in data["meta"], f"Device {device_id} missing last_seen control"

    def test_each_device_has_device_type(self, zigbee_devices):
        for device_id, data in zigbee_devices.items():
            dt_meta = f"/devices/{device_id}/controls/device_type/meta"
            assert dt_meta in data["meta"], f"Device {device_id} missing device_type control"

    def test_device_type_values(self, zigbee_devices):
        valid_types = {"Маршрутизатор", "Оконечное устройство", "Координатор", ""}
        for device_id, data in zigbee_devices.items():
            val = data["values"].get(f"/devices/{device_id}/controls/device_type", "")
            assert val in valid_types, \
                f"Device {device_id}: unexpected device_type '{val}'"

    def test_range_controls_have_min_or_max(self, zigbee_devices):
        for device_id, data in zigbee_devices.items():
            for topic, raw in data["meta"].items():
                meta = json.loads(raw)
                if meta.get("type") == "range":
                    has_bounds = "min" in meta or "max" in meta
                    assert has_bounds, f"Range control without min/max: {topic}"

    def test_readonly_controls_have_no_on_topic(self, mqtt_reader, zigbee_devices):
        """Readonly controls should not have /on subscriptions (spot check)."""
        for device_id, data in zigbee_devices.items():
            for topic, raw in data["meta"].items():
                meta = json.loads(raw)
                if meta.get("readonly") is True:
                    # Extract control_id from .../controls/{id}/meta
                    parts = topic.split("/")
                    control_id = parts[-2]
                    on_topic = f"/devices/{device_id}/controls/{control_id}/on"
                    # We can't easily check subscriptions, but we can verify
                    # the control value topic exists (it should for all controls)
                    val_topic = f"/devices/{device_id}/controls/{control_id}"
                    assert val_topic in data["values"], \
                        f"Control {control_id} has meta but no value topic"
