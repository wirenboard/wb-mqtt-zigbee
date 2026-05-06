"""
Integration tests for `wb.mqtt_zigbee.wb_converter.publisher.WbMqttDriver`.

Wires WbMqttDriver to a FakeMqttClient/FakeMqttBroker and asserts the
Wiren Board MQTT Conventions topic/payload shape: every meta is published
with `retain=True, qos=1`, removals erase retained state, and the retained
ghost-device scan correctly recognises devices owned by our driver.
"""

import json
from typing import Optional

from wb.mqtt_zigbee.wb_converter.controls import (
    BRIDGE_CONTROLS,
    BridgeControl,
    ControlMeta,
    WbBoolValue,
    WbControlType,
)
from wb.mqtt_zigbee.wb_converter.publisher import (
    DEVICES_PREFIX,
    DRIVER_NAME,
    WbMqttDriver,
)

from .fakes.broker import FakeMqttBroker
from .fakes.client import FakeMqttClient
from .helpers.wb_observer import WbObserver

BRIDGE_ID = "zigbee2mqtt"
BRIDGE_NAME = "Zigbee2MQTT bridge"


def _make_driver(fake_mqtt_client: FakeMqttClient) -> WbMqttDriver:
    return WbMqttDriver(
        mqtt_client=fake_mqtt_client,
        device_id=BRIDGE_ID,
        device_name=BRIDGE_NAME,
    )


def _sample_controls() -> dict[str, ControlMeta]:
    return {
        "temperature": ControlMeta(
            type=WbControlType.TEMPERATURE,
            readonly=True,
            order=1,
            title={"en": "Temperature", "ru": "Температура"},
        ),
        "switch": ControlMeta(
            type=WbControlType.SWITCH,
            readonly=False,
            order=2,
            title={"en": "Switch", "ru": "Переключатель"},
            value_on="ON",
            value_off="OFF",
        ),
    }


def _our_device_meta(name: Optional[str] = "X") -> str:
    return json.dumps({"driver": DRIVER_NAME, "title": {"en": name, "ru": name}})


def _foreign_device_meta() -> str:
    return json.dumps({"driver": "some-other-driver", "title": {"en": "X", "ru": "X"}})


