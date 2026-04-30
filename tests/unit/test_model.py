"""Unit tests for wb.mqtt_zigbee.z2m.model."""

from wb.mqtt_zigbee.z2m.model import (
    BridgeInfo,
    BridgeLogLevel,
    BridgeState,
    DeviceAvailability,
    DeviceEvent,
    DeviceEventType,
    ExposeAccess,
    ExposeFeature,
    ExposeType,
    Z2MDevice,
    Z2MEventType,
    _str_or_none,
)


class TestStrOrNone:
    def test_none_returns_none(self):
        assert _str_or_none(None) is None

    def test_string_returned_as_is(self):
        assert _str_or_none("ON") == "ON"

    def test_int_converted_to_string(self):
        assert _str_or_none(1) == "1"

    def test_bool_converted_to_string(self):
        # bool is a common z2m value type for value_on/value_off.
        # NOTE: str(True) == "True" (not "true"!) — see docs/REFACTORING.md.
        # If z2m starts sending bool consistently, this will silently
        # break switch comparisons in ControlMeta.format_value.
        assert _str_or_none(True) == "True"
        assert _str_or_none(False) == "False"

    def test_empty_string_preserved(self):
        # empty string is not None — must be returned as ""
        assert _str_or_none("") == ""


class TestExposeFeatureIsWritable:
    def test_writable_when_write_bit_set(self):
        feat = ExposeFeature(type="numeric", name="x", property="x", access=ExposeAccess.WRITE)
        assert feat.is_writable is True

    def test_writable_when_read_and_write(self):
        feat = ExposeFeature(
            type="numeric",
            name="x",
            property="x",
            access=ExposeAccess.READ | ExposeAccess.WRITE,
        )
        assert feat.is_writable is True

    def test_not_writable_when_only_read(self):
        feat = ExposeFeature(type="numeric", name="x", property="x", access=ExposeAccess.READ)
        assert feat.is_writable is False

    def test_not_writable_when_zero_access(self):
        feat = ExposeFeature(type="numeric", name="x", property="x", access=0)
        assert feat.is_writable is False

    def test_not_writable_when_only_get(self):
        feat = ExposeFeature(type="numeric", name="x", property="x", access=ExposeAccess.GET)
        assert feat.is_writable is False


class TestExposeFeatureFromDict:
    def test_full_leaf_feature(self):
        feat = ExposeFeature.from_dict(
            {
                "type": "numeric",
                "name": "temperature",
                "property": "temperature",
                "access": 1,
                "unit": "°C",
                "value_min": -40,
                "value_max": 80,
            }
        )
        assert feat.type == "numeric"
        assert feat.name == "temperature"
        assert feat.property == "temperature"
        assert feat.access == 1
        assert feat.unit == "°C"
        assert feat.value_min == -40
        assert feat.value_max == 80
        assert feat.value_on is None
        assert feat.value_off is None
        assert not feat.values
        assert not feat.features

    def test_empty_dict_uses_defaults(self):
        feat = ExposeFeature.from_dict({})
        assert feat.type == ""
        assert feat.name == ""
        assert feat.property == ""
        assert feat.access == 0
        assert feat.unit == ""
        assert feat.value_min is None
        assert feat.value_max is None
        assert feat.value_on is None
        assert feat.value_off is None
        assert not feat.values
        assert not feat.features

    def test_binary_with_value_on_off(self):
        feat = ExposeFeature.from_dict(
            {
                "type": "binary",
                "property": "state",
                "access": 3,
                "value_on": "ON",
                "value_off": "OFF",
            }
        )
        assert feat.value_on == "ON"
        assert feat.value_off == "OFF"

    def test_value_on_off_converted_to_string(self):
        # z2m sometimes uses bool/int for value_on/value_off
        feat = ExposeFeature.from_dict(
            {
                "type": "binary",
                "property": "occupancy",
                "value_on": True,
                "value_off": False,
            }
        )
        assert feat.value_on == "True"
        assert feat.value_off == "False"

    def test_value_on_off_none_stays_none(self):
        feat = ExposeFeature.from_dict({"type": "numeric", "property": "x"})
        assert feat.value_on is None
        assert feat.value_off is None

    def test_enum_values(self):
        feat = ExposeFeature.from_dict(
            {
                "type": "enum",
                "property": "mode",
                "values": ["off", "low", "high"],
            }
        )
        assert feat.values == ["off", "low", "high"]

    def test_composite_with_nested_features(self):
        feat = ExposeFeature.from_dict(
            {
                "type": "light",
                "property": "",
                "features": [
                    {"type": "binary", "property": "state", "value_on": "ON", "value_off": "OFF"},
                    {"type": "numeric", "property": "brightness", "value_min": 0, "value_max": 254},
                ],
            }
        )
        assert feat.type == "light"
        assert len(feat.features) == 2
        assert feat.features[0].type == "binary"
        assert feat.features[0].property == "state"
        assert feat.features[0].value_on == "ON"
        assert feat.features[1].property == "brightness"
        assert feat.features[1].value_max == 254

    def test_deeply_nested_features(self):
        feat = ExposeFeature.from_dict(
            {
                "type": "composite",
                "property": "color",
                "features": [
                    {
                        "type": "composite",
                        "property": "inner",
                        "features": [{"type": "numeric", "property": "x"}],
                    }
                ],
            }
        )
        assert feat.features[0].features[0].property == "x"


