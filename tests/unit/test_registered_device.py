"""Unit tests for wb.mqtt_zigbee.registered_device."""

from wb.mqtt_zigbee.registered_device import PendingCommand, RegisteredDevice
from wb.mqtt_zigbee.wb_converter.controls import ControlMeta, WbControlType
from wb.mqtt_zigbee.z2m.model import Z2MDevice


def make_z2m_device(ieee="0x1", name="dev"):
    return Z2MDevice(ieee_address=ieee, friendly_name=name, type="EndDevice")


def make_control(ctype=WbControlType.VALUE, readonly=True):
    return ControlMeta(type=ctype, readonly=readonly)


class TestPendingCommand:
    def test_construction_stores_fields(self):
        pc = PendingCommand(wb_value="1", timestamp=123.456)
        assert pc.wb_value == "1"
        assert pc.timestamp == 123.456

    def test_equality(self):
        a = PendingCommand(wb_value="1", timestamp=1.0)
        b = PendingCommand(wb_value="1", timestamp=1.0)
        c = PendingCommand(wb_value="0", timestamp=1.0)
        assert a == b
        assert a != c


class TestRegisteredDevice:
    def test_minimal_construction_uses_defaults(self):
        z2m = make_z2m_device()
        rd = RegisteredDevice(z2m=z2m, controls={"temp": make_control()}, device_id="dev_01")
        assert rd.z2m is z2m
        assert rd.device_id == "dev_01"
        assert "temp" in rd.controls
        assert not rd.pending_commands
        assert rd.availability_received is False

    def test_pending_commands_factory_isolated_per_instance(self):
        a = RegisteredDevice(z2m=make_z2m_device("0x1"), controls={}, device_id="a")
        b = RegisteredDevice(z2m=make_z2m_device("0x2"), controls={}, device_id="b")
        a.pending_commands["state"] = PendingCommand(wb_value="1", timestamp=10.0)
        assert not b.pending_commands

    def test_can_override_availability_and_pending(self):
        rd = RegisteredDevice(
            z2m=make_z2m_device(),
            controls={},
            device_id="x",
            pending_commands={"state": PendingCommand(wb_value="1", timestamp=5.0)},
            availability_received=True,
        )
        assert rd.availability_received is True
        assert rd.pending_commands["state"].wb_value == "1"

    def test_controls_dict_stored_by_reference(self):
        controls = {"temp": make_control()}
        rd = RegisteredDevice(z2m=make_z2m_device(), controls=controls, device_id="x")
        controls["humidity"] = make_control()
        assert "humidity" in rd.controls
