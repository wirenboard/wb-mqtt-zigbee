import logging
import re
from typing import Optional

from ..z2m.model import ExposeFeature, ExposeProperty, ExposeType
from .controls import ControlMeta, WbControlType
from .translations import ENUM_VALUE_TITLES, POWER_SOURCE_LABELS, PROPERTY_TITLES

logger = logging.getLogger(__name__)

# Mapping of z2m property names to WB control types (for numeric exposes)
NUMERIC_TYPE_MAP: dict[str, str] = {
    ExposeProperty.TEMPERATURE: WbControlType.TEMPERATURE,
    ExposeProperty.LOCAL_TEMPERATURE: WbControlType.TEMPERATURE,
    ExposeProperty.HUMIDITY: WbControlType.REL_HUMIDITY,
    ExposeProperty.PRESSURE: WbControlType.ATMOSPHERIC_PRESSURE,
    ExposeProperty.CO2: WbControlType.CONCENTRATION,
    ExposeProperty.NOISE: WbControlType.SOUND_LEVEL,
    ExposeProperty.POWER: WbControlType.POWER,
    ExposeProperty.VOLTAGE: WbControlType.VOLTAGE,
    ExposeProperty.CURRENT: WbControlType.CURRENT,
    ExposeProperty.ENERGY: WbControlType.POWER_CONSUMPTION,
    ExposeProperty.ILLUMINANCE: WbControlType.ILLUMINANCE,
    ExposeProperty.ILLUMINANCE_LUX: WbControlType.ILLUMINANCE,
}

# z2m milli-unit → WB base-unit conversion factors, keyed by (WB control type, z2m unit).
# Battery/diagnostic voltage and current are reported in mV/mA; WB voltage/current
# control types display V/A.
_UNIT_SCALE_TO_BASE: dict[tuple[str, str], float] = {
    (WbControlType.VOLTAGE, "mV"): 0.001,
    (WbControlType.CURRENT, "mA"): 0.001,
}

# Phase/endpoint suffix: power_l1, voltage_a, switch_type_1 — the index comes with or
# without the leading "l". Stripped by _split_endpoint_suffix() to reuse the base entry.
PHASE_SUFFIX_RE = re.compile(r"^(.+)_(l?\d+|[abc])$")

# Specific/composite expose types that contain nested features
NESTED_TYPES = {
    ExposeType.LIGHT,  # dimmable lights, color lights
    ExposeType.SWITCH,  # on/off switches, smart plugs
    ExposeType.LOCK,  # door locks
    ExposeType.CLIMATE,  # thermostats, AC controllers
    ExposeType.FAN,  # fans, ventilation
    ExposeType.COVER,  # blinds, curtains, shutters
    ExposeType.COMPOSITE,  # generic multi-property exposes
}

# Service controls always added by map_exposes_to_controls regardless of exposes
SERVICE_CONTROLS = {"available", "device_type", "model", "power_source", "last_seen"}


def map_exposes_to_controls(
    exposes: list[ExposeFeature], device_type: str = "", power_source: str = "", model: str = ""
) -> dict[str, ControlMeta]:
    """Convert a list of z2m expose features into a flat dict of WB controls.

    Recursively flattens all exposes, deduplicates by property name,
    assigns sequential order, and appends service controls (available, device_type, last_seen).

    Example:

        exposes = [
            ExposeFeature(type="numeric", name="temperature", property="temperature"),
            ExposeFeature(type="numeric", name="humidity", property="humidity"),
        ]
        controls = map_exposes_to_controls(exposes, device_type="Router")
        # {
        #     "temperature":  ControlMeta(type="temperature", order=1, ...),
        #     "humidity":     ControlMeta(type="rel_humidity", order=2, ...),
        #     "available":    ControlMeta(type="switch", order=3, readonly=True, ...),
        #     "device_type":  ControlMeta(type="text", order=4, ...),
        #     "last_seen":    ControlMeta(type="text", order=5, ...),
        # }
    """
    controls: dict[str, ControlMeta] = {}
    order = 1
    for expose in exposes:
        for prop, meta in _flatten_expose(expose):
            if prop not in controls:
                meta.order = order
                controls[prop] = meta
                order += 1
    controls["available"] = ControlMeta(
        type=WbControlType.SWITCH,
        readonly=True,
        order=order,
        title={"en": "Available", "ru": "Доступно"},
    )
    order += 1
    if device_type:
        controls["device_type"] = ControlMeta(
            type=WbControlType.TEXT,
            readonly=True,
            order=order,
            title={"en": "Device Type", "ru": "Тип устройства"},
            enum={
                "Router": {"en": "Router", "ru": "Маршрутизатор"},
                "EndDevice": {"en": "End Device", "ru": "Оконечное устройство"},
                "Coordinator": {"en": "Coordinator", "ru": "Координатор"},
            },
        )
        order += 1
    if model:
        controls["model"] = ControlMeta(
            type=WbControlType.TEXT,
            readonly=True,
            order=order,
            title={"en": "Model", "ru": "Модель"},
        )
        order += 1
    if power_source:
        controls["power_source"] = ControlMeta(
            type=WbControlType.TEXT,
            readonly=True,
            order=order,
            title={"en": "Power Source", "ru": "Тип питания"},
            enum=POWER_SOURCE_LABELS,
        )
        order += 1
    controls["last_seen"] = ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=order,
        title={"en": "Last Seen", "ru": "Последняя активность"},
    )
    return controls


