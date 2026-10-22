import copy
from dataclasses import dataclass, field
from typing import Any, Collection, Iterator, Optional

from .controls import ControlMeta, ServiceControl

# Keys handled separately from control values in z2m state messages
_NON_CONTROL_KEYS = (ServiceControl.LAST_SEEN, "update")

# z2m gives up reading a device after 10 s, so an unanswered /get is repeated on a later edit
REQUEST_RETRY_SEC = 30.0


@dataclass
class Command:
    """Outcome of a WB command: a /set payload to send and/or a composite to read via /get."""

    payload: Optional[dict[str, Any]] = None
    request: Optional[str] = None


@dataclass
class CompositeState:
    """Composite values of one device in z2m form, with local edits not sent yet."""

    # Values received from the device with local edits merged in: {"cover_mode": {"led": True}}
    values: dict[str, Any] = field(default_factory=dict)
    # Composites whose object was received from the device at least once
    received: set[str] = field(default_factory=set)
    # Field control ids edited in WB and not sent yet
    edits: set[str] = field(default_factory=set)
    # Composites to send as soon as their object is received, with the time of their /get
    send_on_receive: set[str] = field(default_factory=set)
    requested: dict[str, float] = field(default_factory=dict)

    def state_values(
        self, controls: dict[str, ControlMeta], state: dict[str, Any], pending: Collection[str] = ()
    ) -> Iterator[tuple[str, ControlMeta, Any]]:
        """Yield (id, meta, value) for controls in a z2m state message, except buttons and unsent edits.
        Values of `pending` ids (a command in flight) are yielded but not stored."""
        keep = set(self.edits) | set(pending)
        for prop in {meta.path[0] for meta in controls.values() if meta.path}:
            if isinstance(state.get(prop), dict):
                self._receive(prop, state[prop], controls, keep)
        for control_id, meta in controls.items():
            if control_id in _NON_CONTROL_KEYS or control_id in self.edits or meta.is_send_button:
                continue
            found, value = _get_path(state, meta.path or (control_id,))
            if not found and meta.path and control_id == meta.path[-1]:
                # Some legacy converters publish composite fields top-level (Lidl TRV away_setting).
                value = state.get(control_id)
                found = control_id in state and not isinstance(value, dict)
            if found:
                yield control_id, meta, value

    def observe(self, meta: ControlMeta, z2m_value: Any) -> None:
        """Store a composite field value received from the device."""
        if meta.path:
            _set_path(self.values, meta.path, z2m_value)

    def _receive(
        self, prop: str, received: dict[str, Any], controls: dict[str, ControlMeta], keep: set[str]
    ) -> None:
        """Store a composite object as the device sent it, keeping the fields in `keep`."""
        edited = {
            controls[cid].path[1:] for cid in keep if cid in controls and controls[cid].path[:1] == (prop,)
        }
        kept = {path: _get_path(self.values.get(prop), path) for path in edited}
        # A copy: the kept fields must not leak into the state message being read
        self.values[prop] = copy.deepcopy(received)
        for path, (found, value) in kept.items():
            if found:
                _set_path(self.values, (prop, *path), value)
        self.received.add(prop)

    def ready_payloads(self, controls: dict[str, ControlMeta]) -> list[dict[str, Any]]:
        """Return payloads of composites that waited for their object and have received it."""
        ready = [prop for prop in self.send_on_receive if prop in self.received]
        self.send_on_receive.difference_update(ready)
        for prop in ready:
            self.requested.pop(prop, None)
        return [self._send(prop, controls) for prop in ready]

    def edit(
        self,
        control_id: str,
        meta: ControlMeta,
        wb_value: str,
        controls: dict[str, ControlMeta],
        now: float = 0.0,
    ) -> Command:
        """Apply a WB command to a composite field or send button and tell what to do with it."""
        if meta.is_send_button:
            # No /get first: the fields are not readable, so a read may never return the object.
            prop = meta.path[0]
            return Command(payload=self._send(prop, controls)) if self.values.get(prop) else Command()
        z2m_value = meta.parse_wb_value(wb_value)
        if not meta.path:
            return Command(payload={control_id: z2m_value})
        _set_path(self.values, meta.path, z2m_value)
        self.edits.add(control_id)
        prop = meta.path[0]
        if meta.deferred:
            return Command()
        if prop not in self.received:
            if prop in self.send_on_receive and now - self.requested[prop] < REQUEST_RETRY_SEC:
                return Command()
            self.send_on_receive.add(prop)
            self.requested[prop] = now
            return Command(request=prop)
        return Command(payload=self._send(prop, controls))

    def wb_values(self, controls: dict[str, ControlMeta]) -> dict[str, str]:
        """Return known composite field values formatted for WB."""
        result = {}
        for control_id, meta in controls.items():
            if meta.is_composite_field:
                found, value = _get_path(self.values, meta.path)
                if found:
                    result[control_id] = meta.format_value(value)
        return result

    def _send(self, prop: str, controls: dict[str, ControlMeta]) -> dict[str, Any]:
        """Build the whole-object payload of a composite and mark its edits as sent."""
        self.edits = {cid for cid in self.edits if controls[cid].path[0] != prop}
        return {prop: self.values[prop]}


def _get_path(data: Any, path: tuple[str, ...]) -> tuple[bool, Any]:
    """Return (found, value) for a nested key path."""
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return False, None
        data = data[key]
    return True, data


def _set_path(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """Set a value at a nested key path, replacing non-dict intermediate values."""
    for key in path[:-1]:
        if not isinstance(data.get(key), dict):
            data[key] = {}
        data = data[key]
    data[path[-1]] = value
