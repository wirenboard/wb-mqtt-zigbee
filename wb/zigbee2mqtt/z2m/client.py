import json
import logging
from typing import Callable, Optional

from wb_common.mqtt_client import MQTTClient

from .model import BridgeInfo, BridgeState

logger = logging.getLogger(__name__)

PERMIT_JOIN_TIME_SEC = 254
PERMIT_JOIN_TIME_SEC_DISABLED = 0


class Z2MClient:
    """Subscribes to zigbee2mqtt MQTT topics and parses incoming messages into typed callbacks"""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        mqtt_client: MQTTClient,
        base_topic: str,
        on_bridge_state: Callable[[str], None],
        on_bridge_info: Callable[[BridgeInfo], None],
        on_bridge_log: Callable[[str], None],
    ) -> None:
        self._client = mqtt_client
        self._base_topic = base_topic
        self._on_bridge_state = on_bridge_state
        self._on_bridge_info = on_bridge_info
        self._on_bridge_log = on_bridge_log

    def subscribe(self) -> None:
        state_topic = f"{self._base_topic}/bridge/state"
        info_topic = f"{self._base_topic}/bridge/info"
        log_topic = f"{self._base_topic}/bridge/logging"

        self._client.subscribe(state_topic)
        self._client.subscribe(info_topic)
        self._client.subscribe(log_topic)

        self._client.message_callback_add(state_topic, self._handle_bridge_state)
        self._client.message_callback_add(info_topic, self._handle_bridge_info)
        self._client.message_callback_add(log_topic, self._handle_bridge_log)

    def set_permit_join(self, enabled: bool) -> None:
        time = PERMIT_JOIN_TIME_SEC if enabled else PERMIT_JOIN_TIME_SEC_DISABLED
        payload = json.dumps({"time": time})
        self._client.publish(f"{self._base_topic}/bridge/request/permit_join", payload)

    def request_devices_update(self) -> None:
        self._client.publish(f"{self._base_topic}/bridge/request/devices/get", "{}")

    def _handle_bridge_state(self, _client: object, _userdata: object, message: object) -> None:
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
        try:
            data = json.loads(message.payload.decode("utf-8"))
        except json.JSONDecodeError:
            logger.warning("Failed to parse bridge/info payload")
            return

        info = BridgeInfo(
            version=data.get("version", ""),
            permit_join=data.get("permit_join", False),
            permit_join_end=data.get("permit_join_end"),
            log_level=data.get("log_level", ""),
        )
        self._on_bridge_info(info)

    def _handle_bridge_log(self, _client: object, _userdata: object, message: object) -> None:
        try:
            data = json.loads(message.payload.decode("utf-8"))
            log_message: Optional[str] = data.get("message", "")
        except json.JSONDecodeError:
            log_message = message.payload.decode("utf-8")
        self._on_bridge_log(log_message or "")
