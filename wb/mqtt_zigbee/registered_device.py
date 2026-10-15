from dataclasses import dataclass, field
from typing import Any, Optional

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
    # Last known composite values in z2m form: {"cover_mode": {"reversed": True, ...}}
    composite_values: dict[str, Any] = field(default_factory=dict)
    # Deferred field controls changed in WB and not yet sent by their composite's button
    deferred_edits: set[str] = field(default_factory=set)
    availability_received: bool = False
    # Last availability we published, kept so a rename or device_id change can restore it:
    # the new topics start empty and z2m only republishes availability when it changes.
    # None means we have never heard from the device.
    is_online: Optional[bool] = None
