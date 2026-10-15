from typing import Any, Collection, Iterator, Optional

from .controls import ControlMeta, ServiceControl, WbControlType

# Keys handled separately from control values in z2m state messages
_NON_CONTROL_KEYS = (ServiceControl.LAST_SEEN, "update")


def state_values(
    controls: dict[str, ControlMeta], state: dict[str, Any], skip: Collection[str] = ()
) -> Iterator[tuple[str, ControlMeta, Any]]:
    """Yield (id, meta, value) for controls in a z2m state message, except buttons and `skip` ids."""
    for control_id, meta in controls.items():
        if control_id in _NON_CONTROL_KEYS or control_id in skip or meta.type == WbControlType.PUSHBUTTON:
            continue
        found, value = _get_path(state, meta.path or (control_id,))
        if not found and meta.path and control_id == meta.path[-1]:
            # Some legacy converters publish composite fields top-level (Lidl TRV away_setting).
            value = state.get(control_id)
            found = control_id in state and not isinstance(value, dict)
        if found:
            yield control_id, meta, value


def remember(values: dict[str, Any], meta: ControlMeta, z2m_value: Any) -> None:
    """Store a composite field value at its path in the device's composite values."""
    if meta.path:
        _set_path(values, meta.path, z2m_value)


def command_payload(
    control_id: str, meta: ControlMeta, wb_value: str, values: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Return the z2m /set payload for a WB command, or None for a deferred field (only stored).

    A composite field or send button sends the whole composite object from stored values.
    """
    if meta.type == WbControlType.PUSHBUTTON and meta.path:
        return {meta.path[0]: values.get(meta.path[0], {})}
    z2m_value = meta.parse_wb_value(wb_value)
    if not meta.path:
        return {control_id: z2m_value}
    remember(values, meta, z2m_value)
    if meta.deferred:
        return None
    return {meta.path[0]: values[meta.path[0]]}


def stored_wb_values(controls: dict[str, ControlMeta], values: dict[str, Any]) -> dict[str, str]:
    """Return WB values of composite field controls known from stored composite values."""
    result = {}
    for control_id, meta in controls.items():
        if meta.path and meta.type != WbControlType.PUSHBUTTON:
            found, value = _get_path(values, meta.path)
            if found:
                result[control_id] = meta.format_value(value)
    return result


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
