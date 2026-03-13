import logging
from typing import Callable

from wb_common.mqtt_client import MQTTClient

from .controls import BRIDGE_CONTROLS, BridgeControl, ControlMeta

logger = logging.getLogger(__name__)

DEVICES_PREFIX = "/devices"


class WbPublisher:
    """Publishes virtual WB devices and controls according to Wiren Board MQTT Conventions."""

    def __init__(self, mqtt_client: MQTTClient, device_id: str, device_name: str) -> None:
        self._client = mqtt_client
        self._device_id = device_id
        self._device_name = device_name

    def publish_bridge_device(self) -> None:
        self._publish_device(self._device_id, self._device_name, BRIDGE_CONTROLS)

    def publish_bridge_control(self, control_id: str, value: str) -> None:
        topic = f"{DEVICES_PREFIX}/{self._device_id}/controls/{control_id}"
        self._publish_retain(topic, value)

    def subscribe_bridge_commands(
        self,
        on_permit_join: Callable[[bool], None],
        on_update_devices: Callable[[], None],
    ) -> None:
        permit_join_topic = f"{DEVICES_PREFIX}/{self._device_id}/controls/{BridgeControl.PERMIT_JOIN}/on"
        update_devices_topic = f"{DEVICES_PREFIX}/{self._device_id}/controls/{BridgeControl.UPDATE_DEVICES}/on"

        self._client.subscribe(permit_join_topic)
        self._client.subscribe(update_devices_topic)

        def handle_permit_join(_client: object, _userdata: object, message: object) -> None:
            value = message.payload.decode("utf-8").strip()
            on_permit_join(value == "1")

        def handle_update_devices(_client: object, _userdata: object, _message: object) -> None:
            on_update_devices()

        self._client.message_callback_add(permit_join_topic, handle_permit_join)
        self._client.message_callback_add(update_devices_topic, handle_update_devices)

    def _publish_device(self, device_id: str, name: str, controls: dict[str, ControlMeta]) -> None:
        self._publish_retain(f"{DEVICES_PREFIX}/{device_id}/meta/name", name)
        for control_id, meta in controls.items():
            self._publish_control_meta(device_id, control_id, meta)

    def _publish_control_meta(self, device_id: str, control_id: str, meta: ControlMeta) -> None:
        prefix = f"{DEVICES_PREFIX}/{device_id}/controls/{control_id}/meta"
        self._publish_retain(f"{prefix}/type", meta.type)
        self._publish_retain(f"{prefix}/readonly", "1" if meta.readonly else "0")
        if meta.title:
            self._publish_retain(f"{prefix}/title", meta.title)
        if meta.order:
            self._publish_retain(f"{prefix}/order", str(meta.order))

    def _publish_retain(self, topic: str, value: str) -> None:
        self._client.publish(topic, value, retain=True, qos=1)