class TestPublishBridgeDevice:
    """
    `publish_bridge_device()` initial meta + controls
    """

    def test_publishes_device_meta(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        _make_driver(fake_mqtt_client).publish_bridge_device()
        meta = wb_observer.last_json_on(f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta")
        assert meta == {"driver": DRIVER_NAME, "title": {"en": BRIDGE_NAME, "ru": BRIDGE_NAME}}

    def test_publishes_all_bridge_controls(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        _make_driver(fake_mqtt_client).publish_bridge_device()
        for control_id in BRIDGE_CONTROLS:
            topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{control_id}/meta"
            assert wb_observer.retained(topic) is not None, f"missing meta for {control_id}"

    def test_initial_value_is_blank(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        _make_driver(fake_mqtt_client).publish_bridge_device()
        topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.STATE}"
        assert wb_observer.retained(topic) == " "

    def test_all_meta_publishes_use_retain_qos1(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        _make_driver(fake_mqtt_client).publish_bridge_device()
        for msg in wb_observer.all_messages():
            assert msg.retain is True, msg.topic
            assert msg.qos == 1, msg.topic


class TestPublishBridgeControl:
    """
    `publish_bridge_control()` writes a value to the bridge control topic
    """

    def test_writes_value(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        driver = _make_driver(fake_mqtt_client)
        driver.publish_bridge_control(BridgeControl.STATE, "online")
        topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.STATE}"
        assert wb_observer.retained(topic) == "online"


class TestPublishDevice:
    """
    `publish_device()` for non-bridge devices
    """

    def test_writes_device_and_control_meta(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        driver = _make_driver(fake_mqtt_client)
        driver.publish_device("0x123", "Living room sensor", _sample_controls())

        device_meta = wb_observer.last_json_on(f"{DEVICES_PREFIX}/0x123/meta")
        assert device_meta == {
            "driver": DRIVER_NAME,
            "title": {"en": "Living room sensor", "ru": "Living room sensor"},
        }
        temp_meta = wb_observer.last_json_on(f"{DEVICES_PREFIX}/0x123/controls/temperature/meta")
        assert isinstance(temp_meta, dict)
        assert temp_meta["type"] == WbControlType.TEMPERATURE
        assert temp_meta["readonly"] is True
        assert temp_meta["order"] == 1

    def test_with_initial_values_uses_them(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        driver = _make_driver(fake_mqtt_client)
        driver.publish_device(
            "0x123",
            "S",
            _sample_controls(),
            initial_values={"temperature": "21.5", "switch": WbBoolValue.TRUE},
        )
        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x123/controls/temperature") == "21.5"
        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x123/controls/switch") == WbBoolValue.TRUE

    def test_without_initial_values_uses_blank(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        driver = _make_driver(fake_mqtt_client)
        driver.publish_device("0x123", "S", _sample_controls())
        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x123/controls/temperature") == " "

    def test_clears_legacy_meta_subtopics(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        driver = _make_driver(fake_mqtt_client)
        driver.publish_device("0x123", "S", _sample_controls())
        topics = wb_observer.topics()
        assert f"{DEVICES_PREFIX}/0x123/meta/name" in topics
        assert f"{DEVICES_PREFIX}/0x123/meta/driver" in topics
        assert f"{DEVICES_PREFIX}/0x123/controls/temperature/meta/type" in topics
        assert f"{DEVICES_PREFIX}/0x123/controls/temperature/meta/readonly" in topics

    def test_publish_device_control_writes_value(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        driver = _make_driver(fake_mqtt_client)
        driver.publish_device_control("0x123", "temperature", "22.4")
        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x123/controls/temperature") == "22.4"


class TestRemoveDevice:
    """
    `remove_device()` and `remove_retained_device()`
    """

    def test_remove_device_clears_retained_state(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        controls = _sample_controls()
        driver = _make_driver(fake_mqtt_client)
        driver.publish_device("0x123", "S", controls, initial_values={"temperature": "21"})
        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x123/meta") is not None

        driver.remove_device("0x123", controls)

        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x123/meta") is None
        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x123/controls/temperature/meta") is None
        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x123/controls/temperature") is None
        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x123/controls/switch") is None

    def test_remove_retained_device_clears_by_control_ids(
        self,
        fake_mqtt_client: FakeMqttClient,
        wb_observer: WbObserver,
    ) -> None:
        controls = _sample_controls()
        driver = _make_driver(fake_mqtt_client)
        driver.publish_device("0x456", "S", controls)

        driver.remove_retained_device("0x456", {"temperature", "switch"})

        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x456/meta") is None
        assert wb_observer.retained(f"{DEVICES_PREFIX}/0x456/controls/temperature") is None


class TestSubscribeBridgeCommands:
    """
    `subscribe_bridge_commands()` topic wiring and dispatch
    """

    def test_subscribes_topics(
        self,
        fake_mqtt_client: FakeMqttClient,
    ) -> None:
        driver = _make_driver(fake_mqtt_client)
        driver.subscribe_bridge_commands(on_permit_join=lambda _: None, on_update_devices=lambda: None)
        permit_join = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.PERMIT_JOIN}/on"
        update_devices = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.UPDATE_DEVICES}/on"
        assert permit_join in fake_mqtt_client.subscriptions
        assert update_devices in fake_mqtt_client.subscriptions

    def test_permit_join_command_dispatches_bool(
        self,
        fake_mqtt_client: FakeMqttClient,
        fake_broker: FakeMqttBroker,
    ) -> None:
        received: list[bool] = []
        driver = _make_driver(fake_mqtt_client)
        driver.subscribe_bridge_commands(on_permit_join=received.append, on_update_devices=lambda: None)
        topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.PERMIT_JOIN}/on"

        fake_broker.inject(topic, WbBoolValue.TRUE)
        fake_broker.inject(topic, WbBoolValue.FALSE)

        assert received == [True, False]

    def test_update_devices_command_dispatches(
        self,
        fake_mqtt_client: FakeMqttClient,
        fake_broker: FakeMqttBroker,
    ) -> None:
        calls: list[None] = []
        driver = _make_driver(fake_mqtt_client)
        driver.subscribe_bridge_commands(
            on_permit_join=lambda _: None,
            on_update_devices=lambda: calls.append(None),
        )
        topic = f"{DEVICES_PREFIX}/{BRIDGE_ID}/controls/{BridgeControl.UPDATE_DEVICES}/on"

        fake_broker.inject(topic, "1")

        assert len(calls) == 1


class TestSubscribeDeviceCommands:
    """
    `subscribe_device_commands()` and the matching `unsubscribe_device_commands()`
    """

    def test_skips_readonly(
        self,
        fake_mqtt_client: FakeMqttClient,
    ) -> None:
        controls = _sample_controls()
        driver = _make_driver(fake_mqtt_client)
        driver.subscribe_device_commands("0x123", controls, on_command=lambda _c, _v: None)
        subs = fake_mqtt_client.subscriptions
        assert f"{DEVICES_PREFIX}/0x123/controls/switch/on" in subs
        assert f"{DEVICES_PREFIX}/0x123/controls/temperature/on" not in subs

    def test_dispatches_control_id_and_value(
        self,
        fake_mqtt_client: FakeMqttClient,
        fake_broker: FakeMqttBroker,
    ) -> None:
        received: list[tuple[str, str]] = []
        driver = _make_driver(fake_mqtt_client)
        driver.subscribe_device_commands(
            "0x123",
            _sample_controls(),
            on_command=lambda control_id, value: received.append((control_id, value)),
        )

        fake_broker.inject(f"{DEVICES_PREFIX}/0x123/controls/switch/on", WbBoolValue.TRUE)

        assert received == [("switch", WbBoolValue.TRUE)]

    def test_unsubscribe_removes_only_writable(
        self,
        fake_mqtt_client: FakeMqttClient,
    ) -> None:
        controls = _sample_controls()
        driver = _make_driver(fake_mqtt_client)
        driver.subscribe_device_commands("0x123", controls, on_command=lambda _c, _v: None)
        driver.unsubscribe_device_commands("0x123", controls)
        assert f"{DEVICES_PREFIX}/0x123/controls/switch/on" in fake_mqtt_client.unsubscriptions
        assert f"{DEVICES_PREFIX}/0x123/controls/temperature/on" not in fake_mqtt_client.unsubscriptions

    def test_handler_does_not_fire_after_unsubscribe(
        self,
        fake_mqtt_client: FakeMqttClient,
        fake_broker: FakeMqttBroker,
    ) -> None:
        received: list[tuple[str, str]] = []
        controls = _sample_controls()
        driver = _make_driver(fake_mqtt_client)
        driver.subscribe_device_commands(
            "0x123",
            controls,
            on_command=lambda control_id, value: received.append((control_id, value)),
        )
        driver.unsubscribe_device_commands("0x123", controls)

        fake_broker.inject(f"{DEVICES_PREFIX}/0x123/controls/switch/on", WbBoolValue.TRUE)

        assert not received


class TestRetainedScan:
    """
    `start_retained_scan()` / `stop_retained_scan()` ghost-device discovery
    """

    def test_collects_only_our_driver_devices(
        self,
        fake_mqtt_client: FakeMqttClient,
        fake_broker: FakeMqttBroker,
    ) -> None:
        fake_broker.inject(f"{DEVICES_PREFIX}/0xours/meta", _our_device_meta(), retain=True)
        fake_broker.inject(
            f"{DEVICES_PREFIX}/0xours/controls/temp/meta", json.dumps({"type": "temperature"}), retain=True
        )
        fake_broker.inject(f"{DEVICES_PREFIX}/0xforeign/meta", _foreign_device_meta(), retain=True)
        fake_broker.inject(f"{DEVICES_PREFIX}/0xforeign/controls/x/meta", "{}", retain=True)

        driver = _make_driver(fake_mqtt_client)
        driver.start_retained_scan()

        assert driver.get_scanned_device_ids() == {"0xours"}

    def test_excludes_bridge_device(
        self,
        fake_mqtt_client: FakeMqttClient,
        fake_broker: FakeMqttBroker,
    ) -> None:
        fake_broker.inject(f"{DEVICES_PREFIX}/{BRIDGE_ID}/meta", _our_device_meta(BRIDGE_NAME), retain=True)
        fake_broker.inject(f"{DEVICES_PREFIX}/0xours/meta", _our_device_meta(), retain=True)

        driver = _make_driver(fake_mqtt_client)
        driver.start_retained_scan()

        assert driver.get_scanned_device_ids() == {"0xours"}

    def test_collects_per_device_controls(
        self,
        fake_mqtt_client: FakeMqttClient,
        fake_broker: FakeMqttBroker,
    ) -> None:
        fake_broker.inject(f"{DEVICES_PREFIX}/0xours/meta", _our_device_meta(), retain=True)
        fake_broker.inject(f"{DEVICES_PREFIX}/0xours/controls/a/meta", "{}", retain=True)
        fake_broker.inject(f"{DEVICES_PREFIX}/0xours/controls/b/meta", "{}", retain=True)

        driver = _make_driver(fake_mqtt_client)
        driver.start_retained_scan()

        assert driver.get_scanned_controls("0xours") == {"a", "b"}

    def test_ignores_invalid_meta_payloads(
        self,
        fake_mqtt_client: FakeMqttClient,
        fake_broker: FakeMqttBroker,
    ) -> None:
        fake_broker.inject(f"{DEVICES_PREFIX}/0xbroken/meta", "not-json", retain=True)
        fake_broker.inject(f"{DEVICES_PREFIX}/0xempty/meta", "", retain=True)

        driver = _make_driver(fake_mqtt_client)
        driver.start_retained_scan()

        assert driver.get_scanned_device_ids() == set()

    def test_stop_unsubscribes_wildcards(
        self,
        fake_mqtt_client: FakeMqttClient,
    ) -> None:
        driver = _make_driver(fake_mqtt_client)
        driver.start_retained_scan()
        driver.stop_retained_scan()
        assert f"{DEVICES_PREFIX}/+/meta" in fake_mqtt_client.unsubscriptions
        assert f"{DEVICES_PREFIX}/+/controls/+/meta" in fake_mqtt_client.unsubscriptions

    def test_start_resets_previous_state(
        self,
        fake_mqtt_client: FakeMqttClient,
        fake_broker: FakeMqttBroker,
    ) -> None:
        fake_broker.inject(f"{DEVICES_PREFIX}/0xfirst/meta", _our_device_meta(), retain=True)
        driver = _make_driver(fake_mqtt_client)
        driver.start_retained_scan()
        assert driver.get_scanned_device_ids() == {"0xfirst"}

        driver.stop_retained_scan()
        fake_broker.retained.pop(f"{DEVICES_PREFIX}/0xfirst/meta", None)
        fake_broker.inject(f"{DEVICES_PREFIX}/0xsecond/meta", _our_device_meta(), retain=True)
        driver.start_retained_scan()

        assert driver.get_scanned_device_ids() == {"0xsecond"}
