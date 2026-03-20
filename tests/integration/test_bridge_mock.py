"""Integration tests: full data cycle through Bridge with mocked MQTT client."""

import json

import pytest

# conftest.py is auto-loaded by pytest; import data constants directly
from conftest import (
    COLOR_LAMP_DEVICE,
    MockMQTTClient,
    RELAY_DEVICE,
    TEMP_SENSOR_DEVICE,
    make_bridge_devices_payload,
)

from wb.zigbee2mqtt.bridge import Bridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def register_device(mock_mqtt, device_dict):
    """Inject bridge/devices with a single device to trigger registration."""
    payload = make_bridge_devices_payload([device_dict])
    mock_mqtt.inject_message("zigbee2mqtt/bridge/devices", payload)


# ---------------------------------------------------------------------------
# 3.1 Reading device state (z2m → WB)
# ---------------------------------------------------------------------------

class TestReadState:

    def test_relay_state_on(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        mock_mqtt.inject_message("zigbee2mqtt/test_relay", json.dumps({"state": "ON"}))
        assert mock_mqtt.get_control_value("0x00158d0001234567", "state") == "1"

    def test_relay_state_off(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        mock_mqtt.inject_message("zigbee2mqtt/test_relay", json.dumps({"state": "OFF"}))
        assert mock_mqtt.get_control_value("0x00158d0001234567", "state") == "0"

    def test_temp_sensor_values(self, bridge, mock_mqtt):
        register_device(mock_mqtt, TEMP_SENSOR_DEVICE)
        mock_mqtt.inject_message(
            "zigbee2mqtt/temp_sensor",
            json.dumps({"temperature": 23.5, "humidity": 65}),
        )
        assert mock_mqtt.get_control_value("0xa4c1381b020a8ced", "temperature") == "23.5"
        assert mock_mqtt.get_control_value("0xa4c1381b020a8ced", "humidity") == "65"

    def test_device_type_published(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        assert mock_mqtt.get_control_value("0x00158d0001234567", "device_type") == "Маршрутизатор"

    def test_end_device_type(self, bridge, mock_mqtt):
        register_device(mock_mqtt, TEMP_SENSOR_DEVICE)
        assert mock_mqtt.get_control_value("0xa4c1381b020a8ced", "device_type") == "Оконечное устройство"

    def test_color_lamp_rgb(self, bridge, mock_mqtt):
        register_device(mock_mqtt, COLOR_LAMP_DEVICE)
        mock_mqtt.inject_message(
            "zigbee2mqtt/color_lamp",
            json.dumps({"state": "ON", "brightness": 200, "color": {"hue": 0, "saturation": 100}}),
        )
        assert mock_mqtt.get_control_value("0x001788010badf00d", "color") == "255;0;0"
        assert mock_mqtt.get_control_value("0x001788010badf00d", "brightness") == "200"
        assert mock_mqtt.get_control_value("0x001788010badf00d", "state") == "1"

    def test_last_seen_epoch_ms(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        mock_mqtt.inject_message(
            "zigbee2mqtt/test_relay",
            json.dumps({"state": "ON", "last_seen": 1700000000000}),
        )
        value = mock_mqtt.get_control_value("0x00158d0001234567", "last_seen")
        assert value  # non-empty formatted datetime
        assert "2023" in value  # epoch 1700000000 = Nov 2023

    def test_unknown_device_state_ignored(self, bridge, mock_mqtt):
        """State for unregistered device does nothing."""
        register_device(mock_mqtt, RELAY_DEVICE)
        # No callback for "unknown_device"
        assert "zigbee2mqtt/unknown_device" not in mock_mqtt.callbacks

    def test_device_without_exposes_skipped(self, bridge, mock_mqtt):
        """Device without exposes is not registered."""
        device = {
            "ieee_address": "0xdeadbeef",
            "friendly_name": "no_exposes",
            "type": "EndDevice",
            "definition": None,
        }
        register_device(mock_mqtt, device)
        assert "zigbee2mqtt/no_exposes" not in mock_mqtt.callbacks

    def test_control_meta_published(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        meta = mock_mqtt.get_control_meta("0x00158d0001234567", "state")
        assert meta["type"] == "switch"
        assert meta["readonly"] is False

    def test_range_meta_has_min_max(self, bridge, mock_mqtt):
        register_device(mock_mqtt, COLOR_LAMP_DEVICE)
        meta = mock_mqtt.get_control_meta("0x001788010badf00d", "brightness")
        assert meta["type"] == "range"
        assert meta["min"] == 0
        assert meta["max"] == 254


# ---------------------------------------------------------------------------
# 3.2 Device control (WB → z2m)
# ---------------------------------------------------------------------------

class TestDeviceControl:

    def test_relay_switch_on(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        mock_mqtt.inject_message("/devices/0x00158d0001234567/controls/state/on", "1")
        payloads = mock_mqtt.find_published("zigbee2mqtt/test_relay/set")
        assert len(payloads) >= 1
        assert json.loads(payloads[-1]) == {"state": "ON"}

    def test_relay_switch_off(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        mock_mqtt.inject_message("/devices/0x00158d0001234567/controls/state/on", "0")
        payloads = mock_mqtt.find_published("zigbee2mqtt/test_relay/set")
        assert json.loads(payloads[-1]) == {"state": "OFF"}

    def test_brightness_numeric(self, bridge, mock_mqtt):
        register_device(mock_mqtt, COLOR_LAMP_DEVICE)
        mock_mqtt.inject_message("/devices/0x001788010badf00d/controls/brightness/on", "200")
        payloads = mock_mqtt.find_published("zigbee2mqtt/color_lamp/set")
        assert json.loads(payloads[-1]) == {"brightness": 200}

    def test_color_rgb_command(self, bridge, mock_mqtt):
        register_device(mock_mqtt, COLOR_LAMP_DEVICE)
        mock_mqtt.inject_message("/devices/0x001788010badf00d/controls/color/on", "255;0;0")
        payloads = mock_mqtt.find_published("zigbee2mqtt/color_lamp/set")
        assert json.loads(payloads[-1]) == {"color": {"hue": 0, "saturation": 100}}

    def test_readonly_controls_not_subscribed(self, bridge, mock_mqtt):
        register_device(mock_mqtt, TEMP_SENSOR_DEVICE)
        # temperature is readonly — no /on subscription
        assert "/devices/0xa4c1381b020a8ced/controls/temperature/on" not in mock_mqtt.callbacks


# ---------------------------------------------------------------------------
# 3.3 Device lifecycle
# ---------------------------------------------------------------------------

class TestDeviceLifecycle:

    def test_device_registration_creates_meta(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        device_meta_raw = mock_mqtt.retained.get("/devices/0x00158d0001234567/meta", "")
        device_meta = json.loads(device_meta_raw)
        assert device_meta["title"]["en"] == "test_relay"

    def test_device_rename_via_event(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/event",
            json.dumps({"type": "device_renamed", "data": {"from": "test_relay", "to": "new_name"}}),
        )
        # Old topic unsubscribed, new subscribed
        assert "zigbee2mqtt/new_name" in mock_mqtt.subscriptions
        # Device meta updated with new title
        device_meta = json.loads(mock_mqtt.retained["/devices/0x00158d0001234567/meta"])
        assert device_meta["title"]["en"] == "new_name"

    def test_device_rename_via_devices(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        # Same ieee_address, different friendly_name
        renamed = {**RELAY_DEVICE, "friendly_name": "renamed_relay"}
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/devices",
            make_bridge_devices_payload([renamed]),
        )
        assert "zigbee2mqtt/renamed_relay" in mock_mqtt.subscriptions
        device_meta = json.loads(mock_mqtt.retained["/devices/0x00158d0001234567/meta"])
        assert device_meta["title"]["en"] == "renamed_relay"

    def test_device_removal_clears_retain(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        # Verify device exists
        assert mock_mqtt.retained.get("/devices/0x00158d0001234567/meta")
        # Remove device
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/response/device/remove",
            json.dumps({"status": "ok", "data": {"id": "test_relay"}}),
        )
        # All retain topics should be empty
        assert mock_mqtt.retained["/devices/0x00158d0001234567/meta"] == ""

    def test_device_leave_removes(self, bridge, mock_mqtt):
        register_device(mock_mqtt, RELAY_DEVICE)
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/event",
            json.dumps({
                "type": "device_leave",
                "data": {"friendly_name": "test_relay", "ieee_address": "0x00158d0001234567"},
            }),
        )
        assert mock_mqtt.retained["/devices/0x00158d0001234567/meta"] == ""

    def test_stale_device_removed_on_devices_update(self, bridge, mock_mqtt):
        """When a device disappears from bridge/devices, its MQTT topics are cleaned."""
        register_device(mock_mqtt, RELAY_DEVICE)
        assert mock_mqtt.retained.get("/devices/0x00158d0001234567/meta")
        # Re-publish bridge/devices without the relay
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/devices",
            make_bridge_devices_payload([TEMP_SENSOR_DEVICE]),
        )
        assert mock_mqtt.retained["/devices/0x00158d0001234567/meta"] == ""

    def test_control_commands_work_after_rename(self, bridge, mock_mqtt):
        """After rename, commands should go to the new z2m topic."""
        register_device(mock_mqtt, RELAY_DEVICE)
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/event",
            json.dumps({"type": "device_renamed", "data": {"from": "test_relay", "to": "renamed"}}),
        )
        mock_mqtt.inject_message("/devices/0x00158d0001234567/controls/state/on", "1")
        payloads = mock_mqtt.find_published("zigbee2mqtt/renamed/set")
        assert len(payloads) >= 1
        assert json.loads(payloads[-1]) == {"state": "ON"}

    def test_multiple_devices_independent(self, bridge, mock_mqtt):
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/devices",
            make_bridge_devices_payload([RELAY_DEVICE, TEMP_SENSOR_DEVICE]),
        )
        mock_mqtt.inject_message("zigbee2mqtt/test_relay", json.dumps({"state": "ON"}))
        mock_mqtt.inject_message("zigbee2mqtt/temp_sensor", json.dumps({"temperature": 20.0}))
        assert mock_mqtt.get_control_value("0x00158d0001234567", "state") == "1"
        assert mock_mqtt.get_control_value("0xa4c1381b020a8ced", "temperature") == "20.0"


# ---------------------------------------------------------------------------
# 3.4 Bridge device
# ---------------------------------------------------------------------------

class TestBridgeDevice:

    def test_bridge_state_online(self, bridge, mock_mqtt):
        mock_mqtt.inject_message("zigbee2mqtt/bridge/state", "online")
        assert mock_mqtt.get_control_value("zigbee2mqtt", "State") == "online"

    def test_bridge_state_json(self, bridge, mock_mqtt):
        mock_mqtt.inject_message("zigbee2mqtt/bridge/state", json.dumps({"state": "online"}))
        assert mock_mqtt.get_control_value("zigbee2mqtt", "State") == "online"

    def test_bridge_info(self, bridge, mock_mqtt):
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/info",
            json.dumps({"version": "2.5.1", "permit_join": False}),
        )
        assert mock_mqtt.get_control_value("zigbee2mqtt", "Version") == "2.5.1"
        assert mock_mqtt.get_control_value("zigbee2mqtt", "Permit join") == "0"

    def test_permit_join_command(self, bridge, mock_mqtt):
        mock_mqtt.inject_message("/devices/zigbee2mqtt/controls/Permit join/on", "1")
        payloads = mock_mqtt.find_published("zigbee2mqtt/bridge/request/permit_join")
        assert json.loads(payloads[-1]) == {"time": 254}

    def test_permit_join_disable(self, bridge, mock_mqtt):
        mock_mqtt.inject_message("/devices/zigbee2mqtt/controls/Permit join/on", "0")
        payloads = mock_mqtt.find_published("zigbee2mqtt/bridge/request/permit_join")
        assert json.loads(payloads[-1]) == {"time": 0}

    def test_log_filtering_below_min(self, bridge, mock_mqtt):
        """Log level below min_level (warning) should not update Log control."""
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/logging",
            json.dumps({"level": "info", "message": "should be filtered"}),
        )
        assert mock_mqtt.get_control_value("zigbee2mqtt", "Log") != "should be filtered"

    def test_log_filtering_at_min(self, bridge, mock_mqtt):
        """Log at min_level (warning) should update Log control."""
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/logging",
            json.dumps({"level": "warning", "message": "important warning"}),
        )
        assert mock_mqtt.get_control_value("zigbee2mqtt", "Log") == "important warning"

    def test_log_filtering_above_min(self, bridge, mock_mqtt):
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/logging",
            json.dumps({"level": "error", "message": "error msg"}),
        )
        assert mock_mqtt.get_control_value("zigbee2mqtt", "Log") == "error msg"

    def test_device_count(self, bridge, mock_mqtt):
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/devices",
            make_bridge_devices_payload([RELAY_DEVICE, TEMP_SENSOR_DEVICE]),
        )
        assert mock_mqtt.get_control_value("zigbee2mqtt", "Device count") == "2"

    def test_update_devices_command(self, bridge, mock_mqtt):
        mock_mqtt.inject_message("/devices/zigbee2mqtt/controls/Update devices/on", "1")
        payloads = mock_mqtt.find_published("zigbee2mqtt/bridge/request/devices/get")
        assert len(payloads) >= 1


