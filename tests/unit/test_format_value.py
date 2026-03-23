"""Unit tests for ControlMeta.format_value() and parse_wb_value()."""

import pytest

from wb.zigbee2mqtt.wb_converter.controls import ControlMeta, WbControlType

# ---------------------------------------------------------------------------
# 1.1 Switch (binary)
# ---------------------------------------------------------------------------


class TestSwitchFormatValue:
    """format_value: z2m → WB for switch type."""

    @pytest.mark.parametrize(
        "z2m_val, value_on, value_off, expected",
        [
            ("ON", "ON", "OFF", "1"),
            ("OFF", "ON", "OFF", "0"),
            ("toggle", "toggle", "off", "1"),
            ("off", "toggle", "off", "0"),
        ],
    )
    def test_with_value_on_off(self, z2m_val, value_on, value_off, expected):
        meta = ControlMeta(type=WbControlType.SWITCH, readonly=False, value_on=value_on, value_off=value_off)
        assert meta.format_value(z2m_val) == expected

    @pytest.mark.parametrize(
        "z2m_val, expected",
        [
            (True, "1"),
            (False, "0"),
        ],
    )
    def test_bool_without_value_on(self, z2m_val, expected):
        meta = ControlMeta(type=WbControlType.SWITCH, readonly=False)
        assert meta.format_value(z2m_val) == expected


class TestSwitchParseWbValue:
    """parse_wb_value: WB → z2m for switch type."""

    @pytest.mark.parametrize(
        "wb_val, value_on, value_off, expected",
        [
            ("1", "ON", "OFF", "ON"),
            ("0", "ON", "OFF", "OFF"),
            ("1", "toggle", "off", "toggle"),
            ("0", "toggle", "off", "off"),
        ],
    )
    def test_with_value_on_off(self, wb_val, value_on, value_off, expected):
        meta = ControlMeta(type=WbControlType.SWITCH, readonly=False, value_on=value_on, value_off=value_off)
        assert meta.parse_wb_value(wb_val) == expected

    @pytest.mark.parametrize(
        "wb_val, expected",
        [
            ("1", True),
            ("0", False),
        ],
    )
    def test_bool_without_value_on(self, wb_val, expected):
        meta = ControlMeta(type=WbControlType.SWITCH, readonly=False)
        assert meta.parse_wb_value(wb_val) == expected


# ---------------------------------------------------------------------------
# 1.2 Numeric (value / range)
# ---------------------------------------------------------------------------


class TestNumericFormatValue:

    @pytest.mark.parametrize(
        "z2m_val, expected",
        [
            (23.5, "23.5"),
            (100, "100"),
            (0, "0"),
            (254, "254"),
            (-10.3, "-10.3"),
        ],
    )
    def test_numeric(self, z2m_val, expected):
        meta = ControlMeta(type=WbControlType.VALUE, readonly=True)
        assert meta.format_value(z2m_val) == expected

    def test_range_same_as_value(self):
        meta = ControlMeta(type=WbControlType.RANGE, readonly=False, min=0, max=254)
        assert meta.format_value(200) == "200"


class TestNumericParseWbValue:

    @pytest.mark.parametrize(
        "wb_val, expected_type, expected_val",
        [
            ("23.5", float, 23.5),
            ("100", int, 100),
            ("0", int, 0),
            ("-10.3", float, -10.3),
            ("254", int, 254),
        ],
    )
    def test_parse(self, wb_val, expected_type, expected_val):
        meta = ControlMeta(type=WbControlType.VALUE, readonly=True)
        result = meta.parse_wb_value(wb_val)
        assert result == expected_val
        assert isinstance(result, expected_type)

    def test_range_parse(self):
        meta = ControlMeta(type=WbControlType.RANGE, readonly=False, min=0, max=254)
        assert meta.parse_wb_value("200") == 200


# ---------------------------------------------------------------------------
# 1.3 RGB (color)
# ---------------------------------------------------------------------------


class TestRGBFormatValue:

    @pytest.mark.parametrize(
        "hs_dict, expected_rgb",
        [
            ({"hue": 0, "saturation": 100}, "255;0;0"),
            ({"hue": 240, "saturation": 100}, "0;0;255"),
            ({"hue": 120, "saturation": 100}, "0;255;0"),
            ({"hue": 0, "saturation": 0}, "255;255;255"),
        ],
    )
    def test_hs_to_rgb(self, hs_dict, expected_rgb):
        meta = ControlMeta(type=WbControlType.RGB, readonly=False)
        assert meta.format_value(hs_dict) == expected_rgb


