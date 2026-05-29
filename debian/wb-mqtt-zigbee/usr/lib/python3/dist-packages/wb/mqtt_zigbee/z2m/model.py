from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BridgeInfo:
    """Parsed bridge/info message from zigbee2mqtt"""

    version: str
    permit_join: bool
    permit_join_end: Optional[int]


class ExposeProperty:
    """Common zigbee2mqtt expose property names"""

    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    PRESSURE = "pressure"
    CO2 = "co2"
    NOISE = "noise"
    POWER = "power"
    VOLTAGE = "voltage"
    CURRENT = "current"
    ENERGY = "energy"
    BATTERY = "battery"
    LINKQUALITY = "linkquality"
    LOCAL_TEMPERATURE = "local_temperature"
    ILLUMINANCE = "illuminance"
    ILLUMINANCE_LUX = "illuminance_lux"
    OCCUPANCY = "occupancy"
    STATE = "state"
    BRIGHTNESS = "brightness"
    COLOR_TEMP = "color_temp"


class ExposeType:
    """Zigbee2mqtt expose type identifiers"""

    NUMERIC = "numeric"
    BINARY = "binary"
    ENUM = "enum"
    TEXT = "text"
    LIGHT = "light"
    SWITCH = "switch"
    LOCK = "lock"
    CLIMATE = "climate"
    FAN = "fan"
    COVER = "cover"
    COMPOSITE = "composite"


class ExposeAccess:
    """Bitmask constants for zigbee2mqtt expose access flags"""

    READ = 0b001
    WRITE = 0b010
    GET = 0b100


@dataclass
class ExposeFeature:
    """Single expose feature from zigbee2mqtt device definition.

    Represents a device capability (sensor value, switch, etc.).
    May contain nested features for composite types (light, climate, etc.).
    """

    type: str
    name: str
    property: str
    access: int = 0
    unit: str = ""
    value_min: Optional[float] = None
    value_max: Optional[float] = None
    value_on: Optional[str] = None
    value_off: Optional[str] = None
    values: list[str] = field(default_factory=list)
    features: list["ExposeFeature"] = field(default_factory=list)

    @property
    def is_writable(self) -> bool:
        return bool(self.access & ExposeAccess.WRITE)

    @staticmethod
    def from_dict(data: dict) -> "ExposeFeature":
        return ExposeFeature(
            type=data.get("type", ""),
            name=data.get("name", ""),
            property=data.get("property", ""),
            access=data.get("access", 0),
            unit=data.get("unit", ""),
            value_min=data.get("value_min"),
            value_max=data.get("value_max"),
            value_on=_str_or_none(data.get("value_on")),
            value_off=_str_or_none(data.get("value_off")),
            values=data.get("values", []),
            features=[ExposeFeature.from_dict(feat) for feat in data.get("features", [])],
        )


@dataclass
class Z2MDevice:
    """Zigbee device parsed from bridge/devices topic.

    Fields model, vendor, description are extracted from the nested 'definition' object.
    """

    ieee_address: str
    friendly_name: str
    type: str
    model: str = ""
    vendor: str = ""
    description: str = ""
    exposes: list[ExposeFeature] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict) -> "Z2MDevice":
        definition = data.get("definition") or {}
        return Z2MDevice(
            ieee_address=data.get("ieee_address", ""),
            friendly_name=data.get("friendly_name", ""),
            type=data.get("type", ""),
            model=definition.get("model", ""),
            vendor=definition.get("vendor", ""),
            description=definition.get("description", ""),
            exposes=[ExposeFeature.from_dict(exp) for exp in definition.get("exposes", [])],
        )


def _str_or_none(value: object) -> Optional[str]:
    if value is None:
        return None
    return str(value)


class BridgeState:
    """Possible values of the bridge/state topic"""

    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class DeviceAvailability:
    """Possible values of the device availability state"""

    ONLINE = "online"
    OFFLINE = "offline"


class Z2MEventType:
    """Event types from zigbee2mqtt bridge/event topic"""

    DEVICE_JOINED = "device_joined"
    DEVICE_LEAVE = "device_leave"
    DEVICE_RENAMED = "device_renamed"


class DeviceEventType:
    """Internal event types used in DeviceEvent (mapped from Z2MEventType)"""

    JOINED = "joined"
    LEFT = "left"
    REMOVED = "removed"
    RENAMED = "renamed"


@dataclass
class DeviceEvent:
    """Device join/leave/remove/rename event for forwarding to WB bridge controls"""

    type: str
    name: str
    old_name: str = ""


class BridgeLogLevel:
    """Log levels from zigbee2mqtt bridge/logging topic with severity ranking"""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    RANK = {DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3}
