import colorsys
import json
from dataclasses import dataclass, field
from typing import Optional


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
    RGB = "rgb"


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


@dataclass
class ControlMeta:
    """Metadata describing a WB MQTT control (type, readonly, order, title)"""

    type: str
    readonly: bool
    order: Optional[int] = None
    title: dict = field(default_factory=dict)
    value_on: Optional[str] = None
    value_off: Optional[str] = None

    def format_value(self, value: object) -> str:
        """Convert a z2m value to WB control string representation"""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        if self.type == WbControlType.SWITCH and self.value_on is not None:
            return "1" if str(value) == self.value_on else "0"
        if self.type == WbControlType.RGB and isinstance(value, dict):
            return _hs_dict_to_wb_rgb(value)
        if isinstance(value, dict):
            return json.dumps(value)
        return str(value)


def _hs_dict_to_wb_rgb(color: dict) -> str:
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
    hue = float(color.get("hue", 0))
    saturation = float(color.get("saturation", 0))
    r, g, b = colorsys.hsv_to_rgb(hue / 360, saturation / 100, 1.0)
    return f"{round(r * 255)};{round(g * 255)};{round(b * 255)}"


# Control metadata for the zigbee2mqtt bridge virtual device with translations for English and Russian
BRIDGE_CONTROLS: dict[str, ControlMeta] = {
    BridgeControl.STATE: ControlMeta(
        type=WbControlType.TEXT, readonly=True, order=1,
        title={"en": "State", "ru": "Состояние"},
    ),
    BridgeControl.VERSION: ControlMeta(
        type=WbControlType.TEXT, readonly=True, order=2,
        title={"en": "Version", "ru": "Версия"},
    ),
    BridgeControl.PERMIT_JOIN: ControlMeta(
        type=WbControlType.SWITCH, readonly=False, order=3,
        title={"en": "Permit join", "ru": "Разрешить подключение"},
    ),
    BridgeControl.DEVICE_COUNT: ControlMeta(
        type=WbControlType.VALUE, readonly=True, order=4,
        title={"en": "Device count", "ru": "Количество устройств"},
    ),
    BridgeControl.LAST_JOINED: ControlMeta(
        type=WbControlType.TEXT, readonly=True, order=5,
        title={"en": "Last joined", "ru": "Последнее сопряженное"},
    ),
    BridgeControl.LAST_LEFT: ControlMeta(
        type=WbControlType.TEXT, readonly=True, order=6,
        title={"en": "Last left", "ru": "Последнее вышедшее из сети"},
    ),
    BridgeControl.LAST_REMOVED: ControlMeta(
        type=WbControlType.TEXT, readonly=True, order=7,
        title={"en": "Last removed", "ru": "Последнее удаленное"},
    ),
    BridgeControl.UPDATE_DEVICES: ControlMeta(
        type=WbControlType.PUSHBUTTON, readonly=False, order=8,
        title={"en": "Update devices", "ru": "Обновить устройства"},
    ),
    BridgeControl.LAST_SEEN: ControlMeta(
        type=WbControlType.TEXT, readonly=True, order=9,
        title={"en": "Last seen", "ru": "Последняя активность"},
    ),
    BridgeControl.MESSAGES_RECEIVED: ControlMeta(
        type=WbControlType.VALUE, readonly=True, order=10,
        title={"en": "Messages received", "ru": "Сообщений получено"},
    ),
    BridgeControl.LOG_LEVEL: ControlMeta(
        type=WbControlType.TEXT, readonly=True, order=11,
        title={"en": "Log level", "ru": "Уровень логов"},
    ),
    BridgeControl.LOG: ControlMeta(
        type=WbControlType.TEXT, readonly=True, order=12,
        title={"en": "Log", "ru": "Лог"},
    ),
}
