import json
import logging
from typing import Callable, Optional, Union

from wb_common.mqtt_client import MQTTClient

from .model import (
    BridgeInfo,
    BridgeState,
    DeviceEvent,
    DeviceEventType,
    Z2MDevice,
    Z2MEventType,
)

logger = logging.getLogger(__name__)

PERMIT_JOIN_TIME_SEC = 254
PERMIT_JOIN_TIME_SEC_DISABLED = 0
_MQTT_WILDCARD_CHARS = {"+", "#"}


class Z2MClient:
    """Subscribes to zigbee2mqtt MQTT topics and parses incoming messages into typed callbacks"""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        mqtt_client: MQTTClient,
        base_topic: str,
        on_bridge_state: Callable[[str], None],
        on_bridge_info: Callable[[BridgeInfo], None],
        on_bridge_log: Callable[[str, str], None],
        on_devices: Callable[[list[Z2MDevice]], None],
        on_device_event: Callable[[DeviceEvent], None],
        on_device_state: Callable[[str, dict[str, object]], None],  # (friendly_name, z2m state JSON)
    ) -> None:
        """
        Args:
            mqtt_client: shared MQTT client instance
            base_topic: zigbee2mqtt base topic, from config key "zigbee2mqtt_base_topic" (default "zigbee2mqtt")
            on_bridge_state: called with bridge state ("online", "offline", "error")
            on_bridge_info: called with BridgeInfo on bridge/info updates
            on_bridge_log: called with (level, message) on bridge/logging updates
            on_devices: called with list of Z2MDevice (excluding Coordinator)
            on_device_event: called with DeviceEvent on join/leave/remove
            on_device_state: called with (friendly_name, state_dict) on device state updates
        """
        self._client = mqtt_client
        self._base_topic = base_topic
        self._on_bridge_state = on_bridge_state
        self._on_bridge_info = on_bridge_info
        self._on_bridge_log = on_bridge_log
        self._on_devices = on_devices
        self._on_device_event = on_device_event
        self._on_device_state = on_device_state
        self._subscribed_devices: set[str] = set()

    def subscribe(self) -> None:
        """Subscribe to all zigbee2mqtt bridge topics and register message handlers.

        Safe to call on reconnect: re-subscribes to broker (which forgets subscriptions
        after clean session reconnect) and clears _subscribed_devices so device topics
        can be re-subscribed.
        """
        subscriptions = [
            (f"{self._base_topic}/bridge/state", self._handle_bridge_state),
            (f"{self._base_topic}/bridge/info", self._handle_bridge_info),
            (f"{self._base_topic}/bridge/logging", self._handle_bridge_log),
            (f"{self._base_topic}/bridge/devices", self._handle_bridge_devices),
            (f"{self._base_topic}/bridge/event", self._handle_bridge_event),
            (f"{self._base_topic}/bridge/response/device/remove", self._handle_device_remove_response),
        ]
        for topic, handler in subscriptions:
            self._client.subscribe(topic)
            self._client.message_callback_add(topic, handler)
        self._subscribed_devices.clear()

    def set_permit_join(self, enabled: bool) -> None:
        """Send permit_join request to zigbee2mqtt. Enables for PERMIT_JOIN_TIME_SEC or disables immediately"""
        time = PERMIT_JOIN_TIME_SEC if enabled else PERMIT_JOIN_TIME_SEC_DISABLED
        payload = json.dumps({"time": time})
        self._client.publish(f"{self._base_topic}/bridge/request/permit_join", payload)

    def request_devices_update(self) -> None:
        """Re-subscribe to bridge/devices to receive the retained device list again."""
        topic = f"{self._base_topic}/bridge/devices"
        self._client.unsubscribe(topic)
        self._client.subscribe(topic)
        self._client.message_callback_add(topic, self._handle_bridge_devices)

    def subscribe_device(self, friendly_name: str) -> None:
        """Subscribe to a device's state topic"""
        if not _is_safe_topic_segment(friendly_name):
            logger.warning("Refusing to subscribe to device with unsafe name: '%s'", friendly_name)
            return
        if friendly_name in self._subscribed_devices:
            logger.debug("Already subscribed to '%s', skipping", friendly_name)
            return
        topic = f"{self._base_topic}/{friendly_name}"
        self._client.subscribe(topic)
        self._client.message_callback_add(topic, self._make_device_state_handler(friendly_name))
        self._subscribed_devices.add(friendly_name)

    def unsubscribe_device(self, friendly_name: str) -> None:
        """Unsubscribe from a device's state topic"""
        if friendly_name not in self._subscribed_devices:
            logger.debug("Not subscribed to '%s', skipping unsubscribe", friendly_name)
            return
        topic = f"{self._base_topic}/{friendly_name}"
        self._client.unsubscribe(topic)
        self._client.message_callback_remove(topic)
        self._subscribed_devices.discard(friendly_name)

    def request_device_state(self, friendly_name: str) -> None:
        """Request current state from a device via zigbee2mqtt/{device}/get"""
        if not _is_safe_topic_segment(friendly_name):
            return
        self._client.publish(f"{self._base_topic}/{friendly_name}/get", "{}")

    def set_device_state(self, friendly_name: str, payload: dict) -> None:
        """Send command to a device via zigbee2mqtt/{device}/set"""
        if not _is_safe_topic_segment(friendly_name):
            return
        self._client.publish(f"{self._base_topic}/{friendly_name}/set", json.dumps(payload))

    def _make_device_state_handler(self, friendly_name: str):
        def handler(_client: object, _userdata: object, message: object) -> None:
            data = _parse_json_payload(message, friendly_name)
            if data is not None:
                self._on_device_state(friendly_name, data)

        return handler

    def _handle_bridge_state(self, _client: object, _userdata: object, message: object) -> None:
        """Parse bridge/state: may be plain string or JSON {"state": "..."}"""
        raw = message.payload.decode("utf-8").strip()
        try:
            data = json.loads(raw)
            state = data.get("state", raw) if isinstance(data, dict) else raw
        except json.JSONDecodeError:
            state = raw
        if state not in (BridgeState.ONLINE, BridgeState.OFFLINE, BridgeState.ERROR):
            logger.warning("Unknown bridge state: %s", state)
            return
        self._on_bridge_state(state)

    def _handle_bridge_info(self, _client: object, _userdata: object, message: object) -> None:
        """Parse bridge/info JSON into BridgeInfo and forward to callback"""
        data = _parse_json_payload(message, "bridge/info")
        if data is None:
            return
        info = BridgeInfo(
            version=data.get("version", ""),
            permit_join=data.get("permit_join", False),
            permit_join_end=data.get("permit_join_end"),
        )
        self._on_bridge_info(info)

    def _handle_bridge_log(self, _client: object, _userdata: object, message: object) -> None:
        """Parse bridge/logging JSON, extract level and message. Falls back to raw string on error"""
        try:
            data = json.loads(message.payload.decode("utf-8"))
            log_level: str = data.get("level", "info")
            log_message: Optional[str] = data.get("message", "")
        except json.JSONDecodeError:
            log_level = "info"
            log_message = message.payload.decode("utf-8")
        self._on_bridge_log(log_level, log_message or "")

    def _handle_bridge_devices(self, _client: object, _userdata: object, message: object) -> None:
        """Parse bridge/devices JSON array into Z2MDevice list (excluding Coordinator)"""
        data = _parse_json_payload(message, "bridge/devices")
        if data is None:
            return
        devices = []
        for device_data in data:
            if device_data.get("type") != "Coordinator":
                try:
                    devices.append(Z2MDevice.from_dict(device_data))
                except Exception:  # pylint: disable=broad-except
                    logger.exception(
                        "Failed to parse device: %s", device_data.get("friendly_name", device_data)
                    )
        self._on_devices(devices)

    def _handle_bridge_event(self, _client: object, _userdata: object, message: object) -> None:
        """Parse bridge/event JSON, map device_joined/device_leave to DeviceEvent"""
        data = _parse_json_payload(message, "bridge/event")
        if data is None:
            return
        event_type = data.get("type")
        device_data = data.get("data", {})
        event_map = {
            Z2MEventType.DEVICE_JOINED: DeviceEventType.JOINED,
            Z2MEventType.DEVICE_LEAVE: DeviceEventType.LEFT,
        }
        mapped = event_map.get(event_type)
        if mapped:
            self._on_device_event(
                DeviceEvent(
                    type=mapped,
                    name=_resolve_device_name(device_data),
                )
            )
        elif event_type == Z2MEventType.DEVICE_RENAMED:
            self._on_device_event(
                DeviceEvent(
                    type=DeviceEventType.RENAMED,
                    name=device_data.get("to", ""),
                    old_name=device_data.get("from", ""),
                )
            )

    def _handle_device_remove_response(self, _client: object, _userdata: object, message: object) -> None:
        """Parse bridge/response/device/remove, emit REMOVED event on success"""
        data = _parse_json_payload(message, "bridge/response/device/remove")
        if data is None:
            return
        if data.get("status") == "ok":
            name = data.get("data", {}).get("id", "")
            self._on_device_event(DeviceEvent(type=DeviceEventType.REMOVED, name=name))


def _parse_json_payload(message: object, topic_name: str) -> Optional[Union[dict, list]]:
    """Decode MQTT message payload as JSON. Returns None and logs warning on failure"""
    try:
        return json.loads(message.payload.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Failed to parse %s payload", topic_name)
        return None


def _is_safe_topic_segment(name: str) -> bool:
    """Check that a device name is safe to use in MQTT topic paths.

    Rejects names containing MQTT wildcard characters (+, #) that could
    cause subscription to unintended topics.
    """
    if not name:
        return False
    return not any(ch in name for ch in _MQTT_WILDCARD_CHARS)


def _resolve_device_name(device_data: dict) -> str:
    """Return friendly_name if meaningful, otherwise ieee_address"""
    friendly_name = device_data.get("friendly_name", "")
    ieee_address = device_data.get("ieee_address", "")
    has_meaningful_name = friendly_name and friendly_name != ieee_address
    return friendly_name if has_meaningful_name else ieee_address
