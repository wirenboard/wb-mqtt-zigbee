"""Unit tests for wb.mqtt_zigbee.wb_converter.expose_mapper."""

# pylint: disable=too-many-arguments,too-many-positional-arguments,redefined-builtin,too-few-public-methods

from typing import Optional

import pytest

from wb.mqtt_zigbee.wb_converter.controls import WbControlType
from wb.mqtt_zigbee.wb_converter.expose_mapper import (
    _flatten_expose,
    _make_enum,
    _make_title,
    _map_color_feature,
    _map_leaf_feature,
    _resolve_wb_type,
    map_exposes_to_controls,
)
from wb.mqtt_zigbee.z2m.model import ExposeAccess, ExposeFeature, ExposeType

READABLE = ExposeAccess.READ  # 0b001
WRITABLE = ExposeAccess.READ | ExposeAccess.WRITE  # 0b011


def make_expose(
    type: str = ExposeType.NUMERIC,
    name: str = "",
    property: str = "",
    access: int = READABLE,
    value_min: Optional[float] = None,
    value_max: Optional[float] = None,
    value_on: Optional[str] = None,
    value_off: Optional[str] = None,
    values: Optional[list] = None,
    features: Optional[list] = None,
) -> ExposeFeature:
    """Factory for ExposeFeature with sensible defaults (readable numeric leaf)."""
    return ExposeFeature(
        type=type,
        name=name or property,
        property=property,
        access=access,
        value_min=value_min,
        value_max=value_max,
        value_on=value_on,
        value_off=value_off,
        values=values if values is not None else [],
        features=features if features is not None else [],
    )


# =============================================================================
# map_exposes_to_controls — public API
# =============================================================================


class TestMapExposesToControls:
    def test_empty_exposes_returns_only_service_controls(self):
        controls = map_exposes_to_controls([])
        assert set(controls.keys()) == {"available", "last_seen"}

    def test_device_type_added_when_non_empty(self):
        controls = map_exposes_to_controls([], device_type="Router")
        assert "device_type" in controls
        assert controls["device_type"].type == WbControlType.TEXT
        assert controls["device_type"].readonly is True

    def test_device_type_skipped_when_empty(self):
        controls = map_exposes_to_controls([], device_type="")
        assert "device_type" not in controls

    def test_assigns_sequential_order_starting_from_1(self):
        exposes = [
            make_expose(property="temperature"),
            make_expose(property="humidity"),
        ]
        controls = map_exposes_to_controls(exposes, device_type="Router")
        orders = [
            controls[key].order
            for key in ("temperature", "humidity", "available", "device_type", "last_seen")
        ]
        assert orders == [1, 2, 3, 4, 5]

    def test_deduplicates_by_property_first_wins(self):
        exposes = [
            make_expose(type=ExposeType.BINARY, property="state", value_on="ON", value_off="OFF"),
            make_expose(type=ExposeType.BINARY, property="state", value_on="DIFF", value_off="XXX"),
        ]
        controls = map_exposes_to_controls(exposes)
        assert controls["state"].value_on == "ON"
        assert controls["state"].value_off == "OFF"

    def test_available_is_readonly_switch_with_bilingual_title(self):
        controls = map_exposes_to_controls([])
        meta = controls["available"]
        assert meta.type == WbControlType.SWITCH
        assert meta.readonly is True
        assert meta.title == {"en": "Available", "ru": "Доступно"}

    def test_last_seen_is_readonly_text(self):
        controls = map_exposes_to_controls([])
        assert controls["last_seen"].type == WbControlType.TEXT
        assert controls["last_seen"].readonly is True

    def test_expose_without_property_does_not_break_order(self):
        exposes = [
            make_expose(property=""),  # skipped — no property
            make_expose(property="temperature"),
        ]
        controls = map_exposes_to_controls(exposes)
        assert controls["temperature"].order == 1
        assert controls["available"].order == 2
        assert controls["last_seen"].order == 3


# =============================================================================
# _flatten_expose — recursion
# =============================================================================


