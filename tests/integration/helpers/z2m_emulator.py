"""
Z2mEmulator — facade for publishing z2m-shaped messages onto the fake broker.

Tests use this instead of constructing topic strings and JSON payloads inline.
"""

import json
from typing import Any, Optional

from ..fakes.broker import FakeMqttBroker


class Z2mEmulator:
    """
    Publishes messages on the topics that real zigbee2mqtt would use
    """

    def __init__(self, broker: FakeMqttBroker, base_topic: str = "zigbee2mqtt") -> None:
        self._broker = broker
        self._base = base_topic

    @property
    def base_topic(self) -> str:
        return self._base

    # bridge/state
    def online(self) -> None:
        self._broker.inject(f"{self._base}/bridge/state", "online", retain=True)

    def offline(self) -> None:
        self._broker.inject(f"{self._base}/bridge/state", "offline", retain=True)

    def state_raw(self, payload: Any, retain: bool = True) -> None:
        self._broker.inject(f"{self._base}/bridge/state", payload, retain=retain)

    # bridge/info
    def info(
        self,
        version: str = "2.0.0",
        permit_join: bool = False,
        permit_join_end: Optional[int] = None,
    ) -> None:
        payload = {"version": version, "permit_join": permit_join, "permit_join_end": permit_join_end}
        self._broker.inject(f"{self._base}/bridge/info", json.dumps(payload), retain=True)

    def info_raw(self, payload: Any, retain: bool = True) -> None:
        self._broker.inject(f"{self._base}/bridge/info", payload, retain=retain)

    # bridge/logging
    def log(self, level: str, message: str) -> None:
        payload = {"level": level, "message": message}
        self._broker.inject(f"{self._base}/bridge/logging", json.dumps(payload))

    def log_raw(self, payload: Any) -> None:
        self._broker.inject(f"{self._base}/bridge/logging", payload)

    # bridge/devices
    def devices(self, devices: list[dict]) -> None:
        self._broker.inject(f"{self._base}/bridge/devices", json.dumps(devices), retain=True)

    def devices_raw(self, payload: Any, retain: bool = True) -> None:
        self._broker.inject(f"{self._base}/bridge/devices", payload, retain=retain)

    # bridge/event
    def event(self, event_type: str, data: dict) -> None:
        payload = {"type": event_type, "data": data}
        self._broker.inject(f"{self._base}/bridge/event", json.dumps(payload))

    def event_raw(self, payload: Any) -> None:
        self._broker.inject(f"{self._base}/bridge/event", payload)

    def device_joined(self, friendly_name: str, ieee_address: str = "") -> None:
        self.event(
            "device_joined", {"friendly_name": friendly_name, "ieee_address": ieee_address or friendly_name}
        )

    def device_left(self, friendly_name: str, ieee_address: str = "") -> None:
        self.event(
            "device_leave", {"friendly_name": friendly_name, "ieee_address": ieee_address or friendly_name}
        )

    def device_renamed(self, from_name: str, to_name: str, ieee_address: str = "") -> None:
        data: dict[str, Any] = {"from": from_name, "to": to_name}
        if ieee_address:
            data["ieee_address"] = ieee_address
        self.event("device_renamed", data)

    # bridge/response/device/remove
    def remove_response(self, status: str = "ok", id_: str = "device-1") -> None:
        payload = {"status": status, "data": {"id": id_}}
        self._broker.inject(f"{self._base}/bridge/response/device/remove", json.dumps(payload))

    # per-device topics
    def device_state(self, friendly_name: str, state: dict) -> None:
        self._broker.inject(f"{self._base}/{friendly_name}", json.dumps(state))

    def device_state_raw(self, friendly_name: str, payload: Any) -> None:
        self._broker.inject(f"{self._base}/{friendly_name}", payload)

    def device_availability(self, friendly_name: str, online: bool) -> None:
        payload = {"state": "online" if online else "offline"}
        self._broker.inject(f"{self._base}/{friendly_name}/availability", json.dumps(payload), retain=True)

    def device_availability_raw(self, friendly_name: str, payload: Any, retain: bool = True) -> None:
        self._broker.inject(f"{self._base}/{friendly_name}/availability", payload, retain=retain)


__all__ = ["Z2mEmulator"]
