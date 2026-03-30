import logging
from typing import Optional

from ..z2m.model import ExposeFeature, ExposeProperty, ExposeType
from .controls import ControlMeta, WbControlType

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
SERVICE_CONTROLS = {"available", "device_type", "last_seen"}


def map_exposes_to_controls(exposes: list[ExposeFeature], device_type: str = "") -> dict[str, ControlMeta]:
    """Convert a list of z2m expose features into a flat dict of WB controls.

    Recursively flattens all exposes, deduplicates by property name,
    assigns sequential order, and appends service controls (device_type, last_seen).

    Example:

        exposes = [
            ExposeFeature(type="numeric", name="temperature", property="temperature"),
            ExposeFeature(type="numeric", name="humidity", property="humidity"),
        ]
        controls = map_exposes_to_controls(exposes, device_type="Router")
        # {
        #     "available":    ControlMeta(type="switch", order=1, readonly=True, ...),
        #     "temperature":  ControlMeta(type="temperature", order=2, ...),
        #     "humidity":     ControlMeta(type="rel_humidity", order=3, ...),
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
            title={"en": "Device type", "ru": "Тип устройства"},
        )
        order += 1
    controls["last_seen"] = ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=order,
        title={"en": "Last seen", "ru": "Последняя активность"},
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

    title = _make_title(feature.property)
    enum = _make_enum(feature) if feature.type == ExposeType.ENUM else None
    # Writable numerics with min/max → range (slider), not value (text input)
    if (
        wb_type == WbControlType.VALUE
        and feature.is_writable
        and feature.value_min is not None
        and feature.value_max is not None
    ):
        wb_type = WbControlType.RANGE

    meta = ControlMeta(
        type=wb_type,
        readonly=not feature.is_writable,
        title={"en": title},
        value_on=feature.value_on,
        value_off=feature.value_off,
        enum=enum,
        min=feature.value_min,
        max=feature.value_max,
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
    """Build WB enum dict from z2m enum values: {"off": 0, "on": 1, ...}"""
    if not feature.values:
        return None
    return {val: idx for idx, val in enumerate(feature.values)}


def _make_title(property_name: str) -> str:
    """Convert property name to human-readable title: 'noise_detect_level' → 'Noise detect level'"""
    return property_name.replace("_", " ").capitalize()


def _resolve_wb_type(feature: ExposeFeature) -> Optional[str]:
    if feature.type == ExposeType.NUMERIC:
        return NUMERIC_TYPE_MAP.get(feature.property, WbControlType.VALUE)
    if feature.type == ExposeType.BINARY:
        return WbControlType.SWITCH
    if feature.type in (ExposeType.ENUM, ExposeType.TEXT):
        return WbControlType.TEXT
    logger.warning("Unknown expose type '%s' for property '%s'", feature.type, feature.property)
    return None
