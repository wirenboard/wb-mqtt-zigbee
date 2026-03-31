import colorsys
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)


class HueSaturationColor(TypedDict):
    """Z2M color representation: hue (0-360) and saturation (0-100)"""

    hue: int
    saturation: int


class WbControlType:
    """Wiren Board MQTT Conventions control types"""

    VALUE = "value"
    SWITCH = "switch"
    TEXT = "text"
    PUSHBUTTON = "pushbutton"
    TEMPERATURE = "temperature"
    REL_HUMIDITY = "rel_humidity"
    ATMOSPHERIC_PRESSURE = "atmospheric_pressure"
    CONCENTRATION = "concentration"
    SOUND_LEVEL = "sound_level"
    POWER = "power"
    VOLTAGE = "voltage"
    CURRENT = "current"
    POWER_CONSUMPTION = "power_consumption"
    ILLUMINANCE = "illuminance"
    RANGE = "range"
    RGB = "rgb"


class WbBoolValue:
    """WB MQTT Conventions: boolean values in control topics"""

    TRUE = "1"
    FALSE = "0"


class BridgeControl:
    """Control IDs for the zigbee2mqtt bridge virtual device"""

    STATE = "State"
    VERSION = "Version"
    LOG_LEVEL = "Log level"
    LOG = "Log"
    PERMIT_JOIN = "Permit join"
    UPDATE_DEVICES = "Update devices"
    DEVICE_COUNT = "Device count"
    LAST_JOINED = "Last joined"
    LAST_LEFT = "Last left"
    LAST_REMOVED = "Last removed"
    LAST_SEEN = "Last seen"
    MESSAGES_RECEIVED = "Messages received"
    RECONNECTS = "Reconnects"


@dataclass
class ControlMeta:
    """Metadata describing a WB MQTT control (type, readonly, order, title)"""

    type: str
    readonly: bool
    order: Optional[int] = None
    title: dict = field(default_factory=dict)
    value_on: Optional[str] = None
    value_off: Optional[str] = None
    enum: Optional[dict] = None
    min: Optional[float] = None
    max: Optional[float] = None

    def format_value(self, value: object) -> str:
        """Convert a z2m value to WB control string representation"""
        if value is None:
            return ""
        if isinstance(value, bool):
            return WbBoolValue.TRUE if value else WbBoolValue.FALSE
        if self.type == WbControlType.SWITCH and self.value_on is not None:
            return WbBoolValue.TRUE if str(value) == self.value_on else WbBoolValue.FALSE
        if self.type == WbControlType.RGB and isinstance(value, dict):
            return _hs_dict_to_wb_rgb(value)
        if isinstance(value, dict):
            return json.dumps(value)
        return str(value)

    def parse_wb_value(self, wb_value: str) -> object:
        """Convert a WB control value to z2m format (reverse of format_value)"""
        if self.type == WbControlType.SWITCH:
            if self.value_on is not None:
                return self.value_on if wb_value == WbBoolValue.TRUE else self.value_off
            return wb_value == WbBoolValue.TRUE
        if self.type == WbControlType.RGB:
            return _wb_rgb_to_hs_dict(wb_value)
        if self.type == WbControlType.TEXT:
            return wb_value
        return _parse_number(wb_value)


def _wb_rgb_to_hs_dict(wb_rgb: str) -> HueSaturationColor:
    """Convert WB RGB format "R;G;B" to z2m color dict {"hue": H, "saturation": S}.

    Example:
        >>> _wb_rgb_to_hs_dict("255;0;0")
        {"hue": 0, "saturation": 100}
        >>> _wb_rgb_to_hs_dict("0;0;255")
        {"hue": 240, "saturation": 100}
    """
    try:
        parts = wb_rgb.split(";")
        if len(parts) != 3:
            raise ValueError(f"expected 3 components, got {len(parts)}")
        r, g, b = int(parts[0]) / 255, int(parts[1]) / 255, int(parts[2]) / 255
        h, s, _v = colorsys.rgb_to_hsv(r, g, b)
        return {"hue": round(h * 360), "saturation": round(s * 100)}
    except (ValueError, IndexError):
        logger.warning("Invalid RGB value: '%s'", wb_rgb)
        return {"hue": 0, "saturation": 0}