class TestZ2MDeviceFromDict:
    def test_full_device(self):
        device = Z2MDevice.from_dict(
            {
                "ieee_address": "0x00158d0001abcdef",
                "friendly_name": "kitchen_sensor",
                "type": "EndDevice",
                "definition": {
                    "model": "WSDCGQ11LM",
                    "vendor": "Aqara",
                    "description": "Temperature and humidity sensor",
                    "exposes": [
                        {"type": "numeric", "property": "temperature", "access": 1},
                        {"type": "numeric", "property": "humidity", "access": 1},
                    ],
                },
            }
        )
        assert device.ieee_address == "0x00158d0001abcdef"
        assert device.friendly_name == "kitchen_sensor"
        assert device.type == "EndDevice"
        assert device.model == "WSDCGQ11LM"
        assert device.vendor == "Aqara"
        assert device.description == "Temperature and humidity sensor"
        assert len(device.exposes) == 2
        assert device.exposes[0].property == "temperature"

    def test_empty_dict_uses_defaults(self):
        device = Z2MDevice.from_dict({})
        assert device.ieee_address == ""
        assert device.friendly_name == ""
        assert device.type == ""
        assert device.model == ""
        assert device.vendor == ""
        assert device.description == ""
        assert not device.exposes

    def test_definition_none(self):
        # zigbee2mqtt uses null for unsupported devices
        device = Z2MDevice.from_dict(
            {
                "ieee_address": "0x123",
                "friendly_name": "unknown",
                "type": "Router",
                "definition": None,
            }
        )
        assert device.model == ""
        assert device.vendor == ""
        assert device.description == ""
        assert not device.exposes

    def test_definition_missing(self):
        device = Z2MDevice.from_dict({"ieee_address": "0x1", "friendly_name": "n", "type": "Router"})
        assert not device.exposes

    def test_definition_without_exposes(self):
        device = Z2MDevice.from_dict(
            {
                "ieee_address": "0x1",
                "friendly_name": "n",
                "type": "Router",
                "definition": {"model": "M", "vendor": "V"},
            }
        )
        assert device.model == "M"
        assert device.vendor == "V"
        assert not device.exposes


class TestDataclassDefaults:
    def test_bridge_info_required_fields(self):
        info = BridgeInfo(version="1.30.0", permit_join=False, permit_join_end=None)
        assert info.version == "1.30.0"
        assert info.permit_join is False
        assert info.permit_join_end is None

    def test_device_event_default_old_name(self):
        ev = DeviceEvent(type=DeviceEventType.JOINED, name="bulb")
        assert ev.old_name == ""

    def test_device_event_with_rename(self):
        ev = DeviceEvent(type=DeviceEventType.RENAMED, name="new", old_name="old")
        assert ev.old_name == "old"

    def test_expose_feature_factory_defaults_isolated(self):
        # default_factory must produce independent containers per instance
        a = ExposeFeature(type="x", name="a", property="a")
        b = ExposeFeature(type="x", name="b", property="b")
        a.values.append("v")
        a.features.append(ExposeFeature(type="y", name="c", property="c"))
        assert not b.values
        assert not b.features

    def test_z2m_device_factory_defaults_isolated(self):
        a = Z2MDevice(ieee_address="1", friendly_name="a", type="t")
        b = Z2MDevice(ieee_address="2", friendly_name="b", type="t")
        a.exposes.append(ExposeFeature(type="x", name="x", property="x"))
        assert not b.exposes


class TestEnumLikeConstants:
    def test_expose_access_bits(self):
        assert ExposeAccess.READ == 0b001
        assert ExposeAccess.WRITE == 0b010
        assert ExposeAccess.GET == 0b100

    def test_bridge_state_values(self):
        assert BridgeState.ONLINE == "online"
        assert BridgeState.OFFLINE == "offline"
        assert BridgeState.ERROR == "error"

    def test_device_availability_values(self):
        assert DeviceAvailability.ONLINE == "online"
        assert DeviceAvailability.OFFLINE == "offline"

    def test_z2m_event_type_values(self):
        assert Z2MEventType.DEVICE_JOINED == "device_joined"
        assert Z2MEventType.DEVICE_LEAVE == "device_leave"
        assert Z2MEventType.DEVICE_RENAMED == "device_renamed"

    def test_device_event_type_values(self):
        assert DeviceEventType.JOINED == "joined"
        assert DeviceEventType.LEFT == "left"
        assert DeviceEventType.REMOVED == "removed"
        assert DeviceEventType.RENAMED == "renamed"

    def test_expose_type_values(self):
        # spot-check that constants are non-empty distinct strings
        values = [
            ExposeType.NUMERIC,
            ExposeType.BINARY,
            ExposeType.ENUM,
            ExposeType.TEXT,
            ExposeType.LIGHT,
            ExposeType.SWITCH,
            ExposeType.LOCK,
            ExposeType.CLIMATE,
            ExposeType.FAN,
            ExposeType.COVER,
            ExposeType.COMPOSITE,
        ]
        assert len(set(values)) == len(values)
        assert all(isinstance(v, str) and v for v in values)


class TestBridgeLogLevel:
    def test_rank_ordering(self):
        rank = BridgeLogLevel.RANK
        assert rank[BridgeLogLevel.DEBUG] < rank[BridgeLogLevel.INFO]
        assert rank[BridgeLogLevel.INFO] < rank[BridgeLogLevel.WARNING]
        assert rank[BridgeLogLevel.WARNING] < rank[BridgeLogLevel.ERROR]

    def test_rank_covers_all_levels(self):
        assert set(BridgeLogLevel.RANK.keys()) == {
            BridgeLogLevel.DEBUG,
            BridgeLogLevel.INFO,
            BridgeLogLevel.WARNING,
            BridgeLogLevel.ERROR,
        }

    def test_level_values(self):
        assert BridgeLogLevel.DEBUG == "debug"
        assert BridgeLogLevel.INFO == "info"
        assert BridgeLogLevel.WARNING == "warning"
        assert BridgeLogLevel.ERROR == "error"
