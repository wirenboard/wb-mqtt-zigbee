"""Unit tests for wb.mqtt_zigbee.wb_converter.composite."""

from wb.mqtt_zigbee.wb_converter.composite import Command, CompositeState
from wb.mqtt_zigbee.wb_converter.controls import ControlMeta, WbBoolValue, WbControlType


def make_switch(path: tuple[str, ...] = (), deferred: bool = False) -> ControlMeta:
    return ControlMeta(type=WbControlType.SWITCH, readonly=False, path=path, deferred=deferred)


def make_button(path: tuple[str, ...]) -> ControlMeta:
    return ControlMeta(type=WbControlType.PUSHBUTTON, readonly=False, path=path)


COVER_MODE = {
    "reversed": make_switch(("cover_mode", "reversed")),
    "led": make_switch(("cover_mode", "led")),
}
WARNING = {
    "strobe": make_switch(("warning", "strobe"), deferred=True),
    "level": make_switch(("warning", "level"), deferred=True),
    "warning": make_button(("warning",)),
}


def receive(composites: CompositeState, controls: dict[str, ControlMeta], state: dict) -> CompositeState:
    """Process a z2m state message the way the bridge does."""
    for _cid, meta, value in composites.state_values(controls, state):
        composites.observe(meta, value)
    return composites


class TestStateValues:
    """Tests for ``CompositeState.state_values`` — picking control values out of a z2m state message."""

    def test_reads_top_level_and_nested_values(self):
        controls = {"state": make_switch(), **COVER_MODE}
        state = {"state": True, "cover_mode": {"reversed": False}}

        assert list(CompositeState().state_values(controls, state)) == [
            ("state", controls["state"], True),
            ("reversed", controls["reversed"], False),
        ]

    def test_reads_composite_field_published_top_level(self):
        controls = {"away_preset_days": make_switch(("away_setting", "away_preset_days"))}

        values = [v for _id, _meta, v in CompositeState().state_values(controls, {"away_preset_days": 3})]
        assert values == [3]

    def test_prefixed_field_is_not_read_from_top_level(self):
        controls = {"cover_mode_led": make_switch(("cover_mode", "led"))}

        assert not list(CompositeState().state_values(controls, {"cover_mode_led": True}))

    def test_flat_fallback_ignores_the_composite_object_itself(self):
        controls = {"pin_code": make_switch(("pin_code", "pin_code"))}

        assert not list(CompositeState().state_values(controls, {"pin_code": {"user": 1}}))

    def test_composite_object_that_is_not_a_dict_is_skipped(self):
        assert not list(CompositeState().state_values(COVER_MODE, {"cover_mode": None}))

    def test_skips_buttons_service_keys_and_unsent_edits(self):
        controls = {**WARNING, "last_seen": make_switch()}
        composites = CompositeState(edits={"level"})
        state = {"warning": {"strobe": True, "level": "high"}, "last_seen": 1}

        assert [cid for cid, _meta, _value in composites.state_values(controls, state)] == ["strobe"]


class TestEdit:
    """Tests for ``CompositeState.edit`` — what a WB command turns into."""

    def test_top_level_control_sends_its_value(self):
        controls = {"state": make_switch()}

        assert CompositeState().edit("state", controls["state"], WbBoolValue.TRUE, controls) == Command(
            payload={"state": True}
        )

    def test_field_of_received_composite_sends_whole_object(self):
        composites = receive(CompositeState(), COVER_MODE, {"cover_mode": {"reversed": False, "led": True}})

        command = composites.edit("reversed", COVER_MODE["reversed"], WbBoolValue.TRUE, COVER_MODE)

        assert command == Command(payload={"cover_mode": {"reversed": True, "led": True}})
        assert not composites.edits

    def test_field_of_composite_not_received_yet_requests_it(self):
        composites = CompositeState()

        command = composites.edit("reversed", COVER_MODE["reversed"], WbBoolValue.TRUE, COVER_MODE)

        assert command == Command(request="cover_mode")
        assert composites.edits == {"reversed"}
        assert not composites.ready_payloads(COVER_MODE)

    def test_requested_composite_is_sent_with_the_edit_once_received(self):
        composites = CompositeState()
        composites.edit("reversed", COVER_MODE["reversed"], WbBoolValue.TRUE, COVER_MODE)
        receive(composites, COVER_MODE, {"cover_mode": {"reversed": False, "led": True}})

        assert composites.ready_payloads(COVER_MODE) == [{"cover_mode": {"reversed": True, "led": True}}]
        assert not composites.edits
        assert not composites.ready_payloads(COVER_MODE)

    def test_deferred_field_is_only_stored(self):
        composites = CompositeState()

        command = composites.edit("strobe", WARNING["strobe"], WbBoolValue.TRUE, WARNING)

        assert command == Command()
        assert composites.values == {"warning": {"strobe": True}}
        assert composites.edits == {"strobe"}

    def test_button_sends_stored_fields_and_clears_their_edits(self):
        composites = CompositeState()
        composites.edit("strobe", WARNING["strobe"], WbBoolValue.TRUE, WARNING)

        command = composites.edit("warning", WARNING["warning"], WbBoolValue.TRUE, WARNING)

        assert command == Command(payload={"warning": {"strobe": True}})
        assert not composites.edits

    def test_button_without_stored_fields_does_nothing(self):
        assert CompositeState().edit("warning", WARNING["warning"], WbBoolValue.TRUE, WARNING) == Command()

    def test_button_sends_known_fields_without_reading_the_composite(self):
        """
        A read may never return the object (pin_code), so the button sends what is known
        """
        controls = {
            "outlet1": make_switch(("relay", "outlet1"), deferred=True),
            "relay": make_button(("relay",)),
        }
        composites = receive(CompositeState(), controls, {"relay": {"outlet1": False, "outlet2": True}})
        composites.edit("outlet1", controls["outlet1"], WbBoolValue.TRUE, controls)

        command = composites.edit("relay", controls["relay"], WbBoolValue.TRUE, controls)

        assert command == Command(payload={"relay": {"outlet1": True, "outlet2": True}})

    def test_field_command_and_button_touch_only_their_own_composite(self):
        controls = {**COVER_MODE, **WARNING}
        composites = receive(CompositeState(), controls, {"cover_mode": {"reversed": False, "led": True}})
        composites.edit("strobe", WARNING["strobe"], WbBoolValue.TRUE, controls)

        command = composites.edit("led", COVER_MODE["led"], WbBoolValue.FALSE, controls)

        assert command == Command(payload={"cover_mode": {"reversed": False, "led": False}})
        assert composites.edits == {"strobe"}
        assert composites.edit("warning", WARNING["warning"], WbBoolValue.TRUE, controls) == Command(
            payload={"warning": {"strobe": True}}
        )


class TestWbValues:
    """Tests for ``CompositeState.wb_values`` — restoring composite field values in WB form."""

    def test_formats_known_fields_and_skips_buttons(self):
        composites = CompositeState()
        composites.edit("strobe", WARNING["strobe"], WbBoolValue.TRUE, WARNING)

        assert composites.wb_values(WARNING) == {"strobe": WbBoolValue.TRUE}

    def test_composite_object_that_is_not_a_dict_is_skipped(self):
        assert not CompositeState(values={"cover_mode": None}).wb_values(COVER_MODE)