class TestRGBParseWbValue:

    @pytest.mark.parametrize(
        "wb_rgb, expected_hs",
        [
            ("255;0;0", {"hue": 0, "saturation": 100}),
            ("0;0;255", {"hue": 240, "saturation": 100}),
            ("0;255;0", {"hue": 120, "saturation": 100}),
            ("255;255;255", {"hue": 0, "saturation": 0}),
        ],
    )
    def test_rgb_to_hs(self, wb_rgb, expected_hs):
        meta = ControlMeta(type=WbControlType.RGB, readonly=False)
        assert meta.parse_wb_value(wb_rgb) == expected_hs


# ---------------------------------------------------------------------------
# 1.4 Text / Enum
# ---------------------------------------------------------------------------


class TestTextFormatValue:

    @pytest.mark.parametrize(
        "z2m_val, expected",
        [
            ("auto", "auto"),
            ("heat", "heat"),
            ("", ""),
        ],
    )
    def test_text(self, z2m_val, expected):
        meta = ControlMeta(type=WbControlType.TEXT, readonly=False)
        assert meta.format_value(z2m_val) == expected


class TestTextParseWbValue:

    @pytest.mark.parametrize(
        "wb_val, expected",
        [
            ("auto", "auto"),
            ("heat", "heat"),
            ("", ""),
        ],
    )
    def test_text(self, wb_val, expected):
        meta = ControlMeta(type=WbControlType.TEXT, readonly=False)
        assert meta.parse_wb_value(wb_val) == expected


# ---------------------------------------------------------------------------
# 1.5 Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:

    def test_format_none_returns_empty(self):
        for ctrl_type in [WbControlType.SWITCH, WbControlType.VALUE, WbControlType.TEXT, WbControlType.RGB]:
            meta = ControlMeta(type=ctrl_type, readonly=True)
            assert meta.format_value(None) == ""

    def test_format_bool_true_without_value_on(self):
        """bool True goes through isinstance(value, bool) before switch check."""
        meta = ControlMeta(type=WbControlType.SWITCH, readonly=False)
        assert meta.format_value(True) == "1"
        assert meta.format_value(False) == "0"

    def test_format_dict_non_rgb(self):
        """Non-RGB dict → JSON string."""
        meta = ControlMeta(type=WbControlType.TEXT, readonly=True)
        assert meta.format_value({"key": "val"}) == '{"key": "val"}'

    def test_parse_invalid_number(self):
        """Invalid number string → returned as-is."""
        meta = ControlMeta(type=WbControlType.VALUE, readonly=True)
        assert meta.parse_wb_value("abc") == "abc"

    def test_parse_empty_string_numeric(self):
        meta = ControlMeta(type=WbControlType.VALUE, readonly=True)
        assert meta.parse_wb_value("") == ""

    def test_parse_invalid_rgb_returns_zero(self):
        """Invalid RGB string → fallback to hue=0, saturation=0."""
        meta = ControlMeta(type=WbControlType.RGB, readonly=False)
        assert meta.parse_wb_value("invalid") == {"hue": 0, "saturation": 0}
        assert meta.parse_wb_value("255;0") == {"hue": 0, "saturation": 0}
        assert meta.parse_wb_value("") == {"hue": 0, "saturation": 0}

    def test_format_color_missing_hue_saturation(self):
        """Color dict without hue/saturation → white fallback."""
        meta = ControlMeta(type=WbControlType.RGB, readonly=False)
        assert meta.format_value({"x": 0.3, "y": 0.4}) == "255;255;255"
        assert meta.format_value({}) == "255;255;255"


# ---------------------------------------------------------------------------
# 1.6 Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:

    def test_switch_round_trip(self):
        meta = ControlMeta(type=WbControlType.SWITCH, readonly=False, value_on="ON", value_off="OFF")
        for z2m_val in ["ON", "OFF"]:
            wb = meta.format_value(z2m_val)
            assert meta.parse_wb_value(wb) == z2m_val

    def test_numeric_round_trip(self):
        meta = ControlMeta(type=WbControlType.VALUE, readonly=True)
        for z2m_val in [23.5, 100, 0, -5.7]:
            wb = meta.format_value(z2m_val)
            assert meta.parse_wb_value(wb) == z2m_val

    def test_rgb_round_trip(self):
        meta = ControlMeta(type=WbControlType.RGB, readonly=False)
        for hs in [
            {"hue": 0, "saturation": 100},
            {"hue": 240, "saturation": 100},
            {"hue": 0, "saturation": 0},
        ]:
            wb = meta.format_value(hs)
            assert meta.parse_wb_value(wb) == hs

    def test_text_round_trip(self):
        meta = ControlMeta(type=WbControlType.TEXT, readonly=False)
        for val in ["auto", "heat", ""]:
            wb = meta.format_value(val)
            assert meta.parse_wb_value(wb) == val
