"""Unit tests for wb.mqtt_zigbee.wb_converter.controls."""

import pytest

from wb.mqtt_zigbee.wb_converter.controls import (
    BRIDGE_CONTROLS,
    BridgeControl,
    ControlMeta,
    WbBoolValue,
    WbControlType,
    _hs_dict_to_wb_rgb,
    _parse_number,
    _wb_rgb_to_hs_dict,
)


class TestParseNumber:
    def test_parses_integer_string(self):
        assert _parse_number("42") == 42
        assert isinstance(_parse_number("42"), int)

    def test_parses_float_string(self):
        assert _parse_number("3.14") == 3.14
        assert isinstance(_parse_number("3.14"), float)

    def test_float_with_zero_fraction_returns_int(self):
        assert _parse_number("5.0") == 5
        assert isinstance(_parse_number("5.0"), int)

    def test_negative_numbers(self):
        assert _parse_number("-7") == -7
        assert _parse_number("-2.5") == -2.5

    def test_zero(self):
        assert _parse_number("0") == 0
        assert isinstance(_parse_number("0"), int)

    def test_invalid_string_returned_as_is(self):
        assert _parse_number("abc") == "abc"

    def test_empty_string_returned_as_is(self):
        assert _parse_number("") == ""

    def test_scientific_notation(self):
        # 1e2 == 100.0 -> int 100
        assert _parse_number("1e2") == 100
        assert isinstance(_parse_number("1e2"), int)


class TestWbRgbToHsDict:
    def test_red(self):
        assert _wb_rgb_to_hs_dict("255;0;0") == {"hue": 0, "saturation": 100}

    def test_green(self):
        assert _wb_rgb_to_hs_dict("0;255;0") == {"hue": 120, "saturation": 100}

    def test_blue(self):
        assert _wb_rgb_to_hs_dict("0;0;255") == {"hue": 240, "saturation": 100}

    def test_white_zero_saturation(self):
        assert _wb_rgb_to_hs_dict("255;255;255") == {"hue": 0, "saturation": 0}

    def test_black_zero_saturation(self):
        assert _wb_rgb_to_hs_dict("0;0;0") == {"hue": 0, "saturation": 0}

    @pytest.mark.parametrize(
        "bad_input",
        [
            "",
            "255;0",
            "255;0;0;0",
            "abc;0;0",
            "255;0;xyz",
        ],
    )
    def test_invalid_input_returns_default(self, bad_input):
        assert _wb_rgb_to_hs_dict(bad_input) == {"hue": 0, "saturation": 0}


class TestHsDictToWbRgb:
    def test_red(self):
        assert _hs_dict_to_wb_rgb({"hue": 0, "saturation": 100}) == "255;0;0"

    def test_green(self):
        assert _hs_dict_to_wb_rgb({"hue": 120, "saturation": 100}) == "0;255;0"

    def test_blue(self):
        assert _hs_dict_to_wb_rgb({"hue": 240, "saturation": 100}) == "0;0;255"

    def test_zero_saturation_is_white(self):
        assert _hs_dict_to_wb_rgb({"hue": 0, "saturation": 0}) == "255;255;255"

    def test_extra_keys_ignored(self):
        # z2m typically includes x/y too
        result = _hs_dict_to_wb_rgb({"hue": 0, "saturation": 100, "x": 0.7, "y": 0.3})
        assert result == "255;0;0"

    def test_missing_hue_returns_default(self):
        assert _hs_dict_to_wb_rgb({"saturation": 100}) == "255;255;255"

    def test_missing_saturation_returns_default(self):
        assert _hs_dict_to_wb_rgb({"hue": 0}) == "255;255;255"

    def test_invalid_value_types_return_default(self):
        assert _hs_dict_to_wb_rgb({"hue": "abc", "saturation": 100}) == "255;255;255"
        assert _hs_dict_to_wb_rgb({"hue": None, "saturation": None}) == "255;255;255"

    def test_numeric_string_values_accepted(self):
        # float() accepts numeric strings
        assert _hs_dict_to_wb_rgb({"hue": "0", "saturation": "100"}) == "255;0;0"

    def test_roundtrip_primary_colors(self):
        for rgb in ["255;0;0", "0;255;0", "0;0;255"]:
            assert _hs_dict_to_wb_rgb(_wb_rgb_to_hs_dict(rgb)) == rgb


