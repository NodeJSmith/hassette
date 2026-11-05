"""Trigger summaries on handler execution records (spec 147: D2, D3, D5, D7)."""

import dataclasses
import logging

import pytest
from hassette_wire import ExecutionStatus, ExecutionTrigger

from hassette.core.bus_service import make_synthetic_state_event
from hassette.core.execution_record import SYNTHETIC_ORIGIN, ExecutionRecord
from hassette.core.execution_record_builder import (
    TRIGGER_VALUE_MAX_CHARS,
    TRUNCATION_MARK,
    TriggerRecordFields,
    build_execution_record,
    format_trigger_value,
    summarize_trigger,
)
from hassette.core.telemetry.execution_queries import TRIGGER_COLUMNS
from hassette.core.telemetry.insert_params import execution_insert_params
from hassette.testing import create_call_service_event, create_state_change_event, make_state_dict
from hassette.types.enums import Topic
from hassette.utils.execution import ExecutionResult
from tests.support.factories import make_execution_record, make_hassette_event, make_invoke_handler_cmd
from tests.support.helpers import create_attr_change_event, create_listener


def state_listener():
    return create_listener(entity_id="light.office")


def attribute_listener(attribute: str = "brightness"):
    return create_listener(entity_id="light.office", attribute=attribute)


class TestStateChangeSummary:
    def test_records_topic_entity_and_state_values(self) -> None:
        event = create_state_change_event(entity_id="light.office", old_value="off", new_value="on")

        trigger = summarize_trigger(event, state_listener(), is_synthetic=False)

        assert trigger["trigger_topic"] == "hass.event.state_changed"
        assert trigger["trigger_entity_id"] == "light.office"
        assert trigger["trigger_old_value"] == "off"
        assert trigger["trigger_new_value"] == "on"
        assert trigger["trigger_context_id"] == event.payload.context.id
        assert trigger["trigger_origin"] == "LOCAL"

    def test_topic_is_event_topic_not_listener_route(self) -> None:
        event = create_state_change_event(entity_id="light.office", old_value="off", new_value="on")
        listener = create_listener(topic="hass.event.state_changed.light.office", entity_id="light.office")

        assert summarize_trigger(event, listener, is_synthetic=False)["trigger_topic"] == str(
            Topic.HASS_EVENT_STATE_CHANGED
        )

    def test_attribute_listener_records_tracked_attribute(self) -> None:
        event = create_attr_change_event(10, 200, attr_name="brightness")

        trigger = summarize_trigger(event, attribute_listener("brightness"), is_synthetic=False)

        assert trigger["trigger_old_value"] == "10"
        assert trigger["trigger_new_value"] == "200"

    def test_listener_without_entity_watch_records_state_values(self) -> None:
        event = create_state_change_event(entity_id="light.office", old_value="off", new_value="on")

        trigger = summarize_trigger(event, create_listener(topic="hass.event.state_changed"), is_synthetic=False)

        assert (trigger["trigger_old_value"], trigger["trigger_new_value"]) == ("off", "on")

    def test_missing_old_state_stores_none(self) -> None:
        event = create_state_change_event(entity_id="light.office", old_value=None, new_value="on")

        trigger = summarize_trigger(event, state_listener(), is_synthetic=False)

        assert trigger["trigger_old_value"] is None
        assert trigger["trigger_new_value"] == "on"

    def test_missing_attribute_stores_none_but_explicit_null_stores_null(self) -> None:
        event = create_state_change_event(
            entity_id="light.office",
            old_value="on",
            new_value="on",
            old_attrs={},
            new_attrs={"brightness": None},
        )

        trigger = summarize_trigger(event, attribute_listener("brightness"), is_synthetic=False)

        assert trigger["trigger_old_value"] is None
        assert trigger["trigger_new_value"] == "null"

    def test_parent_id_recorded_from_context(self) -> None:
        event = create_state_change_event(entity_id="light.office", old_value="off", new_value="on")
        object.__setattr__(event.payload.context, "parent_id", "parent-ctx")

        assert summarize_trigger(event, state_listener(), is_synthetic=False)["trigger_parent_id"] == "parent-ctx"


