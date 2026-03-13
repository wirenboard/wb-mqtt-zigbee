from dataclasses import dataclass
from typing import Optional


class BridgeControl:
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


@dataclass
class ControlMeta:
    """Metadata describing a WB MQTT control (type, readonly, order)"""

    type: str
    readonly: bool
    order: Optional[int] = None


# Control metadata for the zigbee2mqtt bridge virtual device
BRIDGE_CONTROLS: dict[str, ControlMeta] = {
    BridgeControl.STATE: ControlMeta(type="text", readonly=True, order=1),
    BridgeControl.VERSION: ControlMeta(type="text", readonly=True, order=2),
    BridgeControl.LOG_LEVEL: ControlMeta(type="text", readonly=True, order=3),
    BridgeControl.LOG: ControlMeta(type="text", readonly=True, order=4),
    BridgeControl.PERMIT_JOIN: ControlMeta(type="switch", readonly=False, order=5),
    BridgeControl.UPDATE_DEVICES: ControlMeta(type="pushbutton", readonly=False, order=6),
    BridgeControl.DEVICE_COUNT: ControlMeta(type="value", readonly=True, order=7),
    BridgeControl.LAST_JOINED: ControlMeta(type="text", readonly=True, order=8),
    BridgeControl.LAST_LEFT: ControlMeta(type="text", readonly=True, order=9),
    BridgeControl.LAST_REMOVED: ControlMeta(type="text", readonly=True, order=10),
}
