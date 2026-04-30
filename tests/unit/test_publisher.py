"""Unit tests for wb.mqtt_zigbee.wb_converter.publisher.

Targeted coverage: only legacy DRIVER_NAME filtering in
``_on_retained_device_meta``. The publisher class as a whole is not
yet covered by unit tests — see docs/REFACTORING.md if/when that
gets prioritized.
"""

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock

# wb_common is a runtime-only dependency (system package, not in
# dev-requirements). Stub it before importing publisher so the test
# can run in a plain venv.
if "wb_common" not in sys.modules:
    wb_common = ModuleType("wb_common")
    wb_common_mqtt = ModuleType("wb_common.mqtt_client")
    wb_common_mqtt.MQTTClient = MagicMock  # type: ignore[attr-defined]
    sys.modules["wb_common"] = wb_common
    sys.modules["wb_common.mqtt_client"] = wb_common_mqtt

# pylint: disable=wrong-import-position
from paho.mqtt.client import MQTTMessage

from wb.mqtt_zigbee.wb_converter.publisher import DRIVER_NAME, LEGACY_DRIVER_NAMES, WbMqttDriver


def _make_meta_message(device_id: str, driver: str) -> MQTTMessage:
    msg = MQTTMessage(topic=f"/devices/{device_id}/meta".encode("utf-8"))
    msg.payload = json.dumps({"driver": driver}).encode("utf-8")
    return msg


class TestRetainedDeviceMetaFilter:
    """Ghost cleanup must recognize both current and legacy driver names.

    Otherwise retained meta published by older versions of the package
    (before the wb-zigbee2mqtt → wb-mqtt-zigbee rename, commit d37b3ad)
    stays in the broker forever after upgrade.
    """

    def _make_driver(self) -> WbMqttDriver:
        return WbMqttDriver(MagicMock(), device_id="bridge", device_name="Bridge")

    def test_current_driver_name_is_collected(self):
        driver = self._make_driver()
        driver._on_retained_device_meta(  # pylint: disable=protected-access
            None, None, _make_meta_message("dev1", DRIVER_NAME)
        )
        assert "dev1" in driver._scanned_our_ids  # pylint: disable=protected-access

    def test_legacy_driver_name_is_collected(self):
        driver = self._make_driver()
        for legacy_name in LEGACY_DRIVER_NAMES:
            driver._on_retained_device_meta(  # pylint: disable=protected-access
                None, None, _make_meta_message(f"dev-{legacy_name}", legacy_name)
            )
        scanned = driver._scanned_our_ids  # pylint: disable=protected-access
        for legacy_name in LEGACY_DRIVER_NAMES:
            assert f"dev-{legacy_name}" in scanned

    def test_unknown_driver_name_is_ignored(self):
        driver = self._make_driver()
        driver._on_retained_device_meta(  # pylint: disable=protected-access
            None, None, _make_meta_message("dev2", "some-other-driver")
        )
        assert not driver._scanned_our_ids  # pylint: disable=protected-access

    def test_empty_payload_is_ignored(self):
        driver = self._make_driver()
        msg = MQTTMessage(topic=b"/devices/dev3/meta")
        msg.payload = b""
        driver._on_retained_device_meta(None, None, msg)  # pylint: disable=protected-access
        assert not driver._scanned_our_ids  # pylint: disable=protected-access

    def test_invalid_json_is_ignored(self):
        driver = self._make_driver()
        msg = MQTTMessage(topic=b"/devices/dev4/meta")
        msg.payload = b"not json"
        driver._on_retained_device_meta(None, None, msg)  # pylint: disable=protected-access
        assert not driver._scanned_our_ids  # pylint: disable=protected-access
