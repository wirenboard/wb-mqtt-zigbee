import logging
from typing import Optional

from ..z2m.model import ExposeFeature, ExposeProperty, ExposeType
from .controls import ControlMeta, WbControlType

logger = logging.getLogger(__name__)

# Mapping of z2m property names to WB control types (for numeric exposes)
NUMERIC_TYPE_MAP: dict[str, str] = {
    ExposeProperty.TEMPERATURE: WbControlType.TEMPERATURE,
    ExposeProperty.HUMIDITY: WbControlType.REL_HUMIDITY,
    ExposeProperty.PRESSURE: WbControlType.ATMOSPHERIC_PRESSURE,
    ExposeProperty.CO2: WbControlType.CONCENTRATION,
    ExposeProperty.NOISE: WbControlType.SOUND_LEVEL,
    ExposeProperty.POWER: WbControlType.POWER,
    ExposeProperty.VOLTAGE: WbControlType.VOLTAGE,
    ExposeProperty.CURRENT: WbControlType.CURRENT,
    ExposeProperty.ENERGY: WbControlType.POWER_CONSUMPTION,
    ExposeProperty.ILLUMINANCE_LUX: WbControlType.ILLUMINANCE,
}

# Specific/composite expose types that contain nested features
NESTED_TYPES = {
    ExposeType.LIGHT, ExposeType.SWITCH, ExposeType.LOCK,
    ExposeType.CLIMATE, ExposeType.FAN, ExposeType.COVER, ExposeType.COMPOSITE,
}


def map_exposes_to_controls(exposes: list[ExposeFeature]) -> dict[str, ControlMeta]:
    """Convert a list of z2m expose features into a flat dict of WB controls"""
    controls: dict[str, ControlMeta] = {}
    order = 1
    for expose in exposes:
        for prop, meta in _flatten_expose(expose):
            if prop not in controls:
                meta.order = order
                controls[prop] = meta
                order += 1
    controls["last_seen"] = ControlMeta(
        type=WbControlType.TEXT, readonly=True, order=order,
        title={"en": "Last seen", "ru": "Последняя активность"},
    )
    return controls


def _flatten_expose(expose: ExposeFeature) -> list[tuple[str, ControlMeta]]:
    """Recursively flatten an expose feature into (property, ControlMeta) pairs"""
    if expose.type in NESTED_TYPES and expose.features:
        result = []
        for sub in expose.features:
            result.extend(_flatten_expose(sub))
        return result
    return _map_leaf_feature(expose)


def _map_leaf_feature(feature: ExposeFeature) -> list[tuple[str, ControlMeta]]:
    """Map a single leaf expose feature to a (property, ControlMeta) pair"""
    if not feature.property:
        return []

    wb_type = _resolve_wb_type(feature)
    if wb_type is None:
        return []

    title = _make_title(feature.property)
    meta = ControlMeta(
        type=wb_type, readonly=True,
        title={"en": title},
        value_on=feature.value_on, value_off=feature.value_off,
    )
    return [(feature.property, meta)]


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