class TestOtherEvents:
    def test_call_service_event_has_no_entity_or_values(self) -> None:
        event = create_call_service_event(domain="light", service="turn_on")

        trigger = summarize_trigger(event, create_listener(topic="hass.event.call_service"), is_synthetic=False)

        assert trigger["trigger_topic"] == "hass.event.call_service"
        assert trigger["trigger_entity_id"] is None
        assert trigger["trigger_old_value"] is None
        assert trigger["trigger_new_value"] is None

    def test_hassette_event_records_its_own_id_and_no_parent(self) -> None:
        event = make_hassette_event(topic="hassette.event.app_state_changed")

        trigger = summarize_trigger(
            event, create_listener(topic="hassette.event.app_state_changed"), is_synthetic=False
        )

        assert trigger["trigger_topic"] == "hassette.event.app_state_changed"
        assert trigger["trigger_context_id"] == event.payload.event_id
        assert trigger["trigger_parent_id"] is None
        assert trigger["trigger_origin"] == "HASSETTE"


class TestValueFormatting:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("21.5", "21.5"),
            (21.5, "21.5"),
            (True, "true"),
            (None, "null"),
            (["a", "b"], '["a","b"]'),
            ({"k": "é"}, '{"k":"é"}'),
        ],
    )
    def test_strings_as_is_others_as_compact_json(self, value: object, expected: str) -> None:
        assert format_trigger_value(value) == expected

    def test_value_at_the_cap_is_kept_whole(self) -> None:
        text = "x" * TRIGGER_VALUE_MAX_CHARS
        assert format_trigger_value(text) == text

    def test_value_over_the_cap_is_cut_with_ellipsis(self) -> None:
        cut = format_trigger_value("é" * (TRIGGER_VALUE_MAX_CHARS + 10))

        assert len(cut) == TRIGGER_VALUE_MAX_CHARS
        assert cut.endswith(TRUNCATION_MARK)

    def test_non_json_value_uses_str(self) -> None:
        assert format_trigger_value({"when": object}) == f'{{"when":"{object}"}}'


class TestFailureIsContained:
    def test_extraction_failure_keeps_context_and_origin_and_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        event = create_state_change_event(entity_id="light.office", old_value="off", new_value="on")
        object.__setattr__(event.payload.data, "new_state", {"attributes": "not-a-dict"})

        with caplog.at_level(logging.ERROR):
            trigger = summarize_trigger(event, attribute_listener("brightness"), is_synthetic=False)

        assert trigger["trigger_entity_id"] is None
        assert trigger["trigger_old_value"] is None
        assert trigger["trigger_new_value"] is None
        assert trigger["trigger_context_id"] == event.payload.context.id
        assert trigger["trigger_origin"] == "LOCAL"
        assert trigger["trigger_topic"] == "hass.event.state_changed"
        assert "Failed to summarize the triggering event" in caplog.text
        assert "not-a-dict" not in caplog.text


class TestSyntheticEvents:
    def test_synthetic_event_carries_cached_context_and_base_topic(self) -> None:
        context = {"id": "ctx-real", "parent_id": "ctx-parent", "user_id": None}
        state = make_state_dict("light.office", "on", context=context)

        event = make_synthetic_state_event("light.office", state)  # pyright: ignore[reportArgumentType]

        assert event.topic == Topic.HASS_EVENT_STATE_CHANGED
        assert event.payload.context.id == "ctx-real"
        assert event.payload.context.parent_id == "ctx-parent"
        assert event.payload.data.old_state is None

    def test_synthetic_run_record_keeps_context_and_labels_origin(self) -> None:
        state = make_state_dict("light.office", "on", context={"id": "ctx-real", "parent_id": None, "user_id": None})
        event = make_synthetic_state_event("light.office", state)  # pyright: ignore[reportArgumentType]
        cmd = make_invoke_handler_cmd(event=event, listener=state_listener(), is_synthetic=True)
        result = ExecutionResult()
        result.status = ExecutionStatus.SUCCESS

        record = build_execution_record(cmd, result, 0.0, "exec-1", session_id=None)

        assert record.trigger_context_id == "ctx-real"
        assert record.trigger_origin == SYNTHETIC_ORIGIN
        assert record.trigger_old_value is None
        assert record.trigger_new_value == "on"
        assert record.trigger_topic == str(Topic.HASS_EVENT_STATE_CHANGED)


class TestTriggerColumnsStayInStep:
    def test_select_insert_and_record_carry_the_same_trigger_columns(self) -> None:
        """Every trigger_* record field (bar trigger_mode) is inserted and nested back under Execution.trigger."""
        record_fields = {f.name for f in dataclasses.fields(ExecutionRecord) if f.name.startswith("trigger_")}
        record_fields.discard("trigger_mode")
        inserted = {key for key in execution_insert_params(make_execution_record()) if key.startswith("trigger_")}
        inserted.discard("trigger_mode")

        assert set(TRIGGER_COLUMNS) == record_fields == inserted == set(TriggerRecordFields.__annotations__)
        assert set(TRIGGER_COLUMNS.values()) == set(ExecutionTrigger.model_fields)
