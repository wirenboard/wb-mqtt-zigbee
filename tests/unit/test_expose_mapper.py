"""Unit tests for wb.mqtt_zigbee.wb_converter.expose_mapper."""

# pylint: disable=too-many-arguments,too-many-positional-arguments,redefined-builtin,too-few-public-methods

from typing import Optional

import pytest

from wb.mqtt_zigbee.wb_converter.controls import WbControlType
from wb.mqtt_zigbee.wb_converter.expose_mapper import (
    PHASE_SUFFIX_RE,
    _flatten_expose,
    _localized_title,
    _make_enum,
    _make_title,
    _map_color_feature,
    _map_leaf_feature,
    _resolve_wb_type,
    map_exposes_to_controls,
)
from wb.mqtt_zigbee.wb_converter.translations import ENUM_VALUE_TITLES, PROPERTY_TITLES
from wb.mqtt_zigbee.z2m.model import ExposeAccess, ExposeFeature, ExposeType

READABLE = ExposeAccess.READ  # 0b001
WRITABLE = ExposeAccess.READ | ExposeAccess.WRITE  # 0b011


def make_expose(
    type: str = ExposeType.NUMERIC,
    name: str = "",
    property: str = "",
    access: int = READABLE,
    unit: str = "",
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
        unit=unit,
        value_min=value_min,
        value_max=value_max,
        value_on=value_on,
        value_off=value_off,
        values=values if values is not None else [],
        features=features if features is not None else [],
    )


class TestMapExposesToControls:
    """Tests for ``map_exposes_to_controls`` — the public mapping API."""

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

    def test_model_added_when_non_empty(self):
        controls = map_exposes_to_controls([], model="WB-MSW-ZIGBEE v.4")
        assert "model" in controls
        assert controls["model"].type == WbControlType.TEXT
        assert controls["model"].readonly is True
        assert controls["model"].title == {"en": "Model", "ru": "Модель"}

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

    def test_numbered_endpoint_inherits_base_title_and_enum_labels(self):
        """A numbered endpoint takes both the title and the value labels of its base"""
        controls = map_exposes_to_controls(
            [
                make_expose(type=ExposeType.ENUM, property="switch_type_1", values=["rocker"]),
                make_expose(type=ExposeType.ENUM, property="power_type", values=["full"]),
            ]
        )

        assert controls["switch_type_1"].title == {"en": "Switch Type 1", "ru": "Тип выключателя 1"}
        assert controls["switch_type_1"].enum == {"rocker": {"en": "Rocker", "ru": "Клавишный"}}
        assert controls["power_type"].title == {"en": "Power Type", "ru": "Питание"}
        assert controls["power_type"].enum == {"full": {"en": "Full", "ru": "Полное"}}

    def test_expose_without_property_does_not_break_order(self):
        exposes = [
            make_expose(property=""),  # skipped — no property
            make_expose(property="temperature"),
        ]
        controls = map_exposes_to_controls(exposes)
        assert controls["temperature"].order == 1
        assert controls["available"].order == 2
        assert controls["last_seen"].order == 3


class TestFlattenExpose:
    """Tests for ``_flatten_expose`` — recursive expansion of composite exposes."""

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