def _flatten_expose(expose: ExposeFeature) -> list[tuple[str, ControlMeta]]:
    """Recursively flatten an expose feature into (property, ControlMeta) pairs.

    Leaf features are mapped directly. Composite types (light, switch, climate, etc.)
    are unwrapped and their nested features are flattened recursively.

    Example:

        # Leaf expose — returned as-is via _map_leaf_feature
        expose = ExposeFeature(type="numeric", name="temperature", property="temperature")
        _flatten_expose(expose)
        # [("temperature", ControlMeta(type="temperature", ...))]

        # Composite expose — nested features are extracted and flattened
        expose = ExposeFeature(type="light", name="light", property="", features=[
            ExposeFeature(type="binary", name="state", property="state",
                          value_on="ON", value_off="OFF"),
            ExposeFeature(type="numeric", name="brightness", property="brightness"),
        ])
        _flatten_expose(expose)
        # [("state", ControlMeta(type="switch", ...)),
        #  ("brightness", ControlMeta(type="value", ...))]
    """
    if expose.type in NESTED_TYPES and expose.features:
        # Composite "color" expose (color_xy/color_hs) → single RGB control
        if expose.type == ExposeType.COMPOSITE and expose.property == "color":
            return _map_color_feature(expose)
        result = []
        for sub in expose.features:
            result.extend(_flatten_expose(sub))
        return result
    return _map_leaf_feature(expose)


def _map_leaf_feature(feature: ExposeFeature) -> list[tuple[str, ControlMeta]]:
    """Map a single leaf ExposeFeature to a (property, ControlMeta) pair.

    Example:

        feature = ExposeFeature(type="numeric", name="temperature", property="temperature")
        result = _map_leaf_feature(feature)
        # [("temperature", ControlMeta(type="temperature", readonly=True, title={"en": "Temperature"}))]

        feature = ExposeFeature(type="binary", name="occupancy", property="occupancy",
                                value_on="true", value_off="false")
        result = _map_leaf_feature(feature)
        # [("occupancy", ControlMeta(type="switch", readonly=True, title={"en": "Occupancy"},
        #                            value_on="true", value_off="false"))]
    """
    if not feature.property:
        return []

    wb_type = _resolve_wb_type(feature)
    if wb_type is None:
        return []

    title = _localized_title(feature.property)
    enum = _make_enum(feature) if feature.type == ExposeType.ENUM else None
    # Writable numerics with min/max → range (slider), not value (text input)
    if (
        wb_type == WbControlType.VALUE
        and feature.is_writable
        and feature.value_min is not None
        and feature.value_max is not None
    ):
        wb_type = WbControlType.RANGE

    # z2m reports some diagnostics in milli-units (battery voltage in mV, etc.); the
    # WB voltage/current control types display base SI units, so scale to V / A.
    scale = _UNIT_SCALE_TO_BASE.get((wb_type, feature.unit), 1.0)

    # Typed controls (temperature, voltage, …) carry their unit via the WB type, so
    # only pass z2m's unit through for untyped value/range controls (battery %, etc.).
    units = feature.unit if wb_type in (WbControlType.VALUE, WbControlType.RANGE) else ""

    meta = ControlMeta(
        type=wb_type,
        readonly=not feature.is_writable,
        title=title,
        value_on=feature.value_on,
        value_off=feature.value_off,
        enum=enum,
        min=feature.value_min * scale if feature.value_min is not None else None,
        max=feature.value_max * scale if feature.value_max is not None else None,
        units=units,
        scale=scale,
    )
    return [(feature.property, meta)]