def _parse_number(value: str) -> object:
    """Parse string as int or float, return original string on failure"""
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except ValueError:
        return value


def _hs_dict_to_wb_rgb(color: HueSaturationColor) -> str:
    """Convert z2m color dict to WB RGB format "R;G;B".

    z2m always provides both representations in the color dict:
        {"hue": 240, "saturation": 100, "x": 0.13, "y": 0.04}

    We use hue (0-360) and saturation (0-100) with value=1.0 (brightness is a separate control).

    Example:
        >>> _hs_dict_to_wb_rgb({"hue": 0, "saturation": 100})
        "255;0;0"
        >>> _hs_dict_to_wb_rgb({"hue": 240, "saturation": 100})
        "0;0;255"
    """
    if "hue" not in color or "saturation" not in color:
        logger.warning("Color dict missing hue/saturation: %s", color)
        return "255;255;255"
    try:
        hue = float(color["hue"])
        saturation = float(color["saturation"])
        r, g, b = colorsys.hsv_to_rgb(hue / 360, saturation / 100, 1.0)
        return f"{round(r * 255)};{round(g * 255)};{round(b * 255)}"
    except (ValueError, TypeError):
        logger.warning("Invalid color values: %s", color)
        return "255;255;255"


# Control metadata for the zigbee2mqtt bridge virtual device with translations for English and Russian
BRIDGE_CONTROLS: dict[str, ControlMeta] = {
    BridgeControl.STATE: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=1,
        title={"en": "State", "ru": "Состояние"},
    ),
    BridgeControl.VERSION: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=2,
        title={"en": "Version", "ru": "Версия"},
    ),
    BridgeControl.PERMIT_JOIN: ControlMeta(
        type=WbControlType.SWITCH,
        readonly=False,
        order=3,
        title={"en": "Permit join", "ru": "Разрешить подключение"},
    ),
    BridgeControl.DEVICE_COUNT: ControlMeta(
        type=WbControlType.VALUE,
        readonly=True,
        order=4,
        title={"en": "Device count", "ru": "Количество устройств"},
    ),
    BridgeControl.LAST_JOINED: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=5,
        title={"en": "Last joined", "ru": "Последнее сопряженное"},
    ),
    BridgeControl.LAST_LEFT: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=6,
        title={"en": "Last left", "ru": "Последнее вышедшее из сети"},
    ),
    BridgeControl.LAST_REMOVED: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=7,
        title={"en": "Last removed", "ru": "Последнее удаленное"},
    ),
    BridgeControl.UPDATE_DEVICES: ControlMeta(
        type=WbControlType.PUSHBUTTON,
        readonly=False,
        order=8,
        title={"en": "Refresh device list", "ru": "Обновить список"},
    ),
    BridgeControl.LAST_SEEN: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=9,
        title={"en": "Last seen", "ru": "Последняя активность"},
    ),
    BridgeControl.MESSAGES_RECEIVED: ControlMeta(
        type=WbControlType.VALUE,
        readonly=True,
        order=10,
        title={"en": "Messages received", "ru": "Сообщений получено"},
    ),
    BridgeControl.LOG_LEVEL: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=11,
        title={"en": "Log level", "ru": "Уровень логов"},
    ),
    BridgeControl.LOG: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=12,
        title={"en": "Log", "ru": "Лог"},
    ),
    BridgeControl.RECONNECTS: ControlMeta(
        type=WbControlType.VALUE,
        readonly=True,
        order=13,
        title={"en": "Reconnects", "ru": "Переподключений"},
    ),
}