class TestFlattenExpose:
    def test_leaf_returned_as_single_pair(self):
        expose = make_expose(property="temperature")
        result = _flatten_expose(expose)
        assert [p for p, _ in result] == ["temperature"]

    def test_composite_unwrapped_recursively(self):
        expose = make_expose(
            type=ExposeType.LIGHT,
            features=[
                make_expose(
                    type=ExposeType.BINARY,
                    property="state",
                    value_on="ON",
                    value_off="OFF",
                ),
                make_expose(type=ExposeType.NUMERIC, property="brightness"),
            ],
        )
        result = _flatten_expose(expose)
        assert [p for p, _ in result] == ["state", "brightness"]

    def test_nested_composite_recurses_multiple_levels(self):
        # light → [state, composite(property="color", features=[x, y])]
        expose = make_expose(
            type=ExposeType.LIGHT,
            features=[
                make_expose(
                    type=ExposeType.BINARY,
                    property="state",
                    value_on="ON",
                    value_off="OFF",
                ),
                make_expose(
                    type=ExposeType.COMPOSITE,
                    property="color",
                    features=[
                        make_expose(property="x"),
                        make_expose(property="y"),
                    ],
                ),
            ],
        )
        result = _flatten_expose(expose)
        props = [p for p, _ in result]
        assert props == ["state", "color"]

    def test_composite_with_color_property_becomes_single_rgb(self):
        expose = make_expose(
            type=ExposeType.COMPOSITE,
            property="color",
            features=[
                make_expose(property="hue"),
                make_expose(property="saturation"),
            ],
        )
        [(prop, meta)] = _flatten_expose(expose)
        assert prop == "color"
        assert meta.type == WbControlType.RGB

    def test_composite_type_without_features_falls_through_to_leaf(self):
        # NESTED_TYPES check requires non-empty features — empty falls to leaf
        # mapping, which rejects because LIGHT is not a known leaf type.
        expose = make_expose(type=ExposeType.LIGHT, property="light", features=[])
        assert not _flatten_expose(expose)


# =============================================================================
# _map_leaf_feature
# =============================================================================


class TestMapLeafFeature:
    def test_no_property_returns_empty(self):
        assert not _map_leaf_feature(make_expose(property=""))

    def test_unknown_type_returns_empty(self):
        assert not _map_leaf_feature(make_expose(type="weird_type", property="x"))

    def test_numeric_known_property_gets_typed_control(self):
        [(_, meta)] = _map_leaf_feature(make_expose(type=ExposeType.NUMERIC, property="temperature"))
        assert meta.type == WbControlType.TEMPERATURE

    def test_numeric_unknown_property_falls_back_to_value(self):
        [(_, meta)] = _map_leaf_feature(make_expose(type=ExposeType.NUMERIC, property="linkquality"))
        assert meta.type == WbControlType.VALUE

    def test_writable_value_with_min_max_promoted_to_range(self):
        [(_, meta)] = _map_leaf_feature(
            make_expose(
                type=ExposeType.NUMERIC,
                property="brightness",
                access=WRITABLE,
                value_min=0,
                value_max=254,
            )
        )
        assert meta.type == WbControlType.RANGE
        assert meta.min == 0
        assert meta.max == 254
        assert meta.readonly is False

    def test_writable_value_without_min_stays_value(self):
        [(_, meta)] = _map_leaf_feature(
            make_expose(
                type=ExposeType.NUMERIC,
                property="brightness",
                access=WRITABLE,
                value_max=254,
            )
        )
        assert meta.type == WbControlType.VALUE

    def test_writable_value_without_max_stays_value(self):
        [(_, meta)] = _map_leaf_feature(
            make_expose(
                type=ExposeType.NUMERIC,
                property="brightness",
                access=WRITABLE,
                value_min=0,
            )
        )
        assert meta.type == WbControlType.VALUE

    def test_readonly_value_with_min_max_stays_value(self):
        [(_, meta)] = _map_leaf_feature(
            make_expose(
                type=ExposeType.NUMERIC,
                property="linkquality",
                value_min=0,
                value_max=255,
            )
        )
        assert meta.type == WbControlType.VALUE

    def test_writable_typed_numeric_is_not_promoted_to_range(self):
        # Promotion is VALUE → RANGE only. Typed controls (temperature, etc.)
        # keep their original type even when writable with min/max.
        [(_, meta)] = _map_leaf_feature(
            make_expose(
                type=ExposeType.NUMERIC,
                property="temperature",
                access=WRITABLE,
                value_min=0,
                value_max=40,
            )
        )
        assert meta.type == WbControlType.TEMPERATURE

    def test_binary_becomes_switch_with_value_on_off(self):
        [(_, meta)] = _map_leaf_feature(
            make_expose(
                type=ExposeType.BINARY,
                property="occupancy",
                value_on="true",
                value_off="false",
            )
        )
        assert meta.type == WbControlType.SWITCH
        assert meta.value_on == "true"
        assert meta.value_off == "false"

    def test_enum_becomes_text_with_enum_dict(self):
        [(_, meta)] = _map_leaf_feature(
            make_expose(type=ExposeType.ENUM, property="mode", values=["off", "heat", "cool"])
        )
        assert meta.type == WbControlType.TEXT
        assert meta.enum == {"off": 0, "heat": 1, "cool": 2}

    def test_text_becomes_text_without_enum(self):
        [(_, meta)] = _map_leaf_feature(make_expose(type=ExposeType.TEXT, property="description"))
        assert meta.type == WbControlType.TEXT
        assert meta.enum is None

    def test_readonly_reflects_access(self):
        ro = make_expose(type=ExposeType.NUMERIC, property="temperature", access=READABLE)
        rw = make_expose(type=ExposeType.NUMERIC, property="temperature", access=WRITABLE)
        [(_, ro_meta)] = _map_leaf_feature(ro)
        [(_, rw_meta)] = _map_leaf_feature(rw)
        assert ro_meta.readonly is True
        assert rw_meta.readonly is False

    def test_title_derived_from_property(self):
        [(_, meta)] = _map_leaf_feature(make_expose(type=ExposeType.NUMERIC, property="noise_detect_level"))
        assert meta.title == {"en": "Noise detect level"}


