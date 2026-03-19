"""Unit tests for map_exposes_to_controls() and helpers."""

import pytest

from wb.zigbee2mqtt.z2m.model import ExposeAccess, ExposeFeature
from wb.zigbee2mqtt.wb_converter.controls import WbControlType
from wb.zigbee2mqtt.wb_converter.expose_mapper import map_exposes_to_controls


# ---------------------------------------------------------------------------
# 2.1 Leaf features
# ---------------------------------------------------------------------------

class TestLeafFeatures:

    def test_temperature_readonly(self):
        feature = ExposeFeature(type="numeric", name="temperature", property="temperature", access=ExposeAccess.READ)
        controls = map_exposes_to_controls([feature])
        assert "temperature" in controls
        assert controls["temperature"].type == WbControlType.TEMPERATURE
        assert controls["temperature"].readonly is True

    def test_humidity_readonly(self):
        feature = ExposeFeature(type="numeric", name="humidity", property="humidity", access=ExposeAccess.READ)
        controls = map_exposes_to_controls([feature])
        assert controls["humidity"].type == WbControlType.REL_HUMIDITY
        assert controls["humidity"].readonly is True

    def test_brightness_writable_with_min_max_becomes_range(self):
        feature = ExposeFeature(
            type="numeric", name="brightness", property="brightness",
            access=ExposeAccess.READ | ExposeAccess.WRITE,
            value_min=0, value_max=254,
        )
        controls = map_exposes_to_controls([feature])
        assert controls["brightness"].type == WbControlType.RANGE
        assert controls["brightness"].readonly is False
        assert controls["brightness"].min == 0
        assert controls["brightness"].max == 254

    def test_brightness_writable_without_min_max_stays_value(self):
        feature = ExposeFeature(
            type="numeric", name="brightness", property="brightness",
            access=ExposeAccess.READ | ExposeAccess.WRITE,
        )
        controls = map_exposes_to_controls([feature])
        assert controls["brightness"].type == WbControlType.VALUE
        assert controls["brightness"].readonly is False

    def test_unknown_numeric_becomes_value(self):
        feature = ExposeFeature(type="numeric", name="something", property="something", access=ExposeAccess.READ)
        controls = map_exposes_to_controls([feature])
        assert controls["something"].type == WbControlType.VALUE

    def test_binary_becomes_switch(self):
        feature = ExposeFeature(
            type="binary", name="state", property="state",
            access=ExposeAccess.READ | ExposeAccess.WRITE | ExposeAccess.GET,
            value_on="ON", value_off="OFF",
        )
        controls = map_exposes_to_controls([feature])
        assert controls["state"].type == WbControlType.SWITCH
        assert controls["state"].readonly is False
        assert controls["state"].value_on == "ON"
        assert controls["state"].value_off == "OFF"

    def test_binary_readonly(self):
        feature = ExposeFeature(
            type="binary", name="occupancy", property="occupancy",
            access=ExposeAccess.READ,
            value_on="true", value_off="false",
        )
        controls = map_exposes_to_controls([feature])
        assert controls["occupancy"].type == WbControlType.SWITCH
        assert controls["occupancy"].readonly is True

    def test_enum(self):
        feature = ExposeFeature(
            type="enum", name="mode", property="mode",
            access=ExposeAccess.READ | ExposeAccess.WRITE,
            values=["off", "auto", "heat"],
        )
        controls = map_exposes_to_controls([feature])
        assert controls["mode"].type == WbControlType.TEXT
        assert controls["mode"].enum == {"off": 0, "auto": 1, "heat": 2}
        assert controls["mode"].readonly is False

    def test_text(self):
        feature = ExposeFeature(type="text", name="effect", property="effect", access=ExposeAccess.READ)
        controls = map_exposes_to_controls([feature])
        assert controls["effect"].type == WbControlType.TEXT

    def test_empty_property_skipped(self):
        feature = ExposeFeature(type="numeric", name="test", property="", access=ExposeAccess.READ)
        controls = map_exposes_to_controls([feature])
        # Only service controls (last_seen)
        assert "test" not in controls

    def test_all_numeric_types(self):
        """Verify all 10 NUMERIC_TYPE_MAP entries."""
        mapping = {
            "temperature": WbControlType.TEMPERATURE,
            "humidity": WbControlType.REL_HUMIDITY,
            "pressure": WbControlType.ATMOSPHERIC_PRESSURE,
            "co2": WbControlType.CONCENTRATION,
            "noise": WbControlType.SOUND_LEVEL,
            "power": WbControlType.POWER,
            "voltage": WbControlType.VOLTAGE,
            "current": WbControlType.CURRENT,
            "energy": WbControlType.POWER_CONSUMPTION,
            "illuminance_lux": WbControlType.ILLUMINANCE,
        }
        for prop, expected_type in mapping.items():
            feature = ExposeFeature(type="numeric", name=prop, property=prop, access=ExposeAccess.READ)
            controls = map_exposes_to_controls([feature])
            assert controls[prop].type == expected_type, f"Failed for {prop}"