class TestMapLeafFeature:
    """Tests for ``_map_leaf_feature`` — conversion of a single leaf expose into a control."""

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

    def test_voltage_in_millivolts_is_scaled_to_volts(self):
        [(_, meta)] = _map_leaf_feature(make_expose(type=ExposeType.NUMERIC, property="voltage", unit="mV"))
        assert meta.type == WbControlType.VOLTAGE
        assert meta.scale == 0.001
        # 3000 mV → 3 V, 2700 mV → 2.7 V
        assert meta.format_value(3000) == "3"
        assert meta.format_value(2700) == "2.7"

    def test_voltage_in_volts_is_not_scaled(self):
        [(_, meta)] = _map_leaf_feature(make_expose(type=ExposeType.NUMERIC, property="voltage", unit="V"))
        assert meta.type == WbControlType.VOLTAGE
        assert meta.scale == 1.0
        assert meta.format_value(230) == "230"

    def test_current_in_milliamps_is_scaled_to_amps(self):
        [(_, meta)] = _map_leaf_feature(make_expose(type=ExposeType.NUMERIC, property="current", unit="mA"))
        assert meta.type == WbControlType.CURRENT
        assert meta.scale == 0.001
        assert meta.format_value(500) == "0.5"

    def test_value_control_carries_z2m_unit(self):
        # battery is an untyped value control → z2m's "%" unit is passed through.
        [(_, meta)] = _map_leaf_feature(make_expose(type=ExposeType.NUMERIC, property="battery", unit="%"))
        assert meta.type == WbControlType.VALUE
        assert meta.units == "%"

    def test_typed_control_does_not_carry_z2m_unit(self):
        # temperature is a typed control → unit comes from the WB type, not z2m.
        [(_, meta)] = _map_leaf_feature(
            make_expose(type=ExposeType.NUMERIC, property="temperature", unit="°C")
        )
        assert meta.type == WbControlType.TEMPERATURE
        assert meta.units == ""

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
        """
        An uncurated enum still lists every value, with en-only labels
        """
        [(_, meta)] = _map_leaf_feature(
            make_expose(type=ExposeType.ENUM, property="vendor_knob", values=["off", "heat", "cool"])
        )
        assert meta.type == WbControlType.TEXT
        # Single-token values keep zigbee2mqtt's own wording.
        assert meta.enum == {
            "off": {"en": "off"},
            "heat": {"en": "heat"},
            "cool": {"en": "cool"},
        }

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
        [(_, meta)] = _map_leaf_feature(
            make_expose(type=ExposeType.NUMERIC, property="totally_unknown_property")
        )
        assert meta.title == {"en": "Totally Unknown Property"}

    def test_known_property_gets_bilingual_title(self):
        [(_, meta)] = _map_leaf_feature(make_expose(type=ExposeType.NUMERIC, property="temperature"))
        assert meta.title == {"en": "Temperature", "ru": "Температура"}

    def test_phase_endpoint_property_gets_composed_bilingual_title(self):
        [(_, meta)] = _map_leaf_feature(make_expose(type=ExposeType.NUMERIC, property="power_l1"))
        assert meta.title == {"en": "Power L1", "ru": "Мощность L1"}


class TestMapColorFeature:
    """Tests for ``_map_color_feature`` — special handling of composite color exposes."""

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