class TestControlMetaFormatValue:
    def test_none_returns_empty_string(self):
        meta = ControlMeta(type=WbControlType.VALUE, readonly=True)
        assert meta.format_value(None) == ""

    def test_bool_true(self):
        meta = ControlMeta(type=WbControlType.SWITCH, readonly=False)
        assert meta.format_value(True) == WbBoolValue.TRUE

    def test_bool_false(self):
        meta = ControlMeta(type=WbControlType.SWITCH, readonly=False)
        assert meta.format_value(False) == WbBoolValue.FALSE

    def test_switch_with_value_on_match(self):
        meta = ControlMeta(
            type=WbControlType.SWITCH,
            readonly=False,
            value_on="ON",
            value_off="OFF",
        )
        assert meta.format_value("ON") == WbBoolValue.TRUE

    def test_switch_with_value_on_no_match(self):
        meta = ControlMeta(
            type=WbControlType.SWITCH,
            readonly=False,
            value_on="ON",
            value_off="OFF",
        )
        assert meta.format_value("OFF") == WbBoolValue.FALSE
        assert meta.format_value("anything") == WbBoolValue.FALSE

    def test_rgb_with_dict(self):
        meta = ControlMeta(type=WbControlType.RGB, readonly=False)
        assert meta.format_value({"hue": 0, "saturation": 100}) == "255;0;0"

    def test_dict_falls_back_to_json(self):
        meta = ControlMeta(type=WbControlType.TEXT, readonly=True)
        assert meta.format_value({"a": 1}) == '{"a": 1}'

    def test_numeric_value(self):
        meta = ControlMeta(type=WbControlType.VALUE, readonly=True)
        assert meta.format_value(42) == "42"
        assert meta.format_value(3.14) == "3.14"

    def test_string_value(self):
        meta = ControlMeta(type=WbControlType.TEXT, readonly=True)
        assert meta.format_value("hello") == "hello"

    def test_bool_takes_precedence_over_switch_value_on(self):
        # bool check happens before SWITCH+value_on branch
        meta = ControlMeta(
            type=WbControlType.SWITCH,
            readonly=False,
            value_on="ON",
            value_off="OFF",
        )
        assert meta.format_value(True) == WbBoolValue.TRUE
        assert meta.format_value(False) == WbBoolValue.FALSE


