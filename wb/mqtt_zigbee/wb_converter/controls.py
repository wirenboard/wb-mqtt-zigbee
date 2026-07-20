import colorsys
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, TypedDict

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


class WbControlError:
    """
    WB MQTT Conventions: /meta/error flag characters (combinable, e.g. "rw")
    """

    READ = "r"  # failed to read from device / device reports an error
    WRITE = "w"  # write to device error
    PERIOD = "p"  # read period miss
    READ_WRITE = READ + WRITE  # device fully unreachable: neither read nor write


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
    value_on: Any = None
    value_off: Any = None
    enum: Optional[dict] = None
    min: Optional[float] = None
    max: Optional[float] = None
    # Unit string shown next to the value in the WB UI (e.g. "%", "lx", "s"). Only
    # set for untyped value/range controls; typed controls (temperature, voltage, …)
    # already carry their unit via the WB control type.
    units: str = ""
    # Multiplier applied to numeric z2m values before publishing (and reversed on
    # commands). Used to convert z2m milli-units (mV, mA) to the base SI units the
    # WB voltage/current control types display. 1.0 = no conversion.
    scale: float = 1.0

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
        if self.scale != 1.0 and isinstance(value, (int, float)):
            return _format_number(value * self.scale)
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
        number = _parse_number(wb_value)
        if self.scale != 1.0 and isinstance(number, (int, float)):
            reversed_value = number / self.scale
            return int(reversed_value) if float(reversed_value).is_integer() else reversed_value
        return number


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


def _format_number(value: float) -> str:
    """
    Format a number for a WB control: drop the trailing .0 and binary-float noise.

    Example:
        >>> _format_number(3.0)
        '3'
        >>> _format_number(9 * 0.001)  # would be '0.009000000000000001' without rounding
        '0.009'
    """
    # 3 decimals: the only scaling is milli -> base unit (÷1000), so thousandths are
    # the finest meaningful precision. Rounding here also strips float noise such as
    # 9 * 0.001 == 0.009000000000000001.
    rounded = round(value, 3)
    return str(int(rounded)) if float(rounded).is_integer() else str(rounded)


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
        title={"en": "Permit Join", "ru": "Разрешить подключение"},
    ),
    BridgeControl.DEVICE_COUNT: ControlMeta(
        type=WbControlType.VALUE,
        readonly=True,
        order=4,
        title={"en": "Device Count", "ru": "Количество устройств"},
    ),
    BridgeControl.LAST_JOINED: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=5,
        title={"en": "Last Joined", "ru": "Последнее сопряженное"},
    ),
    BridgeControl.LAST_LEFT: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=6,
        title={"en": "Last Left", "ru": "Последнее вышедшее из сети"},
    ),
    BridgeControl.LAST_REMOVED: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=7,
        title={"en": "Last Removed", "ru": "Последнее удаленное"},
    ),
    BridgeControl.UPDATE_DEVICES: ControlMeta(
        type=WbControlType.PUSHBUTTON,
        readonly=False,
        order=8,
        title={"en": "Refresh Device List", "ru": "Обновить список"},
    ),
    BridgeControl.LAST_SEEN: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=9,
        title={"en": "Last Seen", "ru": "Последняя активность"},
    ),
    BridgeControl.MESSAGES_RECEIVED: ControlMeta(
        type=WbControlType.VALUE,
        readonly=True,
        order=10,
        title={"en": "Messages Received", "ru": "Сообщений получено"},
    ),
    BridgeControl.LOG_LEVEL: ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=11,
        title={"en": "Log Level", "ru": "Уровень логов"},
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