class TestMakeEnum:
    """
    Tests for helper ``_make_enum``. The key is the control value itself — that is what
    a command must carry back.
    """

    def test_curated_values_translated_uncurated_fall_back_to_english(self):
        # A missing "ru" is deliberate: the web interface falls back to "en".
        assert _make_enum(make_expose(property="switch_type", values=["rocker", "wombat"])) == {
            "rocker": {"en": "Rocker", "ru": "Клавишный"},
            "wombat": {"en": "wombat"},
        }

    def test_multiword_uncurated_value_is_title_cased(self):
        assert _make_enum(make_expose(property="x", values=["battery_full"])) == {
            "battery_full": {"en": "Battery Full"}
        }

    @pytest.mark.parametrize(
        "value",
        [
            "usb",  # capitalize() would give "Usb"
            "heat",
            "ON",
            "2000K",
            "on_",  # title-casing leaves a dangling space
        ],
    )
    def test_values_are_kept_verbatim(self, value):
        assert _make_enum(make_expose(property="x", values=[value])) == {value: {"en": value}}

    def test_endpoint_suffix_reuses_base_property(self):
        """switch_type_1 must get switch_type's labels"""
        assert _make_enum(make_expose(property="switch_type_1", values=["rocker"])) == _make_enum(
            make_expose(property="switch_type", values=["rocker"])
        )

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("on_1", {"en": "On 1", "ru": "Включение 1"}),
            ("brightness_stop_l2", {"en": "Brightness Stop L2", "ru": "Остановка изменения яркости L2"}),
        ],
    )
    def test_button_index_is_composed_from_the_base_value(self, value, expected):
        """Multi-gang devices number the value itself, not just the property"""
        assert _make_enum(make_expose(property="action", values=[value])) == {value: expected}

    def test_curated_value_wins_over_composing(self, monkeypatch):
        """A curated label must survive even when the base plus index would differ"""
        monkeypatch.setitem(
            ENUM_VALUE_TITLES,
            "probe",
            {"on": {"en": "On", "ru": "Включение"}, "on_1": {"en": "First", "ru": "Первая клавиша"}},
        )
        assert _make_enum(make_expose(property="probe", values=["on_1"])) == {
            "on_1": {"en": "First", "ru": "Первая клавиша"}
        }

    def test_numeric_values_are_stringified(self):
        """A str method on a numeric value would raise and drop the whole device"""
        assert _make_enum(make_expose(property="melody", values=[1, 2])) == {
            "1": {"en": "1"},
            "2": {"en": "2"},
        }

    def test_returned_labels_are_copies(self):
        enum = _make_enum(make_expose(property="switch_type", values=["rocker"]))
        enum["rocker"]["ru"] = "испорчено"
        assert ENUM_VALUE_TITLES["switch_type"]["rocker"]["ru"] == "Клавишный"

    def test_empty_values_returns_none(self):
        assert _make_enum(make_expose(values=[])) is None


class TestEnumValueTitlesTable:
    """Structural invariants of ENUM_VALUE_TITLES — cheap guards as the table grows"""

    def test_table_is_well_formed(self):
        for prop, values in ENUM_VALUE_TITLES.items():
            # An endpoint variant would be dead: it resolves through the base entry.
            assert not PHASE_SUFFIX_RE.match(prop), f"{prop} carries an endpoint suffix"
            assert prop in PROPERTY_TITLES, f"{prop} has value labels but no control title"
            for value, label in values.items():
                assert value, f"{prop} has an empty value key"
                assert label.get("en"), f"{prop}.{value} has no English label"
                # A typo'd language key would silently publish an untranslated label.
                assert set(label) <= {"en", "ru"}, f"{prop}.{value} has an unexpected language"
                assert all(text.strip() for text in label.values()), f"{prop}.{value} has a blank label"


class TestMakeTitle:
    """Tests for helper ``_make_title`` — pretty-printing snake_case property names."""

    @pytest.mark.parametrize(
        "prop, expected",
        [
            ("temperature", "Temperature"),
            ("noise_detect_level", "Noise Detect Level"),
            ("x", "X"),
        ],
    )
    def test_snake_to_title(self, prop, expected):
        assert _make_title(prop) == expected