def _map_color_feature(feature: ExposeFeature) -> list[tuple[str, ControlMeta]]:
    """Map a composite color expose (color_xy or color_hs) to a single RGB control.

    z2m exposes color as composite with property "color" and nested x/y or hue/saturation.
    We map it to a single WB "rgb" control. The state dict key is "color",
    and format_value handles HS→RGB conversion.

    Example:

        feature = ExposeFeature(type="composite", name="color_hs", property="color", features=[
            ExposeFeature(type="numeric", name="hue", property=""),
            ExposeFeature(type="numeric", name="saturation", property=""),
        ])
        _map_color_feature(feature)
        # [("color", ControlMeta(type="rgb", readonly=True, title={"en": "Color"}))]
    """
    writable = any(sub.is_writable for sub in feature.features) if feature.features else False
    meta = ControlMeta(
        type=WbControlType.RGB,
        readonly=not writable,
        title={"en": "Color", "ru": "Цвет"},
    )
    return [(feature.property, meta)]


def _make_enum(feature: ExposeFeature) -> Optional[dict]:
    """
    Build a WB meta.enum from a z2m enum expose.

    Per the WB conventions an enum maps each control value to its translations:
    {"rocker": {"en": "Rocker", "ru": "Клавишный"}, ...}. Uncurated values get an
    en-only label, which the web interface falls back to.
    """
    if not feature.values:
        return None
    labels = _enum_value_titles(feature.property)
    enum: dict[str, dict[str, str]] = {}
    for value in feature.values:
        # Some converters report numeric values; the control value is always a string.
        key = str(value)
        label = labels.get(key)
        # Copy: the tables are shared and must not be mutated through meta.
        enum[key] = dict(label) if label else {"en": _humanize_enum_value(key)}
    return enum


def _enum_value_titles(property_name: str) -> dict[str, dict[str, str]]:
    """
    Curated value labels for a property, falling back to its endpoint base.
    """
    if property_name in ENUM_VALUE_TITLES:
        return ENUM_VALUE_TITLES[property_name]
    base, suffix = _split_endpoint_suffix(property_name)
    return ENUM_VALUE_TITLES.get(base, {}) if suffix else {}


def _humanize_enum_value(value: str) -> str:
    """
    English label for an enum value with no curated translation.

    Only multi-word snake_case is title-cased ("power_outage" -> "Power Outage").
    Anything else is left as z2m wrote it: capitalize() would damage "usb"/"ON"/"2000K",
    and "on_" would title-case into a label with a dangling space.
    """
    parts = value.split("_")
    return _make_title(value) if len(parts) > 1 and value.islower() and all(parts) else value


def _split_endpoint_suffix(property_name: str) -> tuple[str, str]:
    """
    Split a phase/endpoint suffix off a property name.

    'power_l1' -> ('power', 'L1'), 'switch_type_1' -> ('switch_type', '1'),
    'temperature' -> ('temperature', '').
    """
    match = PHASE_SUFFIX_RE.match(property_name)
    return (match.group(1), match.group(2).upper()) if match else (property_name, "")


def _localized_title(property_name: str) -> dict[str, str]:
    """
    Build a bilingual {"en", "ru"} title for a z2m property.

    Resolution order:
      1. exact match in PROPERTY_TITLES;
      2. phase/endpoint-suffixed variant (power_l1, voltage_a, switch_type_1, …) —
         base title + suffix label, e.g. "power_l1" → {"en": "Power L1", "ru": "Мощность L1"}
         and "switch_type_1" → {"en": "Switch Type 1", "ru": "Тип выключателя 1"};
      3. fallback — English-only title mechanically derived from the property name.

    Example:

        _localized_title("temperature")  # {"en": "Temperature", "ru": "Температура"}
        _localized_title("power_l2")      # {"en": "Power L2", "ru": "Мощность L2"}
        _localized_title("some_new_property")  # {"en": "Some New Property"}
    """
    if property_name in PROPERTY_TITLES:
        return dict(PROPERTY_TITLES[property_name])
    base, label = _split_endpoint_suffix(property_name)
    if label and base in PROPERTY_TITLES:
        return {lang: f"{text} {label}" for lang, text in PROPERTY_TITLES[base].items()}
    return {"en": _make_title(property_name)}


def _make_title(property_name: str) -> str:
    """Convert property name to a Title Case title: 'noise_detect_level' → 'Noise Detect Level'.

    Every word is capitalized, per the WB web-interface style guide (English titles
    capitalize each word). This is the en-only fallback for properties not listed
    in PROPERTY_TITLES, so on-the-fly titles follow the same casing as curated ones.
    """
    return " ".join(word.capitalize() for word in property_name.split("_"))


def _resolve_wb_type(feature: ExposeFeature) -> Optional[str]:
    if feature.type == ExposeType.NUMERIC:
        return NUMERIC_TYPE_MAP.get(feature.property, WbControlType.VALUE)
    if feature.type == ExposeType.BINARY:
        return WbControlType.SWITCH
    if feature.type in (ExposeType.ENUM, ExposeType.TEXT):
        return WbControlType.TEXT
    logger.warning("Unknown expose type '%s' for property '%s'", feature.type, feature.property)
    return None
