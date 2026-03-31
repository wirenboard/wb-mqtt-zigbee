import logging
import re
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from wb_common.mqtt_client import MQTTClient

from .registered_device import PendingCommand, RegisteredDevice
from .wb_converter.controls import BridgeControl, WbBoolValue
from .wb_converter.expose_mapper import SERVICE_CONTROLS, map_exposes_to_controls
from .wb_converter.publisher import WbMqttDriver
from .z2m.client import Z2MClient
from .z2m.model import (
    BridgeInfo,
    BridgeLogLevel,
    DeviceEvent,
    DeviceEventType,
    Z2MDevice,
)

logger = logging.getLogger(__name__)

_DEVICE_TYPE_RU: dict[str, str] = {
    "Router": "Маршрутизатор",
    "EndDevice": "Оконечное устройство",
    "Coordinator": "Координатор",
}

_EVENT_TYPE_TO_CONTROL = {
    DeviceEventType.JOINED: BridgeControl.LAST_JOINED,
    DeviceEventType.LEFT: BridgeControl.LAST_LEFT,
    DeviceEventType.REMOVED: BridgeControl.LAST_REMOVED,
}


class Bridge:
    """Orchestrates data flow between zigbee2mqtt and the Wiren Board MQTT broker.

    Subscribes to z2m bridge topics, converts events to WB control updates,
    and forwards WB commands back to zigbee2mqtt.
    """

    def __init__(
        self,
        mqtt_client: MQTTClient,
        base_topic: str,
        device_id: str,
        device_name: str,
        bridge_log_min_level: str,
        command_debounce_sec: float = 5.0,
    ) -> None:
        self._z2m = Z2MClient(
            mqtt_client=mqtt_client,
            base_topic=base_topic,
            on_bridge_state=self._on_bridge_state,
            on_bridge_info=self._on_bridge_info,
            on_bridge_log=self._on_bridge_log,
            on_devices=self._on_devices,
            on_device_event=self._on_device_event,
            on_device_state=self._on_device_state,
            on_device_availability=self._on_device_availability,
        )
        self._mqtt_driver = WbMqttDriver(mqtt_client, device_id, device_name)
        self._bridge_log_min_level = bridge_log_min_level
        self._log_min_rank = BridgeLogLevel.RANK.get(
            bridge_log_min_level, BridgeLogLevel.RANK[BridgeLogLevel.WARNING]
        )
        self._command_debounce_sec = command_debounce_sec
        self._messages_received = 0
        self._last_stats_publish = 0.0
        self._known_devices: dict[str, RegisteredDevice] = {}  # friendly_name → RegisteredDevice
        self._ieee_to_name: dict[str, str] = {}  # ieee_address → friendly_name
        self._retained_scan_active = False
        self._reconnect_count = 0

    def subscribe(self) -> None:
        self._mqtt_driver.start_retained_scan()
        self._retained_scan_active = True
        self._publish_bridge()

    def set_all_unavailable(self) -> None:
        """Mark all known devices as offline."""
        if self._known_devices:
            logger.info("Setting %d devices as unavailable", len(self._known_devices))
        for registered in self._known_devices.values():
            self._mqtt_driver.publish_device_control(registered.device_id, "available", WbBoolValue.FALSE)

    def republish(self) -> None:
        self._reconnect_count += 1
        self._publish_bridge()
        self._mqtt_driver.publish_bridge_control(BridgeControl.RECONNECTS, str(self._reconnect_count))
        for friendly_name, registered in self._known_devices.items():
            registered.availability_received = False
            self._mqtt_driver.publish_device(
                registered.device_id,
                friendly_name,
                registered.controls,
                {"available": WbBoolValue.FALSE},
            )
            if registered.z2m.type:
                self._mqtt_driver.publish_device_control(
                    registered.device_id,
                    "device_type",
                    _DEVICE_TYPE_RU.get(registered.z2m.type, registered.z2m.type),
                )
            self._mqtt_driver.subscribe_device_commands(
                registered.device_id,
                registered.controls,
                self._make_device_command_handler(registered),
            )
            self._z2m.subscribe_device(friendly_name)
            self._z2m.request_device_state(friendly_name)
        self._z2m.refresh_device_list()

    def _publish_bridge(self) -> None:
        self._mqtt_driver.publish_bridge_device()
        self._mqtt_driver.publish_bridge_control(BridgeControl.LOG_LEVEL, self._bridge_log_min_level)
        self._z2m.subscribe()
        self._mqtt_driver.subscribe_bridge_commands(
            on_permit_join=self._z2m.set_permit_join,
            on_update_devices=self._z2m.refresh_device_list,
        )

    def _update_stats(self) -> None:
        self._messages_received += 1
        now = time.monotonic()
        if now - self._last_stats_publish < 1.0:
            return
        self._last_stats_publish = now
        self._cleanup_expired_pending(now)
        self._mqtt_driver.publish_bridge_control(
            BridgeControl.MESSAGES_RECEIVED, str(self._messages_received)
        )
        self._mqtt_driver.publish_bridge_control(
            BridgeControl.LAST_SEEN,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def _cleanup_expired_pending(self, now: float) -> None:
        """Remove pending commands that have expired without confirmation."""
        cutoff = now - self._command_debounce_sec
        for registered in self._known_devices.values():
            expired = [k for k, v in registered.pending_commands.items() if v.timestamp < cutoff]
            for key in expired:
                del registered.pending_commands[key]

    def _on_bridge_state(self, state: str) -> None:
        logger.info("Bridge state: %s", state)
        self._mqtt_driver.publish_bridge_control(BridgeControl.STATE, state)
        self._update_stats()

    def _on_bridge_info(self, info: BridgeInfo) -> None:
        logger.info("Bridge info: version=%s, permit_join=%s", info.version, info.permit_join)
        self._mqtt_driver.publish_bridge_control(BridgeControl.VERSION, info.version)
        self._mqtt_driver.publish_bridge_control(
            BridgeControl.PERMIT_JOIN,
            WbBoolValue.TRUE if info.permit_join else WbBoolValue.FALSE,
        )
        self._update_stats()

    def _on_bridge_log(self, level: str, message: str) -> None:
        self._update_stats()
        if BridgeLogLevel.RANK.get(level, 0) >= self._log_min_rank:
            self._mqtt_driver.publish_bridge_control(BridgeControl.LOG, message)

    def _on_devices(self, devices: list[Z2MDevice]) -> None:
        logger.info("Devices: %d", len(devices))
        self._mqtt_driver.publish_bridge_control(BridgeControl.DEVICE_COUNT, str(len(devices)))
        self._update_stats()
        for device in devices:
            self._register_device(device)
        self._remove_stale_devices(devices)
        if self._retained_scan_active:
            self._remove_ghost_devices(devices)
            self._mqtt_driver.stop_retained_scan()
            self._retained_scan_active = False

    def _register_device(self, device: Z2MDevice) -> None:
        if not _is_safe_topic_name(device.friendly_name):
            logger.warning("Device '%s' has unsafe name for MQTT topics, skipping", device.friendly_name)
            return
        if device.friendly_name in self._known_devices:
            self._update_device(device)
            return
        old_name = self._find_old_name(device.ieee_address)
        if old_name is not None:
            self._on_device_renamed(old_name, device.friendly_name)
            return
        if not device.exposes:
            logger.info("Device '%s' has no exposes yet, skipping", device.friendly_name)
            return
        controls = map_exposes_to_controls(device.exposes, device_type=device.type)
        if sum(1 for _control in controls if _control not in SERVICE_CONTROLS) == 0:
            logger.warning("Device '%s' has no mappable exposes, skipping", device.friendly_name)
            return
        device_id = _sanitize_device_id(device.friendly_name)
        registered = RegisteredDevice(z2m=device, controls=controls, device_id=device_id)
        logger.info(
            "Registering device '%s' as '%s' (%d controls)", device.friendly_name, device_id, len(controls)
        )
        self._known_devices[device.friendly_name] = registered
        self._ieee_to_name[device.ieee_address] = device.friendly_name
        self._mqtt_driver.publish_device(
            device_id, device.friendly_name, controls, {"available": WbBoolValue.FALSE}
        )
        if device.type:
            self._mqtt_driver.publish_device_control(
                device_id, "device_type", _DEVICE_TYPE_RU.get(device.type, device.type)
            )
        self._mqtt_driver.subscribe_device_commands(
            device_id,
            controls,
            self._make_device_command_handler(registered),
        )
        self._z2m.subscribe_device(device.friendly_name)
        self._z2m.request_device_state(device.friendly_name)

    def _update_device(self, device: Z2MDevice) -> None:
        """Update metadata and controls for an already-registered device.

        Re-registers controls if exposes have changed (e.g. after firmware update).
        """
        registered = self._known_devices[device.friendly_name]
        if device.type:
            self._mqtt_driver.publish_device_control(
                registered.device_id, "device_type", _DEVICE_TYPE_RU.get(device.type, device.type)
            )
        if device.exposes:
            new_controls = map_exposes_to_controls(device.exposes, device_type=device.type)
            if set(new_controls.keys()) != set(registered.controls.keys()):
                logger.info(
                    "Device '%s' exposes changed (%d → %d controls), re-registering",
                    device.friendly_name,
                    len(registered.controls),
                    len(new_controls),
                )
                self._mqtt_driver.unsubscribe_device_commands(registered.device_id, registered.controls)
                self._mqtt_driver.remove_device(registered.device_id, registered.controls)
                registered.controls = new_controls
                registered.z2m = device
                self._mqtt_driver.publish_device(registered.device_id, device.friendly_name, new_controls)
                self._mqtt_driver.subscribe_device_commands(
                    registered.device_id,
                    new_controls,
                    self._make_device_command_handler(registered),
                )
                self._z2m.request_device_state(device.friendly_name)

    def _on_device_availability(self, friendly_name: str, available: bool) -> None:
        registered = self._known_devices.get(friendly_name)
        if registered is None:
            logger.debug("Availability update for unknown device '%s', skipping", friendly_name)
            return
        registered.availability_received = True
        wb_value = WbBoolValue.TRUE if available else WbBoolValue.FALSE
        self._mqtt_driver.publish_device_control(registered.device_id, "available", wb_value)
        logger.debug("Device availability: %s = %s", friendly_name, "online" if available else "offline")

    def _on_device_state(self, friendly_name: str, state: dict[str, object]) -> None:
        registered = self._known_devices.get(friendly_name)
        if registered is None:
            logger.debug("State update for unknown device '%s', skipping", friendly_name)
            return
        now = time.monotonic()
        for prop, meta in registered.controls.items():
            if prop not in state or prop in ("last_seen", "update"):
                continue
            try:
                wb_value = meta.format_value(state[prop])
            except Exception:  # pylint: disable=broad-except
                logger.warning("Failed to format %s/%s: %r", friendly_name, prop, state[prop])
                continue
            pending = registered.pending_commands.get(prop)
            if pending is not None:
                if wb_value == pending.wb_value:
                    del registered.pending_commands[prop]
                    logger.debug("Command confirmed: %s/%s = %s", friendly_name, prop, wb_value)
                    continue
                if now - pending.timestamp < self._command_debounce_sec:
                    logger.debug(
                        "Suppressing stale state: %s/%s = %s (pending: %s)",
                        friendly_name,
                        prop,
                        wb_value,
                        pending.wb_value,
                    )
                    continue
                del registered.pending_commands[prop]
                logger.debug(
                    "Debounce expired, publishing real value: %s/%s = %s", friendly_name, prop, wb_value
                )
            self._mqtt_driver.publish_device_control(registered.device_id, prop, wb_value)
        if "last_seen" in state:
            formatted = _format_last_seen(state["last_seen"])
            if formatted:
                self._mqtt_driver.publish_device_control(registered.device_id, "last_seen", formatted)
        if not registered.availability_received:
            self._mqtt_driver.publish_device_control(registered.device_id, "available", WbBoolValue.TRUE)
        self._update_stats()

    def _make_device_command_handler(self, registered: RegisteredDevice) -> Callable[[str, str], None]:
        """Create a callback for WB /on commands that forwards them to z2m.

        The closure captures `registered` (same object as in _known_devices),
        so friendly_name stays current after renames.
        """

        def on_command(control_id: str, wb_value: str) -> None:
            meta = registered.controls.get(control_id)
            if meta is None:
                return
            z2m_value = meta.parse_wb_value(wb_value)
            payload = {control_id: z2m_value}
            logger.info(
                "Device command: %s/%s = %s → %s",
                registered.z2m.friendly_name,
                control_id,
                wb_value,
                z2m_value,
            )
            self._z2m.set_device_state(registered.z2m.friendly_name, payload)
            registered.pending_commands[control_id] = PendingCommand(
                wb_value=wb_value, timestamp=time.monotonic()
            )
            self._mqtt_driver.publish_device_control(registered.device_id, control_id, wb_value)

        return on_command

    def _on_device_event(self, event: DeviceEvent) -> None:
        logger.info("Device event: %s %s", event.type, event.name)
        control = _EVENT_TYPE_TO_CONTROL.get(event.type)
        if control:
            self._mqtt_driver.publish_bridge_control(control, event.name)
        if event.type in (DeviceEventType.REMOVED, DeviceEventType.LEFT):
            registered = self._known_devices.pop(event.name, None)
            if registered:
                self._ieee_to_name.pop(registered.z2m.ieee_address, None)
                self._z2m.unsubscribe_device(event.name)
                self._mqtt_driver.unsubscribe_device_commands(registered.device_id, registered.controls)
                self._mqtt_driver.remove_device(registered.device_id, registered.controls)
                logger.info("Removed WB device '%s'", registered.device_id)
        elif event.type == DeviceEventType.RENAMED:
            self._on_device_renamed(event.old_name, event.name)
        self._update_stats()

    def _remove_stale_devices(self, devices: list[Z2MDevice]) -> None:
        """Remove devices that are registered locally but no longer present in zigbee2mqtt."""
        current_names = {d.friendly_name for d in devices}
        stale_names = [name for name in self._known_devices if name not in current_names]
        for name in stale_names:
            registered = self._known_devices.pop(name)
            self._ieee_to_name.pop(registered.z2m.ieee_address, None)
            self._z2m.unsubscribe_device(name)
            self._mqtt_driver.unsubscribe_device_commands(registered.device_id, registered.controls)
            self._mqtt_driver.remove_device(registered.device_id, registered.controls)
            logger.info("Removed stale WB device '%s' (%s)", name, registered.device_id)

    def _remove_ghost_devices(self, devices: list[Z2MDevice]) -> None:
        """Remove retained WB devices from previous runs that are no longer in zigbee2mqtt."""
        current_device_ids = {_sanitize_device_id(d.friendly_name) for d in devices}
        scanned_ids = self._mqtt_driver.get_scanned_device_ids()
        ghost_ids = scanned_ids - current_device_ids
        for device_id in ghost_ids:
            control_ids = self._mqtt_driver.get_scanned_controls(device_id)
            self._mqtt_driver.remove_retained_device(device_id, control_ids)
            logger.info("Removed ghost WB device '%s' (%d controls)", device_id, len(control_ids))

    def _find_old_name(self, ieee_address: str) -> Optional[str]:
        """Find friendly_name of a known device by ieee_address, or None. O(1) lookup."""
        return self._ieee_to_name.get(ieee_address)

    def _on_device_renamed(self, old_name: str, new_name: str) -> None:
        registered = self._known_devices.pop(old_name, None)
        if registered is None:
            logger.warning("Rename event for unknown device '%s' -> '%s'", old_name, new_name)
            return
        old_device_id = registered.device_id
        new_device_id = _sanitize_device_id(new_name)
        self._z2m.unsubscribe_device(old_name)
        self._mqtt_driver.unsubscribe_device_commands(old_device_id, registered.controls)
        self._mqtt_driver.remove_device(old_device_id, registered.controls)
        registered.z2m.friendly_name = new_name
        registered.device_id = new_device_id
        self._known_devices[new_name] = registered
        self._ieee_to_name[registered.z2m.ieee_address] = new_name
        self._z2m.subscribe_device(new_name)
        self._mqtt_driver.publish_device(new_device_id, new_name, registered.controls)
        if registered.z2m.type:
            self._mqtt_driver.publish_device_control(
                new_device_id, "device_type", _DEVICE_TYPE_RU.get(registered.z2m.type, registered.z2m.type)
            )
        self._mqtt_driver.subscribe_device_commands(
            new_device_id,
            registered.controls,
            self._make_device_command_handler(registered),
        )
        logger.info(
            "Renamed device '%s' -> '%s' (device_id: %s -> %s)",
            old_name,
            new_name,
            old_device_id,
            new_device_id,
        )


_MQTT_UNSAFE_CHARS = {"+", "#", "/"}


def _is_safe_topic_name(name: str) -> bool:
    """Check that a device name is safe to use in MQTT topic paths."""
    if not name:
        return False
    return not any(ch in name for ch in _MQTT_UNSAFE_CHARS)


def _sanitize_device_id(name: str) -> str:
    """Convert a device name to a valid WB device ID.

    Keeps Unicode letters/digits, ASCII alphanumerics, hyphens, and underscores.
    Replaces everything else (spaces, special chars) with underscores.
    """
    return re.sub(r"[^\w\-]", "_", name)


def _format_last_seen(value: object) -> str:
    """Convert last_seen to formatted local datetime string.

    zigbee2mqtt sends last_seen in one of three formats depending on configuration:
    - epoch milliseconds (default): 1700000000000
    - epoch seconds: 1700000000
    - ISO 8601 string: "2023-11-14T22:13:20.000Z"

    The > 1e12 threshold reliably distinguishes ms from s: 1e12 ms = 2001-09-09,
    while 1e12 s = year 33658. All real-world ms timestamps are above this threshold,
    and all real-world s timestamps are below it.
    """
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, (int, float)):
            if value > 1e12:
                value = value / 1000
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        logger.warning("Failed to parse last_seen: %s", value)
    return ""