# =============================================================================
# _map_color_feature
# =============================================================================


class TestMapColorFeature:
    def test_readonly_when_no_writable_subfeatures(self):
        [(_, meta)] = _map_color_feature(
            make_expose(
                type=ExposeType.COMPOSITE,
                property="color",
                features=[make_expose(property="x"), make_expose(property="y")],
            )
        )
        assert meta.type == WbControlType.RGB
        assert meta.readonly is True

    def test_writable_when_any_subfeature_writable(self):
        [(_, meta)] = _map_color_feature(
            make_expose(
                type=ExposeType.COMPOSITE,
                property="color",
                features=[
                    make_expose(property="hue", access=WRITABLE),
                    make_expose(property="saturation"),
                ],
            )
        )
        assert meta.readonly is False

    def test_empty_features_is_readonly(self):
        [(_, meta)] = _map_color_feature(
            make_expose(type=ExposeType.COMPOSITE, property="color", features=[])
        )
        assert meta.readonly is True

    def test_title_has_ru_translation(self):
        [(_, meta)] = _map_color_feature(
            make_expose(type=ExposeType.COMPOSITE, property="color", features=[])
        )
        assert meta.title == {"en": "Color", "ru": "Цвет"}


# =============================================================================
# Helpers
# =============================================================================


class TestMakeEnum:
    def test_values_mapped_to_sequential_indices(self):
        assert _make_enum(make_expose(values=["off", "low", "high"])) == {
            "off": 0,
            "low": 1,
            "high": 2,
        }

    def test_empty_values_returns_none(self):
        assert _make_enum(make_expose(values=[])) is None


class TestMakeTitle:
    @pytest.mark.parametrize(
        "prop, expected",
        [
            ("temperature", "Temperature"),
            ("noise_detect_level", "Noise detect level"),
            ("x", "X"),
        ],
    )
    def test_snake_to_title(self, prop, expected):
        assert _make_title(prop) == expected


class TestResolveWbType:
    def test_numeric_known_property(self):
        assert (
            _resolve_wb_type(make_expose(type=ExposeType.NUMERIC, property="humidity"))
            == WbControlType.REL_HUMIDITY
        )

    def test_numeric_unknown_property_falls_back_to_value(self):
        assert (
            _resolve_wb_type(make_expose(type=ExposeType.NUMERIC, property="linkquality"))
            == WbControlType.VALUE
        )

    def test_binary(self):
        assert _resolve_wb_type(make_expose(type=ExposeType.BINARY, property="state")) == WbControlType.SWITCH

    def test_enum(self):
        assert _resolve_wb_type(make_expose(type=ExposeType.ENUM, property="mode")) == WbControlType.TEXT

    def test_text(self):
        assert (
            _resolve_wb_type(make_expose(type=ExposeType.TEXT, property="description")) == WbControlType.TEXT
        )

    def test_unknown_type_returns_none(self):
        assert _resolve_wb_type(make_expose(type="mystery", property="x")) is None
