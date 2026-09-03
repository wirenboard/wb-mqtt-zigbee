import logging
import re
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from wb_common.mqtt_client import MQTTClient

from .mqtt_utils import is_safe_topic_name
from .registered_device import PendingCommand, RegisteredDevice
from .wb_converter.controls import (
    BridgeControl,
    ControlMeta,
    WbBoolValue,
    WbControlError,
)
from .wb_converter.expose_mapper import SERVICE_CONTROLS, map_exposes_to_controls
from .wb_converter.publisher import WbMqttDriver, build_display_name
from .z2m.client import Z2MClient
from .z2m.model import (
    BridgeInfo,
    BridgeLogLevel,
    BridgeState,
    DeviceEvent,
    DeviceEventType,
    Z2MDevice,
)

logger = logging.getLogger(__name__)

_EVENT_TYPE_TO_CONTROL = {
    DeviceEventType.JOINED: BridgeControl.LAST_JOINED,
    DeviceEventType.LEFT: BridgeControl.LAST_LEFT,
    DeviceEventType.REMOVED: BridgeControl.LAST_REMOVED,
}

# Appending the (unique) ieee_address resolves a device_id clash in one round; a second
# round only matters when a name sanitizes to an already-suffixed id. The bound keeps an
# unforeseen input from looping forever.
_MAX_ID_DISAMBIGUATION_ROUNDS = 5


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
        self._mqtt_driver.configure_bridge_lwt()
        self._bridge_log_min_level = bridge_log_min_level
        self._log_min_rank = BridgeLogLevel.RANK.get(
            bridge_log_min_level, BridgeLogLevel.RANK[BridgeLogLevel.WARNING]
        )
        self._command_debounce_sec = command_debounce_sec
        self._messages_received = 0
        self._last_stats_publish = 0.0
        self._known_devices: dict[str, RegisteredDevice] = {}  # friendly_name → RegisteredDevice
        self._ieee_to_name: dict[str, str] = {}  # ieee_address → friendly_name
        # Last bridge/devices list, so a standalone rename can recompute the device_id
        # layout over the same set — including devices present in z2m but not registered
        # (still interviewing, no exposes yet), which still take part in id collisions.
        self._last_devices: list[Z2MDevice] = []
        self._retained_scan_active = False
        self._reconnect_count = 0

    def subscribe(self) -> None:
        self._mqtt_driver.start_retained_scan()
        self._retained_scan_active = True
        self._publish_bridge()

    def shutdown(self) -> list[object]:
        """Remove all retained WB topics and return their publish results."""
        published = []
        known_ids = set()
        if self._retained_scan_active:
            self._mqtt_driver.stop_retained_scan()
            self._retained_scan_active = False
        for registered in self._known_devices.values():
            known_ids.add(registered.device_id)
            published.extend(self._teardown_device_id(registered))
        for device_id in self._mqtt_driver.get_scanned_device_ids() - known_ids:
            published.extend(
                self._mqtt_driver.remove_retained_device(
                    device_id, self._mqtt_driver.get_scanned_controls(device_id)
                )
            )
        published.extend(self._mqtt_driver.remove_bridge_device())
        return published

    def republish(self) -> None:
        self._reconnect_count += 1
        self._publish_bridge()
        self._mqtt_driver.publish_bridge_control(BridgeControl.RECONNECTS, str(self._reconnect_count))
        for friendly_name, registered in self._known_devices.items():
            registered.availability_received = False
            registered.values["available"] = WbBoolValue.FALSE
            self._mqtt_driver.publish_device(
                registered.device_id,
                friendly_name,
                registered.controls,
                registered.values,
                model=registered.z2m.model,
                ieee_address=registered.z2m.ieee_address,
            )
            self._mqtt_driver.publish_device_error(
                registered.device_id, _device_offline_error(registered.controls)
            )
            if registered.z2m.type:
                self._mqtt_driver.publish_device_control(
                    registered.device_id,
                    "device_type",
                    registered.z2m.type,
                )
            if registered.z2m.model:
                self._mqtt_driver.publish_device_control(
                    registered.device_id,
                    "model",
                    registered.z2m.model,
                )
            if registered.z2m.power_source:
                self._mqtt_driver.publish_device_control(
                    registered.device_id,
                    "power_source",
                    registered.z2m.power_source,
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
        # z2m down → the whole bridge is non-functional: flag the bridge device
        # ("rw" — no zigbee device can be read or commanded); clear when z2m is back.
        bridge_error = "" if state == BridgeState.ONLINE else WbControlError.READ_WRITE
        self._mqtt_driver.publish_bridge_error(bridge_error)
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
            self._mqtt_driver.publish_bridge_control(BridgeControl.LOG, _strip_control_chars(message))

    def _on_devices(self, devices: list[Z2MDevice]) -> None:
        logger.info("Devices: %d", len(devices))
        self._mqtt_driver.publish_bridge_control(BridgeControl.DEVICE_COUNT, str(len(devices)))
        self._update_stats()
        # Resolve device_ids for the whole batch up front: the layout is a pure function of
        # this list, so it does not depend on list order or on what we happened to register
        # earlier (which would differ after a restart).
        device_ids = self._compute_device_ids(devices)
        self._last_devices = devices
        # Order matters here, and every step must run before the registration loop:
        #   1. stale removal, so a departing device releases its device_id before anyone
        #      else is published under it (it matches on ieee_address, so renames are safe);
        #   2. renames, so a device filed under its old friendly_name is moved before
        #      anything looks it up (otherwise a newcomer taking the freed name is merged
        #      into the renamed device's record and ends up driving the wrong hardware);
        #   3. reassignments, so devices that lose or regain the bare id release it.
        # Doing any of these after the loop would tear down topics just published.
        self._remove_stale_devices(devices)
        self._apply_renames(devices, device_ids)
        self._apply_device_ids(device_ids)
        for device in devices:
            try:
                self._register_device(device, device_ids.get(device.ieee_address))
            except Exception:  # pylint: disable=broad-except
                # Isolate a bad device: malformed field types (e.g. non-string
                # friendly_name, bad access/value_min) pass the JSON-shape check but
                # break control mapping. Log it and keep going, so later devices and the
                # ghost cleanup below still run (arc42 "Устойчивость к ошибкам").
                logger.exception("Failed to register device '%s'", device.friendly_name)
        if self._retained_scan_active:
            self._remove_ghost_devices(device_ids)
            self._mqtt_driver.stop_retained_scan()
            self._retained_scan_active = False

    def _register_device(self, device: Z2MDevice, device_id: Optional[str]) -> None:
        if not is_safe_topic_name(device.friendly_name):
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
        controls = map_exposes_to_controls(
            device.exposes,
            device_type=device.type,
            power_source=device.power_source,
            model=device.model,
        )
        if sum(1 for _control in controls if _control not in SERVICE_CONTROLS) == 0:
            logger.warning("Device '%s' has no mappable exposes, skipping", device.friendly_name)
            return
        if device_id is None:
            # Defensive: a registerable device always gets an entry from
            # _compute_device_ids (only unsafe names are dropped, and those returned above).
            logger.warning("No device_id resolved for '%s', skipping", device.friendly_name)
            return
        registered = RegisteredDevice(
            z2m=device,
            controls=controls,
            device_id=device_id,
            values={"available": WbBoolValue.FALSE},
        )
        logger.info(
            "Registering device '%s' as '%s' (%d controls)", device.friendly_name, device_id, len(controls)
        )
        self._known_devices[device.friendly_name] = registered
        self._ieee_to_name[device.ieee_address] = device.friendly_name
        self._publish_device_topics(registered)
        self._mqtt_driver.publish_device_error(device_id, _device_offline_error(controls))
        self._z2m.subscribe_device(device.friendly_name)
        self._z2m.request_device_state(device.friendly_name)

    def _publish_device_topics(
        self, registered: RegisteredDevice, initial_values: Optional[dict[str, str]] = None
    ) -> None:
        """
        Publish a registered device's WB topics under its current device_id and subscribe
        its command topics. Shared by registration, rename, and device_id reassignment.
        """
        device = registered.z2m
        values = dict(registered.values)
        if initial_values:
            values.update(initial_values)
        self._mqtt_driver.publish_device(
            registered.device_id,
            device.friendly_name,
            registered.controls,
            values,
            model=device.model,
            ieee_address=device.ieee_address,
        )
        if device.type:
            self._mqtt_driver.publish_device_control(registered.device_id, "device_type", device.type)
        if device.model:
            self._mqtt_driver.publish_device_control(registered.device_id, "model", device.model)
        if device.power_source:
            self._mqtt_driver.publish_device_control(
                registered.device_id, "power_source", device.power_source
            )
        self._mqtt_driver.subscribe_device_commands(
            registered.device_id,
            registered.controls,
            self._make_device_command_handler(registered),
        )

    def _teardown_device_id(self, registered: RegisteredDevice) -> list[object]:
        """Unsubscribe commands and clear all retained WB topics of the current device_id"""
        self._mqtt_driver.unsubscribe_device_commands(registered.device_id, registered.controls)
        return self._mqtt_driver.remove_device(registered.device_id, registered.controls)

    def _republish_device(self, registered: RegisteredDevice) -> None:
        """
        Republish a device under its current device_id after its old topics were torn down
        (rename or device_id reassignment).

        The new topics start out empty, so restore what we already know: the last
        availability we saw, or "unreachable" if we have never heard from the device. z2m
        only republishes availability when it changes, so publishing a blanket "offline"
        here would leave a healthy device flagged with an error until it next changes state
        — a false alarm on an ordinary rename. Also ask z2m for the current state so the
        control values come back at once instead of staying blank.
        """
        # pending_commands are deliberately kept: they expire on their own and still
        # suppress a pre-command echo from z2m, so a command issued just before the move
        # is not visibly reverted.
        is_online = bool(registered.is_online)
        if registered.is_online is None:
            registered.availability_received = False
        available = WbBoolValue.TRUE if is_online else WbBoolValue.FALSE
        registered.values["available"] = available
        self._publish_device_topics(registered)
        self._mqtt_driver.publish_device_error(
            registered.device_id, "" if is_online else _device_offline_error(registered.controls)
        )
        self._z2m.request_device_state(registered.z2m.friendly_name)

    def _update_device(self, device: Z2MDevice) -> None:
        """Update metadata and controls for an already-registered device.

        Re-registers controls if exposes have changed (e.g. after firmware update).
        """
        registered = self._known_devices[device.friendly_name]
        if device.exposes:
            new_controls = map_exposes_to_controls(
                device.exposes,
                device_type=device.type,
                power_source=device.power_source,
                model=device.model,
            )
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
                registered.values = {
                    control_id: value
                    for control_id, value in registered.values.items()
                    if control_id in new_controls
                }
                self._publish_device_topics(registered)
                self._z2m.request_device_state(device.friendly_name)
        # Publish service-control values AFTER any re-registration: remove_device()
        # above wipes the device's retained topics, so publishing these earlier would
        # leave device_type/model/power_source blank until exposes next stabilize.
        if device.type:
            self._mqtt_driver.publish_device_control(registered.device_id, "device_type", device.type)
        if device.model:
            self._mqtt_driver.publish_device_control(registered.device_id, "model", device.model)
        if device.power_source:
            self._mqtt_driver.publish_device_control(
                registered.device_id, "power_source", device.power_source
            )

    def _on_device_availability(self, friendly_name: str, available: bool) -> None:
        registered = self._known_devices.get(friendly_name)
        if registered is None:
            logger.debug("Availability update for unknown device '%s', skipping", friendly_name)
            return
        registered.availability_received = True
        registered.is_online = available
        wb_value = WbBoolValue.TRUE if available else WbBoolValue.FALSE
        registered.values["available"] = wb_value
        self._mqtt_driver.publish_device_control(registered.device_id, "available", wb_value)
        self._mqtt_driver.publish_device_error(
            registered.device_id, "" if available else _device_offline_error(registered.controls)
        )
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
            registered.values[prop] = wb_value
            self._mqtt_driver.publish_device_control(registered.device_id, prop, wb_value)
        if "last_seen" in state:
            formatted = _format_last_seen(state["last_seen"])
            if formatted:
                registered.values["last_seen"] = formatted
                self._mqtt_driver.publish_device_control(registered.device_id, "last_seen", formatted)
        if not registered.availability_received:
            registered.is_online = True
            registered.values["available"] = WbBoolValue.TRUE
            self._mqtt_driver.publish_device_control(registered.device_id, "available", WbBoolValue.TRUE)
            self._mqtt_driver.publish_device_error(registered.device_id, "")
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
            registered.values[control_id] = wb_value
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
        """
        Remove devices that are registered locally but no longer present in zigbee2mqtt.

        Presence is decided by ieee_address, not friendly_name: the name changes on a
        rename (and we may refuse a rename to an unsafe name), while the ieee_address is
        stable. Matching on names would drop a device that is merely renamed, and would
        force this to run after the renames — too late, because a renamed device can land
        on the device_id a departing one still holds and have its fresh topics wiped.
        """
        current_ieee = {device.ieee_address for device in devices}
        stale = [
            (name, registered)
            for name, registered in self._known_devices.items()
            if registered.z2m.ieee_address not in current_ieee
        ]
        for name, registered in stale:
            self._detach_device(name, registered)
            self._ieee_to_name.pop(registered.z2m.ieee_address, None)
            logger.info("Removed stale WB device '%s' (%s)", name, registered.device_id)

    def _compute_device_ids(self, devices: list[Z2MDevice]) -> dict[str, str]:
        """
        Map {ieee_address: device_id} for exactly this set of devices.

        _sanitize_device_id can map two distinct z2m names to the same id ("lamp.1" and
        "lamp 1" both -> "lamp_1"). When that happens NO device keeps the bare id: every
        member of the colliding group gets an ieee_address suffix. The ambiguous id then
        simply does not exist, so a wb-rules reference to it breaks loudly (empty topic)
        instead of silently reading whichever device happened to win.

        The result depends only on the devices passed in — not on registration order and
        not on what we registered before a restart — so the same z2m device list always
        produces the same layout.

        Every device's model/friendly_name/ieee_address is already str-validated by
        Z2MDevice.from_dict, so id-building here can't raise on a malformed field type.
        """
        assigned: dict[str, str] = {}
        for device in devices:
            if not is_safe_topic_name(device.friendly_name):
                continue  # skipped at registration; must not claim an id
            assigned[device.ieee_address] = _build_device_id(
                device.model, device.friendly_name, device.ieee_address
            )
        # Suffix every member of a colliding group, then re-check: a suffixed id can itself
        # equal another device's id (a friendly_name that sanitizes to "<base>_<ieee>"), so
        # repeat until every device holds an id of its own. ieee_address is unique, so this
        # converges; the bound only guards against an unforeseen input.
        for _round in range(_MAX_ID_DISAMBIGUATION_ROUNDS):
            by_id: dict[str, list[str]] = {}
            for ieee, device_id in assigned.items():
                by_id.setdefault(device_id, []).append(ieee)
            ambiguous = {device_id: ieees for device_id, ieees in by_id.items() if len(ieees) > 1}
            if not ambiguous:
                break
            for device_id, ieees in ambiguous.items():
                logger.warning(
                    "device_id '%s' is ambiguous between %s; none keeps it, all get an ieee suffix",
                    device_id,
                    sorted(ieees),
                )
                for ieee in ieees:
                    assigned[ieee] = f"{device_id}_{_sanitize_device_id(ieee)}"
        else:
            logger.error("Could not make device_ids unique after %d rounds", _MAX_ID_DISAMBIGUATION_ROUNDS)
        return assigned

    def _apply_device_ids(self, assigned: dict[str, str]) -> None:
        """
        Move already-registered devices whose assigned device_id changed.

        A device loses the bare id when a colliding neighbour appears and regains it when
        that neighbour leaves, so the id is not fixed for the lifetime of the process. Tear
        every outgoing id down first and only then publish the new ones, so no device
        publishes into topics another one is still holding.

        Renames must be applied before this runs: a device still filed under its old
        friendly_name would otherwise be republished with a stale name.
        """
        changes = [
            (registered, assigned[registered.z2m.ieee_address])
            for registered in self._known_devices.values()
            if registered.z2m.ieee_address in assigned
            and assigned[registered.z2m.ieee_address] != registered.device_id
        ]
        for registered, _new_id in changes:
            self._teardown_device_id(registered)
        for registered, new_id in changes:
            logger.info(
                "Reassigning device '%s': device_id '%s' -> '%s'",
                registered.z2m.friendly_name,
                registered.device_id,
                new_id,
            )
            registered.device_id = new_id
            self._republish_device(registered)

    def _remove_ghost_devices(self, device_ids: dict[str, str]) -> None:
        """
        Remove retained WB devices from previous runs that are no longer in zigbee2mqtt
        """
        # Union registered ids with the ids assigned to every incoming device, so a device
        # present in z2m but skipped at registration (no exposes yet, e.g. mid-interview)
        # is not wiped as a ghost.
        current_device_ids = {registered.device_id for registered in self._known_devices.values()}
        current_device_ids |= set(device_ids.values())
        scanned_ids = self._mqtt_driver.get_scanned_device_ids()
        ghost_ids = scanned_ids - current_device_ids
        for device_id in ghost_ids:
            control_ids = self._mqtt_driver.get_scanned_controls(device_id)
            self._mqtt_driver.remove_retained_device(device_id, control_ids)
            logger.info("Removed ghost WB device '%s' (%d controls)", device_id, len(control_ids))

    def _find_old_name(self, ieee_address: str) -> Optional[str]:
        """Find friendly_name of a known device by ieee_address, or None. O(1) lookup."""
        return self._ieee_to_name.get(ieee_address)

    def _mark_device_unusable(self, registered: RegisteredDevice) -> None:
        """
        Flag a device we can no longer address, and stop accepting commands for it.

        Reached when z2m renamed a device to a name we refuse to put in a topic. The device
        keeps its previous WB card, but that card is now detached from reality: z2m talks
        under the new name, so nothing updates it, and a command would be echoed
        optimistically and then dropped on the floor. Show it as unavailable with a device
        error and drop the command subscriptions, so the problem is visible instead of the
        card looking healthy and responsive. A later rename to a safe name republishes it.
        """
        registered.is_online = False
        registered.availability_received = False
        self._mqtt_driver.unsubscribe_device_commands(registered.device_id, registered.controls)
        self._mqtt_driver.publish_device_control(registered.device_id, "available", WbBoolValue.FALSE)
        self._mqtt_driver.publish_device_error(
            registered.device_id, _device_offline_error(registered.controls)
        )

    def _apply_renames(self, devices: list[Z2MDevice], device_ids: dict[str, str]) -> None:
        """
        Re-file every device of this batch whose friendly_name changed since we saw it.

        Collected up front, then detached in one pass and re-attached in another: two
        devices can swap names in a single batch, and re-attaching one before detaching the
        other would drop whichever record the first insert landed on.
        """
        renames = []
        for device in devices:
            old_name = self._find_old_name(device.ieee_address)
            if old_name is None or old_name == device.friendly_name:
                continue
            registered = self._known_devices.get(old_name)
            if registered is None:
                continue
            if not is_safe_topic_name(device.friendly_name):
                # Same rule as the bridge/event path: keep the old name rather than let a
                # wildcard/separator into our topics, and flag the device as unusable.
                logger.warning(
                    "Ignoring rename '%s' -> '%s': unsafe name for MQTT topics",
                    old_name,
                    device.friendly_name,
                )
                self._mark_device_unusable(registered)
                continue
            renames.append((registered, old_name, device.friendly_name))
        for registered, old_name, _new_name in renames:
            self._detach_device(old_name, registered)
        for registered, old_name, new_name in renames:
            self._rename_device(registered, old_name, new_name, device_ids)

    def _detach_device(self, name: str, registered: RegisteredDevice) -> None:
        """
        Drop a device's WB presence and z2m subscription, keeping its RegisteredDevice.

        Used before re-filing a device under another name/device_id. Detaching every
        renamed device before re-attaching any of them is what makes a name swap between
        two devices safe: neither insert can land on a name the other still holds.
        """
        self._known_devices.pop(name, None)
        self._z2m.unsubscribe_device(name)
        self._teardown_device_id(registered)

    def _attach_device(self, registered: RegisteredDevice, new_name: str, device_id: str) -> None:
        """File a detached device under new_name/device_id, subscribe it and publish it"""
        occupant = self._known_devices.get(new_name)
        if occupant is not None and occupant is not registered:
            # z2m keeps friendly_names unique, so the holder is on its way out (removed in
            # this same batch). Clear it now, or its retained topics would be orphaned.
            logger.warning(
                "Name '%s' still held by ieee %s; removing it", new_name, occupant.z2m.ieee_address
            )
            self._detach_device(new_name, occupant)
            self._ieee_to_name.pop(occupant.z2m.ieee_address, None)
        registered.z2m.friendly_name = new_name
        registered.device_id = device_id
        self._known_devices[new_name] = registered
        self._ieee_to_name[registered.z2m.ieee_address] = new_name
        self._z2m.subscribe_device(new_name)
        self._republish_device(registered)

    def _rename_device(
        self, registered: RegisteredDevice, old_name: str, new_name: str, assigned: dict[str, str]
    ) -> None:
        """Re-file an already-detached device under new_name, using the given id layout"""
        old_device_id = registered.device_id
        device_id = assigned.get(
            registered.z2m.ieee_address,
            _build_device_id(registered.z2m.model, new_name, registered.z2m.ieee_address),
        )
        self._attach_device(registered, new_name, device_id)
        logger.info(
            "Renamed device '%s' -> '%s' (device_id: %s -> %s)",
            old_name,
            new_name,
            old_device_id,
            registered.device_id,
        )

    def _on_device_renamed(self, old_name: str, new_name: str) -> None:
        """Handle a standalone bridge/event rename (batched renames go through _on_devices)"""
        registered = self._known_devices.get(old_name)
        if registered is None:
            logger.warning("Rename event for unknown device '%s' -> '%s'", old_name, new_name)
            return
        # new_name comes straight from the z2m payload (data["to"]); reject unsafe names so
        # a rename to "#"/"+"/"a/b" cannot hijack a subscription. Keep the old name, but
        # flag the device — under the new name we can no longer reach it.
        if not is_safe_topic_name(new_name):
            logger.warning("Ignoring rename '%s' -> '%s': unsafe name for MQTT topics", old_name, new_name)
            self._mark_device_unusable(registered)
            return
        self._detach_device(old_name, registered)
        # Recompute over the last device list (with the new name applied): the new name may
        # now collide with another device — then both move to suffixed ids — and the freed
        # name may let a former partner take the bare id back. Using the last list rather
        # than just the registered devices keeps unregistered-but-present devices in the
        # picture, so registered ones don't flap to the bare id and back on the next list.
        registered.z2m.friendly_name = new_name
        known = self._last_devices or [known.z2m for known in self._known_devices.values()]
        assigned = self._compute_device_ids(
            known if registered.z2m in known else list(known) + [registered.z2m]
        )
        self._rename_device(registered, old_name, new_name, assigned)
        self._apply_device_ids(assigned)


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _strip_control_chars(text: str) -> str:
    """Replace C0/C1 control characters (incl. CR/LF/NUL) with spaces.

    The z2m log message is forwarded verbatim into the retained WB "Log" control;
    stray control characters would corrupt the single-line value shown in the UI.
    """
    return _CONTROL_CHARS_RE.sub(" ", text)


def _sanitize_device_id(name: str) -> str:
    """Convert a device name to a valid WB device ID.

    Keeps Unicode letters/digits, ASCII alphanumerics, hyphens, and underscores.
    Replaces everything else (spaces, special chars) with underscores.
    """
    return re.sub(r"[^\w\-]", "_", name)


def _build_device_id(model: str, friendly_name: str, ieee_address: str) -> str:
    """
    Build the WB device ID from the device display name.

    The device_id mirrors the card title (see build_display_name): "{model} {ieee}"
    while the device is unnamed, or just the user's friendly_name once renamed. The
    device_id is the last-resort fallback the WB Web UI shows in the card header on a
    cold load, so it must carry the same meaningful text as the title.
    """
    return _sanitize_device_id(build_display_name(model, friendly_name, ieee_address))


def _device_offline_error(controls: dict[str, ControlMeta]) -> str:
    """
    WB meta/error value for an unreachable device.

    Always "r" (its state cannot be read); plus "w" when the device has at least one
    writable control (a command that also cannot be delivered). A read-only device
    (e.g. a pure sensor) has nothing to write, so it gets just "r".
    """
    has_writable = any(not meta.readonly for meta in controls.values())
    return WbControlError.READ_WRITE if has_writable else WbControlError.READ


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
