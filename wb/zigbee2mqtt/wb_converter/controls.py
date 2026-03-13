from dataclasses import dataclass
from typing import Optional


class BridgeControl:
    STATE = "state"
    VERSION = "version"
    LOG_LEVEL = "log_level"
    LOG = "log"
    PERMIT_JOIN = "permit_join"
    UPDATE_DEVICES = "update_devices"


@dataclass
class ControlMeta:
    """Metadata describing a WB MQTT control (type, readonly, title, order)"""

    type: str
    readonly: bool
    title: Optional[str] = None
    order: Optional[int] = None


# Control metadata for the zigbee2mqtt bridge virtual device
BRIDGE_CONTROLS: dict[str, ControlMeta] = {
    BridgeControl.STATE: ControlMeta(type="text", readonly=True, title="State", order=1),
    BridgeControl.VERSION: ControlMeta(type="text", readonly=True, title="Version", order=2),
    BridgeControl.LOG_LEVEL: ControlMeta(type="text", readonly=True, title="Log level", order=3),
    BridgeControl.LOG: ControlMeta(type="text", readonly=True, title="Log", order=4),
    BridgeControl.PERMIT_JOIN: ControlMeta(type="switch", readonly=False, title="Permit join", order=5),
    BridgeControl.UPDATE_DEVICES: ControlMeta(type="pushbutton", readonly=False, title="Update devices", order=6),
}
