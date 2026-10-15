"""Unit tests for wb.mqtt_zigbee.wb_converter.composite."""

from wb.mqtt_zigbee.wb_converter.composite import (
    command_payload,
    remember,
    state_values,
    stored_wb_values,
)
from wb.mqtt_zigbee.wb_converter.controls import ControlMeta, WbBoolValue, WbControlType


def switch(path: tuple[str, ...] = (), deferred: bool = False) -> ControlMeta:
    return ControlMeta(type=WbControlType.SWITCH, readonly=False, path=path, deferred=deferred)


def button(path: tuple[str, ...]) -> ControlMeta:
    return ControlMeta(type=WbControlType.PUSHBUTTON, readonly=False, path=path)


class TestStateValues:
    """Tests for ``state_values`` — picking control values out of a z2m state message."""

    def test_reads_top_level_and_nested_values(self):
        controls = {"state": switch(), "reversed": switch(("cover_mode", "reversed"))}
        state = {"state": True, "cover_mode": {"reversed": False}}

        assert list(state_values(controls, state)) == [
            ("state", controls["state"], True),
            ("reversed", controls["reversed"], False),
        ]

    def test_reads_composite_field_published_top_level(self):
        controls = {"away_preset_days": switch(("away_setting", "away_preset_days"))}

        assert [value for _id, _meta, value in state_values(controls, {"away_preset_days": 3})] == [3]

    def test_prefixed_field_is_not_read_from_top_level(self):
        controls = {"cover_mode_led": switch(("cover_mode", "led"))}

        assert not list(state_values(controls, {"led": True}))

    def test_flat_fallback_ignores_the_composite_object_itself(self):
        controls = {"pin_code": switch(("pin_code", "pin_code"))}

        assert not list(state_values(controls, {"pin_code": {"user": 1}}))

    def test_reads_deferred_fields_and_skips_buttons_service_keys_and_skip_ids(self):
        controls = {
            "ssid": switch(("wifi_config", "ssid"), deferred=True),
            "password": switch(("wifi_config", "password"), deferred=True),
            "wifi_config": button(("wifi_config",)),
            "last_seen": switch(),
        }
        state = {"wifi_config": {"ssid": "home", "password": "x"}, "last_seen": 1}

        assert [cid for cid, _meta, _value in state_values(controls, state, skip={"password"})] == ["ssid"]


class TestCommandPayload:
    """Tests for ``command_payload`` — building the z2m /set payload for a WB command."""

    def test_top_level_control_sends_its_value(self):
        assert command_payload("state", switch(), WbBoolValue.TRUE, {}) == {"state": True}

    def test_composite_field_sends_whole_object_and_stores_value(self):
        values = {"cover_mode": {"reversed": False, "led": True}}

        payload = command_payload("reversed", switch(("cover_mode", "reversed")), WbBoolValue.TRUE, values)

        assert payload == {"cover_mode": {"reversed": True, "led": True}}
        assert values == payload

    def test_deferred_field_is_only_stored(self):
        values: dict = {}

        payload = command_payload(
            "strobe", switch(("warning", "strobe"), deferred=True), WbBoolValue.TRUE, values
        )

        assert payload is None
        assert values == {"warning": {"strobe": True}}

    def test_button_sends_stored_fields(self):
        values = {"warning": {"strobe": True}}

        assert command_payload("warning", button(("warning",)), WbBoolValue.TRUE, values) == {
            "warning": {"strobe": True}
        }

    def test_button_without_stored_fields_sends_empty_object(self):
        assert command_payload("warning", button(("warning",)), WbBoolValue.TRUE, {}) == {"warning": {}}


class TestStoredWbValues:
    """Tests for ``stored_wb_values`` — restoring composite field values in WB form."""

    def test_formats_known_fields_and_skips_buttons(self):
        controls = {
            "strobe": switch(("warning", "strobe"), deferred=True),
            "level": switch(("warning", "level"), deferred=True),
            "warning": button(("warning",)),
        }
        values: dict = {}
        remember(values, controls["strobe"], True)

        assert stored_wb_values(controls, values) == {"strobe": WbBoolValue.TRUE}
