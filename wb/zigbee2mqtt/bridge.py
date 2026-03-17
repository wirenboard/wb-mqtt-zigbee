import logging
import re
import time
from datetime import datetime
from typing import Optional

from wb_common.mqtt_client import MQTTClient

from .registered_device import RegisteredDevice
from .wb_converter.controls import BridgeControl
from .wb_converter.expose_mapper import map_exposes_to_controls
from .wb_converter.publisher import WbPublisher
from .z2m.client import Z2MClient
from .z2m.model import BridgeInfo, BridgeLogLevel, DeviceEvent, DeviceEventType, Z2MDevice

logger = logging.getLogger(__name__)

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
        self, mqtt_client: MQTTClient, base_topic: str, device_id: str, device_name: str, bridge_log_min_level: str
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
        )
        self._wb = WbPublisher(mqtt_client, device_id, device_name)
        self._bridge_log_min_level = bridge_log_min_level
        self._log_min_rank = BridgeLogLevel.RANK.get(bridge_log_min_level, BridgeLogLevel.RANK[BridgeLogLevel.WARNING])
        self._messages_received = 0
        self._last_stats_publish = 0.0
        self._known_devices: dict[str, RegisteredDevice] = {}  # friendly_name → RegisteredDevice

    def subscribe(self) -> None:
        self._wb.publish_bridge_device()
        self._wb.publish_bridge_control(BridgeControl.LOG_LEVEL, self._bridge_log_min_level)
        self._z2m.subscribe()
        self._wb.subscribe_bridge_commands(
            on_permit_join=self._z2m.set_permit_join,
            on_update_devices=self._z2m.request_devices_update,
        )

    def republish(self) -> None:
        self._wb.publish_bridge_device()
        self._wb.publish_bridge_control(BridgeControl.LOG_LEVEL, self._bridge_log_min_level)

    def _update_stats(self) -> None:
        self._messages_received += 1
        now = time.monotonic()
        if now - self._last_stats_publish < 1.0:
            return
        self._last_stats_publish = now
        self._wb.publish_bridge_control(BridgeControl.MESSAGES_RECEIVED, str(self._messages_received))
        self._wb.publish_bridge_control(
            BridgeControl.LAST_SEEN, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def _on_bridge_state(self, state: str) -> None:
        logger.info("Bridge state: %s", state)
        self._wb.publish_bridge_control(BridgeControl.STATE, state)
        self._update_stats()

    def _on_bridge_info(self, info: BridgeInfo) -> None:
        logger.info("Bridge info: version=%s, permit_join=%s", info.version, info.permit_join)
        self._wb.publish_bridge_control(BridgeControl.VERSION, info.version)
        self._wb.publish_bridge_control(BridgeControl.PERMIT_JOIN, "1" if info.permit_join else "0")
        self._update_stats()

    def _on_bridge_log(self, level: str, message: str) -> None:
        self._update_stats()
        if BridgeLogLevel.RANK.get(level, 0) >= self._log_min_rank:
            self._wb.publish_bridge_control(BridgeControl.LOG, message)

    def _on_devices(self, devices: list) -> None:
        logger.info("Devices: %d", len(devices))
        self._wb.publish_bridge_control(BridgeControl.DEVICE_COUNT, str(len(devices)))
        self._update_stats()
        for device in devices:
            self._register_device(device)

    def _register_device(self, device: Z2MDevice) -> None:
        if device.friendly_name in self._known_devices:
            logger.debug("Device '%s' already registered, skipping", device.friendly_name)
            return
        old_name = self._find_old_name(device.ieee_address)
        if old_name is not None:
            self._on_device_renamed(old_name, device.friendly_name)
            return
        if not device.exposes:
            logger.info("Device '%s' has no exposes yet, skipping", device.friendly_name)
            return
        controls = map_exposes_to_controls(device.exposes)
        if len(controls) <= 1:
            logger.warning("Device '%s' has no mappable exposes, skipping", device.friendly_name)
            return
        device_id = _sanitize_device_id(device.ieee_address)
        registered = RegisteredDevice(z2m=device, controls=controls, device_id=device_id)
        logger.info("Registering device '%s' as '%s' (%d controls)", device.friendly_name, device_id, len(controls))
        self._known_devices[device.friendly_name] = registered
        self._wb.publish_device(device_id, device.friendly_name, controls)
        self._z2m.subscribe_device(device.friendly_name)
        self._z2m.request_device_state(device.friendly_name)

    def _on_device_state(self, friendly_name: str, state: dict[str, object]) -> None:
        registered = self._known_devices.get(friendly_name)
        if registered is None:
            logger.debug("State update for unknown device '%s', skipping", friendly_name)
            return
        for prop, meta in registered.controls.items():
            if prop in state:
                self._wb.publish_device_control(registered.device_id, prop, meta.format_value(state[prop]))
        if "last_seen" in state:
            formatted = _format_last_seen(state["last_seen"])
            if formatted:
                self._wb.publish_device_control(registered.device_id, "last_seen", formatted)
        self._update_stats()

    def _on_device_event(self, event: DeviceEvent) -> None:
        logger.info("Device event: %s %s", event.type, event.name)
        control = _EVENT_TYPE_TO_CONTROL.get(event.type)
        if control:
            self._wb.publish_bridge_control(control, event.name)
        if event.type in (DeviceEventType.REMOVED, DeviceEventType.LEFT):
            registered = self._known_devices.pop(event.name, None)
            if registered:
                self._z2m.unsubscribe_device(event.name)
                self._wb.remove_device(registered.device_id, registered.controls)
                logger.info("Removed WB device '%s'", registered.device_id)
        elif event.type == DeviceEventType.RENAMED:
            self._on_device_renamed(event.old_name, event.name)
        self._update_stats()

    def _find_old_name(self, ieee_address: str) -> Optional[str]:
        """Find friendly_name of a known device by ieee_address, or None"""
        for name, registered in self._known_devices.items():
            if registered.z2m.ieee_address == ieee_address:
                return name
        return None

    def _on_device_renamed(self, old_name: str, new_name: str) -> None:
        registered = self._known_devices.pop(old_name, None)
        if registered is None:
            logger.warning("Rename event for unknown device '%s' -> '%s'", old_name, new_name)
            return
        self._z2m.unsubscribe_device(old_name)
        registered.z2m.friendly_name = new_name
        self._known_devices[new_name] = registered
        self._z2m.subscribe_device(new_name)
        self._wb.publish_device(registered.device_id, new_name, registered.controls)
        logger.info("Renamed device '%s' -> '%s' (device_id=%s)", old_name, new_name, registered.device_id)


def _sanitize_device_id(ieee_address: str) -> str:
    """Convert ieee_address to a valid WB device ID (alphanumeric + underscores)"""
    return re.sub(r"[^a-zA-Z0-9_]", "_", ieee_address)


def _format_last_seen(value: object) -> str:
    """Convert last_seen to formatted local datetime string. Handles epoch (ms and s) and ISO strings"""
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, (int, float)):
            if value > 1e12:
                value = value / 1000
            return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        logger.warning("Failed to parse last_seen: %s", value)
    return ""