class TestLocalizedTitle:
    """Tests for helper ``_localized_title`` — bilingual title resolution."""

    @pytest.mark.parametrize(
        "prop, expected",
        [
            # Exact matches — pins the correct ru wording, including tricky cases.
            # EN titles follow the WB style guide: every word capitalized.
            ("power", {"en": "Power", "ru": "Мощность"}),
            ("noise", {"en": "Noise", "ru": "Шум"}),
            ("pm25", {"en": "PM2.5", "ru": "PM2.5"}),
            ("temperature", {"en": "Temperature", "ru": "Температура"}),
            # Abbreviations are not translated — left as-is in both languages.
            ("voc", {"en": "VOC", "ru": "VOC"}),
            ("tvoc", {"en": "TVOC", "ru": "TVOC"}),
            ("co2", {"en": "CO2", "ru": "CO2"}),
            ("uv_index", {"en": "UV Index", "ru": "UV-индекс"}),
            # Apparent power — "Полная мощность" matches WB meter templates (e.g. milur total_power) and ГОСТ.
            ("power_apparent", {"en": "Apparent Power", "ru": "Полная мощность"}),
            # WB-MSW-ZIGBEE specific exposes (added after on-bench review).
            ("noise_detect_level", {"en": "Noise Detection Level", "ru": "Порог обнаружения шума"}),
            ("noise_timeout", {"en": "Noise Timeout", "ru": "Таймаут шума"}),
            ("occupancy_level", {"en": "Occupancy Level", "ru": "Уровень присутствия"}),
            (
                "occupancy_sensitivity",
                {"en": "Occupancy Sensitivity", "ru": "Чувствительность к присутствию"},
            ),
            ("temperature_offset", {"en": "Temperature Offset", "ru": "Смещение температуры"}),
            ("th_heater", {"en": "T/H Heater", "ru": "Нагрев датчика T/H"}),
            ("uart_baud_rate", {"en": "UART Baud Rate", "ru": "Скорость UART"}),
            ("uart_connection", {"en": "UART Connection", "ru": "Связь по UART"}),
            # "LED" stays Latin (abbreviation); surrounding words are translated.
            ("led_disabled_night", {"en": "Disable LED At Night", "ru": "Отключать LED ночью"}),
            ("activity_led_indicator", {"en": "Activity LED Indicator", "ru": "LED-индикатор активности"}),
            ("co2_autocalibration", {"en": "CO2 Auto-Calibration", "ru": "Автокалибровка CO2"}),
            ("co2_manual_calibration", {"en": "CO2 Manual Calibration", "ru": "Ручная калибровка CO2"}),
            # mmWave presence sensors (Tuya & similar).
            (
                "detection_distance_max",
                {"en": "Maximum Detection Distance", "ru": "Максимальная дистанция обнаружения"},
            ),
            (
                "detection_distance_min",
                {"en": "Minimum Detection Distance", "ru": "Минимальная дистанция обнаружения"},
            ),
            ("target_distance", {"en": "Target Distance", "ru": "Дистанция до цели"}),
            (
                "presence_sensitivity",
                {"en": "Presence Sensitivity", "ru": "Чувствительность к присутствию"},
            ),
            ("indicator", {"en": "Indicator", "ru": "Индикатор"}),
            # Smart RGB lights.
            ("do_not_disturb", {"en": "Do Not Disturb", "ru": "Не беспокоить"}),
            (
                "color_power_on_behavior",
                {"en": "Color Power-On Behavior", "ru": "Поведение цвета при включении"},
            ),
            # Phase-suffixed endpoints composed from the base entry.
            ("power_l1", {"en": "Power L1", "ru": "Мощность L1"}),
            ("voltage_l3", {"en": "Voltage L3", "ru": "Напряжение L3"}),
            ("current_a", {"en": "Current A", "ru": "Ток A"}),
            ("state_l2", {"en": "State L2", "ru": "Состояние L2"}),
            # Bare numeric endpoint index: some converters spell it without the "l".
            ("switch_type_1", {"en": "Switch Type 1", "ru": "Тип выключателя 1"}),
            ("state_1", {"en": "State 1", "ru": "Состояние 1"}),
            ("power_on_behavior_2", {"en": "Power-On Behavior 2", "ru": "Поведение при включении 2"}),
            ("power_type", {"en": "Power Type", "ru": "Питание"}),
        ],
    )
    def test_resolves_to_bilingual_title(self, prop, expected):
        assert _localized_title(prop) == expected

    @pytest.mark.parametrize(
        "prop, expected",
        [
            ("totally_unknown_property", {"en": "Totally Unknown Property"}),
            ("foo_l1", {"en": "Foo L1"}),  # phase suffix, base "foo" not curated
            ("totally_unknown_1", {"en": "Totally Unknown 1"}),  # numeric suffix, base not curated
        ],
    )
    def test_falls_back_to_english_only(self, prop, expected):
        assert _localized_title(prop) == expected


class TestResolveWbType:
    """Tests for helper ``_resolve_wb_type`` — picking WB control type from expose metadata."""

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
