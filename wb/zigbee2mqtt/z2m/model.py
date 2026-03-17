from dataclasses import dataclass
from typing import Optional


@dataclass
class BridgeInfo:
    version: str
    permit_join: bool
    permit_join_end: Optional[int]


class BridgeState:
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class Z2MEventType:
    DEVICE_JOINED = "device_joined"
    DEVICE_LEAVE = "device_leave"


class DeviceEventType:
    JOINED = "joined"
    LEFT = "left"
    REMOVED = "removed"


@dataclass
class DeviceEvent:
    type: str
    name: str


class BridgeLogLevel:
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    RANK = {DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3}
