import json
import logging
from typing import Callable

from wb_common.mqtt_client import MQTTClient

from .controls import BRIDGE_CONTROLS, BridgeControl, ControlMeta

logger = logging.getLogger(__name__)

DEVICES_PREFIX = "/devices"
DRIVER_NAME = "wb-zigbee2mqtt"

_DEVICE_META_WILDCARD = f"{DEVICES_PREFIX}/+/meta"
_CONTROL_META_WILDCARD = f"{DEVICES_PREFIX}/+/controls/+/meta"


class WbPublisher:
    """Publishes virtual WB devices and controls according to Wiren Board MQTT Conventions"""

    def __init__(self, mqtt_client: MQTTClient, device_id: str, device_name: str) -> None:
        self._client = mqtt_client
        self._device_id = device_id
        self._device_name = device_name
        self._scanned_our_ids: set[str] = set()  # device_ids with our driver
        self._scanned_controls: dict[str, set[str]] = {}  # device_id → set of control_ids (all)

    def publish_bridge_device(self) -> None:
        self._publish_device(self._device_id, self._device_name, BRIDGE_CONTROLS)

    def publish_bridge_control(self, control_id: str, value: str) -> None:
        topic = f"{DEVICES_PREFIX}/{self._device_id}/controls/{control_id}"
        self._publish_retain(topic, value)

    def publish_device(self, device_id: str, name: str, controls: dict[str, ControlMeta]) -> None:
        self._publish_device(device_id, name, controls)

    def remove_device(self, device_id: str, controls: dict[str, ControlMeta]) -> None:
        """Remove a WB device by publishing empty retain on all its topics"""
        for control_id in controls:
            self._publish_retain(f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}/meta", "")
            self._publish_retain(f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}", "")
            self._clear_legacy_control_meta(device_id, control_id)
        self._publish_retain(f"{DEVICES_PREFIX}/{device_id}/meta", "")
        self._clear_legacy_device_meta(device_id)

    def remove_retained_device(self, device_id: str, control_ids: set[str]) -> None:
        """Remove a ghost device discovered via retained scan (no ControlMeta needed)"""
        for control_id in control_ids:
            self._publish_retain(f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}/meta", "")
            self._publish_retain(f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}", "")
            self._clear_legacy_control_meta(device_id, control_id)
        self._publish_retain(f"{DEVICES_PREFIX}/{device_id}/meta", "")
        self._clear_legacy_device_meta(device_id)

    def publish_device_control(self, device_id: str, control_id: str, value: str) -> None:
        topic = f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}"
        self._publish_retain(topic, value)

    # -- Retained device scan (ghost cleanup) ----------------------------------

    def start_retained_scan(self) -> None:
        """Subscribe to wildcard topics to discover retained devices with our driver."""
        self._scanned_our_ids.clear()
        self._scanned_controls.clear()
        self._client.subscribe(_DEVICE_META_WILDCARD)
        self._client.subscribe(_CONTROL_META_WILDCARD)
        self._client.message_callback_add(_DEVICE_META_WILDCARD, self._on_retained_device_meta)
        self._client.message_callback_add(_CONTROL_META_WILDCARD, self._on_retained_control_meta)

    def stop_retained_scan(self) -> None:
        """Unsubscribe from wildcard scan topics."""
        self._client.unsubscribe(_DEVICE_META_WILDCARD)
        self._client.unsubscribe(_CONTROL_META_WILDCARD)
        self._client.message_callback_remove(_DEVICE_META_WILDCARD)
        self._client.message_callback_remove(_CONTROL_META_WILDCARD)

    def get_scanned_device_ids(self) -> set[str]:
        """Return device_ids discovered during retained scan that have our driver.

        Excludes the bridge device itself (it is not a zigbee device).
        """
        return self._scanned_our_ids - {self._device_id}

    def get_scanned_controls(self, device_id: str) -> set[str]:
        """Return control_ids discovered for a given device_id."""
        return self._scanned_controls.get(device_id, set())

    def _on_retained_device_meta(self, _client: object, _userdata: object, message: object) -> None:
        """Callback for /devices/+/meta: collect device_ids with our driver."""
        payload = message.payload.decode("utf-8").strip()
        if not payload:
            return
        try:
            meta = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return
        if meta.get("driver") != DRIVER_NAME:
            return
        # topic: /devices/{device_id}/meta
        parts = message.topic.split("/")
        if len(parts) >= 3:
            self._scanned_our_ids.add(parts[2])

    def _on_retained_control_meta(self, _client: object, _userdata: object, message: object) -> None:
        """Callback for /devices/+/controls/+/meta: collect control_ids per device."""
        payload = message.payload.decode("utf-8").strip()
        if not payload:
            return
        # topic: /devices/{device_id}/controls/{control_id}/meta
        parts = message.topic.split("/")
        if len(parts) >= 5:
            device_id = parts[2]
            control_id = parts[4]
            if device_id not in self._scanned_controls:
                self._scanned_controls[device_id] = set()
            self._scanned_controls[device_id].add(control_id)

    # -- Bridge commands -------------------------------------------------------

    def subscribe_bridge_commands(
        self,
        on_permit_join: Callable[[bool], None],
        on_update_devices: Callable[[], None],
    ) -> None:
        permit_join_topic = f"{DEVICES_PREFIX}/{self._device_id}/controls/{BridgeControl.PERMIT_JOIN}/on"
        update_devices_topic = (
            f"{DEVICES_PREFIX}/{self._device_id}/controls/{BridgeControl.UPDATE_DEVICES}/on"
        )

        self._client.subscribe(permit_join_topic)
        self._client.subscribe(update_devices_topic)

        def handle_permit_join(_client: object, _userdata: object, message: object) -> None:
            value = message.payload.decode("utf-8").strip()
            on_permit_join(value == "1")

        def handle_update_devices(_client: object, _userdata: object, _message: object) -> None:
            on_update_devices()

        self._client.message_callback_add(permit_join_topic, handle_permit_join)
        self._client.message_callback_add(update_devices_topic, handle_update_devices)

    def subscribe_device_commands(
        self,
        device_id: str,
        controls: dict[str, ControlMeta],
        on_command: Callable[[str, str], None],
    ) -> None:
        """Subscribe to /on topics for writable controls.

        Args:
            device_id: WB device ID
            controls: device controls dict (property → ControlMeta)
            on_command: callback(control_id, wb_value) called when a command is received
        """
        for control_id, meta in controls.items():
            if meta.readonly:
                continue
            topic = f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}/on"
            self._client.subscribe(topic)
            self._client.message_callback_add(topic, _make_command_handler(control_id, on_command))
            logger.debug("Subscribed to device command: %s", topic)

    def unsubscribe_device_commands(self, device_id: str, controls: dict[str, ControlMeta]) -> None:
        """Unsubscribe from /on topics for writable controls"""
        for control_id, meta in controls.items():
            if meta.readonly:
                continue
            topic = f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}/on"
            self._client.unsubscribe(topic)
            self._client.message_callback_remove(topic)

    def _publish_device(self, device_id: str, name: str, controls: dict[str, ControlMeta]) -> None:
        device_meta = {"driver": DRIVER_NAME, "title": {"en": name, "ru": name}}
        self._publish_retain(f"{DEVICES_PREFIX}/{device_id}/meta", json.dumps(device_meta))
        self._clear_legacy_device_meta(device_id)
        for control_id, meta in controls.items():
            self._clear_legacy_control_meta(device_id, control_id)
            self._publish_control_meta(device_id, control_id, meta)
            self._publish_retain(f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}", " ")

    def _publish_control_meta(self, device_id: str, control_id: str, meta: ControlMeta) -> None:
        payload: dict = {"type": meta.type, "readonly": meta.readonly}
        if meta.order is not None:
            payload["order"] = meta.order
        if meta.title:
            payload["title"] = meta.title
        if meta.enum:
            payload["enum"] = meta.enum
        if meta.max is not None:
            payload["max"] = meta.max
        if meta.min is not None:
            payload["min"] = meta.min
        topic = f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}/meta"
        self._publish_retain(topic, json.dumps(payload))

    def _clear_legacy_device_meta(self, device_id: str) -> None:
        """Clear old wb-rules style device meta sub-topics (name, driver)"""
        prefix = f"{DEVICES_PREFIX}/{device_id}/meta"
        for sub in ("name", "driver"):
            self._publish_retain(f"{prefix}/{sub}", "")

    def _clear_legacy_control_meta(self, device_id: str, control_id: str) -> None:
        """Clear old wb-rules style control meta sub-topics (type, order, readonly)"""
        prefix = f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}/meta"
        for sub in ("type", "order", "readonly"):
            self._publish_retain(f"{prefix}/{sub}", "")

    def _publish_retain(self, topic: str, value: str) -> None:
        self._client.publish(topic, value, retain=True, qos=1)


def _make_command_handler(control_id: str, on_command: Callable[[str, str], None]):
    """Create MQTT message handler that extracts payload and calls on_command(control_id, value)"""

    def handler(_client: object, _userdata: object, message: object) -> None:
        value = message.payload.decode("utf-8").strip()
        on_command(control_id, value)

    return handler