# ---------------------------------------------------------------------------
# 2.2 Composite features
# ---------------------------------------------------------------------------

class TestCompositeFeatures:

    def test_light_with_state_and_brightness(self, color_lamp_exposes):
        controls = map_exposes_to_controls(color_lamp_exposes)
        assert controls["state"].type == WbControlType.SWITCH
        assert controls["state"].readonly is False
        assert controls["brightness"].type == WbControlType.RANGE
        assert controls["brightness"].readonly is False

    def test_color_composite_becomes_rgb(self, color_lamp_exposes):
        controls = map_exposes_to_controls(color_lamp_exposes)
        assert "color" in controls
        assert controls["color"].type == WbControlType.RGB

    def test_switch_with_nested_state(self, relay_exposes):
        controls = map_exposes_to_controls(relay_exposes)
        assert "state" in controls
        assert controls["state"].type == WbControlType.SWITCH
        assert controls["state"].readonly is False

    def test_color_lamp_has_color_temp(self, color_lamp_exposes):
        controls = map_exposes_to_controls(color_lamp_exposes)
        assert "color_temp" in controls
        assert controls["color_temp"].type == WbControlType.RANGE
        assert controls["color_temp"].min == 150
        assert controls["color_temp"].max == 500


# ---------------------------------------------------------------------------
# 2.3 Service controls
# ---------------------------------------------------------------------------

class TestServiceControls:

    def test_device_type_added_when_present(self, relay_exposes):
        controls = map_exposes_to_controls(relay_exposes, device_type="Router")
        assert "device_type" in controls
        assert controls["device_type"].type == WbControlType.TEXT
        assert controls["device_type"].readonly is True

    def test_device_type_not_added_when_empty(self, relay_exposes):
        controls = map_exposes_to_controls(relay_exposes, device_type="")
        assert "device_type" not in controls

    def test_last_seen_always_last(self, relay_exposes):
        controls = map_exposes_to_controls(relay_exposes, device_type="Router")
        assert "last_seen" in controls
        assert controls["last_seen"].readonly is True
        # last_seen should have the highest order
        max_order = max(m.order for m in controls.values() if m.order is not None)
        assert controls["last_seen"].order == max_order


# ---------------------------------------------------------------------------
# 2.4 Order and deduplication
# ---------------------------------------------------------------------------

class TestOrderAndDedup:

    def test_sequential_order(self, temp_sensor_exposes):
        controls = map_exposes_to_controls(temp_sensor_exposes)
        orders = [m.order for m in controls.values() if m.order is not None]
        assert orders == list(range(1, len(orders) + 1))

    def test_duplicate_property_ignored(self):
        """Second expose with same property is ignored."""
        f1 = ExposeFeature(type="numeric", name="temp", property="temperature", access=ExposeAccess.READ)
        f2 = ExposeFeature(type="numeric", name="temp2", property="temperature", access=ExposeAccess.READ | ExposeAccess.WRITE)
        controls = map_exposes_to_controls([f1, f2])
        # First one wins — readonly
        assert controls["temperature"].readonly is True


# ---------------------------------------------------------------------------
# 2.5 Full device fixtures
# ---------------------------------------------------------------------------

class TestFullDevices:

    def test_temp_sensor(self, temp_sensor_exposes):
        controls = map_exposes_to_controls(temp_sensor_exposes, device_type="EndDevice")
        assert "temperature" in controls
        assert "humidity" in controls
        assert "battery" in controls
        assert "device_type" in controls
        assert "last_seen" in controls

    def test_multisensor(self, multisensor_exposes):
        controls = map_exposes_to_controls(multisensor_exposes)
        assert controls["temperature"].type == WbControlType.TEMPERATURE
        assert controls["humidity"].type == WbControlType.REL_HUMIDITY
        assert controls["illuminance_lux"].type == WbControlType.ILLUMINANCE
        assert controls["occupancy"].type == WbControlType.SWITCH
        assert controls["occupancy"].readonly is True

    def test_color_lamp_full(self, color_lamp_exposes):
        controls = map_exposes_to_controls(color_lamp_exposes, device_type="Router")
        expected_keys = {"state", "brightness", "color_temp", "color", "device_type", "last_seen"}
        assert set(controls.keys()) == expected_keys
