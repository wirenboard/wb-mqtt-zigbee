import logging
import time
from datetime import datetime

from wb_common.mqtt_client import MQTTClient

from .wb_converter.controls import BridgeControl
from .wb_converter.publisher import WbPublisher
from .z2m.client import Z2MClient
from .z2m.model import BridgeInfo, BridgeLogLevel, DeviceEvent, DeviceEventType

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
        )
        self._wb = WbPublisher(mqtt_client, device_id, device_name)
        self._bridge_log_min_level = bridge_log_min_level
        self._log_min_rank = BridgeLogLevel.RANK.get(bridge_log_min_level, BridgeLogLevel.RANK[BridgeLogLevel.WARNING])
        self._messages_received = 0
        self._last_stats_publish = 0.0

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

    def _on_devices(self, count: int) -> None:
        logger.info("Devices: %d", count)
        self._wb.publish_bridge_control(BridgeControl.DEVICE_COUNT, str(count))
        self._update_stats()

    def _on_device_event(self, event: DeviceEvent) -> None:
        logger.info("Device event: %s %s", event.type, event.name)
        control = _EVENT_TYPE_TO_CONTROL.get(event.type)
        if control:
            self._wb.publish_bridge_control(control, event.name)
        self._update_stats()