# ---------------------------------------------------------------------------
# 3.5 Ghost device cleanup
# ---------------------------------------------------------------------------

class TestGhostDeviceCleanup:

    def test_ghost_device_removed_on_startup(self):
        """Retained topics from a previous run are cleaned up when bridge starts."""
        mock_mqtt = MockMQTTClient()
        # Simulate ghost device retained from a previous run
        ghost_id = "0xdeadbeef12345678"
        ghost_meta = json.dumps({"driver": "wb-zigbee2mqtt", "title": {"en": "ghost"}})
        ctrl_meta = json.dumps({"type": "switch", "readonly": False})
        mock_mqtt.retained[f"/devices/{ghost_id}/meta"] = ghost_meta
        mock_mqtt.retained[f"/devices/{ghost_id}/controls/state/meta"] = ctrl_meta
        mock_mqtt.retained[f"/devices/{ghost_id}/controls/state"] = "1"

        # Create bridge — subscribe() starts retained scan
        bridge = Bridge(mock_mqtt, "zigbee2mqtt", "zigbee2mqtt", "Zigbee2MQTT", "warning")
        bridge.subscribe()

        # Deliver retained messages to wildcard subscribers
        mock_mqtt.inject_retained()

        # First bridge/devices arrives with only the relay — ghost not in list
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/devices",
            make_bridge_devices_payload([RELAY_DEVICE]),
        )

        # Ghost device topics should be cleared
        assert mock_mqtt.retained[f"/devices/{ghost_id}/meta"] == ""
        assert mock_mqtt.retained[f"/devices/{ghost_id}/controls/state/meta"] == ""
        assert mock_mqtt.retained[f"/devices/{ghost_id}/controls/state"] == ""

    def test_active_device_not_removed_as_ghost(self):
        """Devices present in z2m list should NOT be cleaned up by ghost scan."""
        mock_mqtt = MockMQTTClient()
        # Retained from previous run for a device that still exists
        device_id = "0x00158d0001234567"
        device_meta = json.dumps({"driver": "wb-zigbee2mqtt", "title": {"en": "test_relay"}})
        mock_mqtt.retained[f"/devices/{device_id}/meta"] = device_meta
        mock_mqtt.retained[f"/devices/{device_id}/controls/state/meta"] = json.dumps({"type": "switch"})

        bridge = Bridge(mock_mqtt, "zigbee2mqtt", "zigbee2mqtt", "Zigbee2MQTT", "warning")
        bridge.subscribe()
        mock_mqtt.inject_retained()

        # Device IS in the z2m list — should not be removed
        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/devices",
            make_bridge_devices_payload([RELAY_DEVICE]),
        )

        # Device meta should NOT be empty (it gets re-published by register_device)
        assert mock_mqtt.retained[f"/devices/{device_id}/meta"] != ""

    def test_non_our_device_not_removed(self):
        """Devices without our driver marker should not be touched."""
        mock_mqtt = MockMQTTClient()
        # Some other driver's device
        other_meta = json.dumps({"driver": "wb-modbus", "title": {"en": "modbus device"}})
        mock_mqtt.retained["/devices/wb-modbus-123/meta"] = other_meta
        mock_mqtt.retained["/devices/wb-modbus-123/controls/temp/meta"] = json.dumps({"type": "temperature"})

        bridge = Bridge(mock_mqtt, "zigbee2mqtt", "zigbee2mqtt", "Zigbee2MQTT", "warning")
        bridge.subscribe()
        mock_mqtt.inject_retained()

        mock_mqtt.inject_message(
            "zigbee2mqtt/bridge/devices",
            make_bridge_devices_payload([RELAY_DEVICE]),
        )

        # Other driver's device should be untouched
        assert mock_mqtt.retained["/devices/wb-modbus-123/meta"] == other_meta
