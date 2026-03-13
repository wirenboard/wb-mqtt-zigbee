import logging

from wb_common.mqtt_client import MQTTClient

from .wb_converter.controls import BridgeControl
from .wb_converter.publisher import WbPublisher
from .z2m.client import Z2MClient
from .z2m.model import BridgeInfo

logger = logging.getLogger(__name__)


class Bridge:
    """Orchestrates data flow between zigbee2mqtt and the Wiren Board MQTT broker.

    Subscribes to z2m bridge topics, converts events to WB control updates,
    and forwards WB commands back to zigbee2mqtt.
    """

    def __init__(self, mqtt_client: MQTTClient, base_topic: str, device_id: str, device_name: str) -> None:
        self._z2m = Z2MClient(
            mqtt_client=mqtt_client,
            base_topic=base_topic,
            on_bridge_state=self._on_bridge_state,
            on_bridge_info=self._on_bridge_info,
            on_bridge_log=self._on_bridge_log,
        )
        self._wb = WbPublisher(mqtt_client, device_id, device_name)

    def subscribe(self) -> None:
        self._wb.publish_bridge_device()
        self._z2m.subscribe()
        self._wb.subscribe_bridge_commands(
            on_permit_join=self._z2m.set_permit_join,
            on_update_devices=self._z2m.request_devices_update,
        )

    def republish(self) -> None:
        self._wb.publish_bridge_device()

    def _on_bridge_state(self, state: str) -> None:
        logger.info("Bridge state: %s", state)
        self._wb.publish_bridge_control(BridgeControl.STATE, state)

    def _on_bridge_info(self, info: BridgeInfo) -> None:
        logger.info("Bridge info: version=%s, permit_join=%s", info.version, info.permit_join)
        self._wb.publish_bridge_control(BridgeControl.VERSION, info.version)
        self._wb.publish_bridge_control(BridgeControl.LOG_LEVEL, info.log_level)
        self._wb.publish_bridge_control(BridgeControl.PERMIT_JOIN, "1" if info.permit_join else "0")

    def _on_bridge_log(self, message: str) -> None:
        self._wb.publish_bridge_control(BridgeControl.LOG, message)
