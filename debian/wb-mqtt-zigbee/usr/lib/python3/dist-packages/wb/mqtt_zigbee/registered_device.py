from dataclasses import dataclass, field

from .wb_converter.controls import ControlMeta
from .z2m.model import Z2MDevice


@dataclass
class PendingCommand:
    """Tracks a recently sent command for debounce/optimistic update."""

    wb_value: str  # WB-formatted value that was published optimistically
    timestamp: float  # time.monotonic() when command was sent


@dataclass
class RegisteredDevice:
    """Cached representation of a device registered in WB MQTT"""

    z2m: Z2MDevice
    controls: dict[str, ControlMeta]
    device_id: str
    pending_commands: dict[str, PendingCommand] = field(default_factory=dict)
    availability_received: bool = False
