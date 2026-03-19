from dataclasses import dataclass

from .wb_converter.controls import ControlMeta
from .z2m.model import Z2MDevice


@dataclass
class RegisteredDevice:
    """Cached representation of a device registered in WB MQTT"""

    z2m: Z2MDevice
    controls: dict[str, ControlMeta]
    device_id: str