class TestControlMetaParseWbValue:
    def test_switch_without_value_on_returns_bool(self):
        meta = ControlMeta(type=WbControlType.SWITCH, readonly=False)
        assert meta.parse_wb_value(WbBoolValue.TRUE) is True
        assert meta.parse_wb_value(WbBoolValue.FALSE) is False

    def test_switch_with_value_on_returns_string(self):
        meta = ControlMeta(
            type=WbControlType.SWITCH,
            readonly=False,
            value_on="ON",
            value_off="OFF",
        )
        assert meta.parse_wb_value(WbBoolValue.TRUE) == "ON"
        assert meta.parse_wb_value(WbBoolValue.FALSE) == "OFF"

    def test_rgb_parses_to_hs_dict(self):
        meta = ControlMeta(type=WbControlType.RGB, readonly=False)
        assert meta.parse_wb_value("255;0;0") == {"hue": 0, "saturation": 100}

    def test_rgb_invalid_returns_default(self):
        meta = ControlMeta(type=WbControlType.RGB, readonly=False)
        assert meta.parse_wb_value("garbage") == {"hue": 0, "saturation": 0}

    def test_text_returns_raw_string(self):
        meta = ControlMeta(type=WbControlType.TEXT, readonly=False)
        assert meta.parse_wb_value("hello") == "hello"
        assert meta.parse_wb_value("123") == "123"  # not parsed as number

    def test_numeric_types_parse_number(self):
        for ctype in (
            WbControlType.VALUE,
            WbControlType.RANGE,
            WbControlType.TEMPERATURE,
            WbControlType.POWER,
        ):
            meta = ControlMeta(type=ctype, readonly=False)
            assert meta.parse_wb_value("42") == 42
            assert meta.parse_wb_value("3.14") == 3.14

    def test_numeric_invalid_returns_string(self):
        meta = ControlMeta(type=WbControlType.VALUE, readonly=False)
        assert meta.parse_wb_value("abc") == "abc"

    def test_format_then_parse_roundtrip_switch_with_value_on(self):
        meta = ControlMeta(
            type=WbControlType.SWITCH,
            readonly=False,
            value_on="ON",
            value_off="OFF",
        )
        assert meta.parse_wb_value(meta.format_value("ON")) == "ON"
        assert meta.parse_wb_value(meta.format_value("OFF")) == "OFF"

    def test_format_then_parse_roundtrip_bool_switch(self):
        meta = ControlMeta(type=WbControlType.SWITCH, readonly=False)
        assert meta.parse_wb_value(meta.format_value(True)) is True
        assert meta.parse_wb_value(meta.format_value(False)) is False


class TestControlMetaDefaults:
    def test_default_field_values(self):
        meta = ControlMeta(type=WbControlType.VALUE, readonly=True)
        assert meta.order is None
        assert not meta.title
        assert meta.value_on is None
        assert meta.value_off is None
        assert meta.enum is None
        assert meta.min is None
        assert meta.max is None

    def test_title_default_is_independent_per_instance(self):
        # default_factory should not share dict between instances
        a = ControlMeta(type=WbControlType.TEXT, readonly=True)
        b = ControlMeta(type=WbControlType.TEXT, readonly=True)
        a.title["en"] = "X"
        assert not b.title


class TestBridgeControls:
    def test_all_bridge_controls_have_metadata(self):
        expected_ids = {
            BridgeControl.STATE,
            BridgeControl.VERSION,
            BridgeControl.PERMIT_JOIN,
            BridgeControl.DEVICE_COUNT,
            BridgeControl.LAST_JOINED,
            BridgeControl.LAST_LEFT,
            BridgeControl.LAST_REMOVED,
            BridgeControl.UPDATE_DEVICES,
            BridgeControl.LAST_SEEN,
            BridgeControl.MESSAGES_RECEIVED,
            BridgeControl.LOG_LEVEL,
            BridgeControl.LOG,
            BridgeControl.RECONNECTS,
        }
        assert set(BRIDGE_CONTROLS.keys()) == expected_ids

    def test_orders_are_unique_and_sequential(self):
        orders = [meta.order for meta in BRIDGE_CONTROLS.values()]
        assert all(o is not None for o in orders)
        assert sorted(orders) == list(range(1, len(orders) + 1))

    def test_all_titles_have_en_and_ru(self):
        for control_id, meta in BRIDGE_CONTROLS.items():
            assert "en" in meta.title, f"{control_id} missing 'en' title"
            assert "ru" in meta.title, f"{control_id} missing 'ru' title"

    def test_writable_controls(self):
        # Only PERMIT_JOIN and UPDATE_DEVICES should be writable
        writable = {cid for cid, m in BRIDGE_CONTROLS.items() if not m.readonly}
        assert writable == {BridgeControl.PERMIT_JOIN, BridgeControl.UPDATE_DEVICES}

    def test_permit_join_is_switch(self):
        assert BRIDGE_CONTROLS[BridgeControl.PERMIT_JOIN].type == WbControlType.SWITCH

    def test_update_devices_is_pushbutton(self):
        assert BRIDGE_CONTROLS[BridgeControl.UPDATE_DEVICES].type == WbControlType.PUSHBUTTON
