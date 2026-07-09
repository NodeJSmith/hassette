"""Unit tests for Bus registration edge cases not covered elsewhere.

Covers:
- mode= / backpressure= accepted as already-resolved enum instances (not just strings)
- Invalid backpressure string raises ValueError via Bus.on() (mirrors the mode coercion)
- _on_internal()'s own defensive name=None check (bypassing the public on()/on_state_change()
  wrappers, which normally catch this first)
- on_call_service(where=<Mapping>) and on_call_service(where=<callable>)
- on_state_change / on_attribute_change reject duration= combined with a glob entity_id
- on_attribute_change(changed=False) omits the AttrDidChange predicate
- on_component_loaded / on_service_registered / on_app_state_changed filter predicates
- on_state_change(changed=<ComparisonCondition>) builds a StateComparison predicate
"""

import typing

import pytest

from hassette import C
from hassette.events.hassette import HassetteAppStateEvent
from hassette.exceptions import ListenerNameRequiredError
from hassette.test_utils.helpers import (
    create_call_service_event,
    create_component_loaded_event,
    create_service_registered_event,
    create_state_change_event,
    make_full_state_change_event,
    make_state_dict,
)
from hassette.types.enums import BackpressurePolicy, ExecutionMode, ResourceStatus

from .conftest import mock_add_listener

if typing.TYPE_CHECKING:
    from hassette.bus.bus import Bus


async def handler_a(event) -> None:
    pass


class TestModeAndBackpressureEnumPassthrough:
    async def test_on_accepts_execution_mode_enum_directly(self, bus: "Bus") -> None:
        """mode= already an ExecutionMode instance (not a string) is stored as-is."""
        with mock_add_listener(bus):
            sub = await bus.on(topic="test.topic", handler=handler_a, name="enum_mode", mode=ExecutionMode.RESTART)
        assert sub.listener.options.mode is ExecutionMode.RESTART

    async def test_on_accepts_backpressure_enum_directly(self, bus: "Bus") -> None:
        """backpressure= already a BackpressurePolicy instance (not a string) is stored as-is."""
        with mock_add_listener(bus):
            sub = await bus.on(
                topic="test.topic", handler=handler_a, name="enum_bp", backpressure=BackpressurePolicy.DROP_NEWEST
            )
        assert sub.listener.options.backpressure is BackpressurePolicy.DROP_NEWEST

    async def test_on_rejects_invalid_backpressure_string(self, bus: "Bus") -> None:
        """An unknown backpressure string raises ValueError listing the valid policies.

        This is Bus._on_internal's own pre-validation (distinct from ListenerOptions'
        __post_init__ coercion, which runs later on the already-resolved value).
        """
        with mock_add_listener(bus), pytest.raises(ValueError, match="bogus_policy") as exc_info:
            await bus.on(topic="test.topic", handler=handler_a, name="bad_bp", backpressure="bogus_policy")
        msg = str(exc_info.value)
        assert "block" in msg
        assert "drop_newest" in msg


class TestOnInternalDirectNameCheck:
    async def test_on_internal_direct_call_without_name_raises(self, bus: "Bus") -> None:
        """_on_internal's own defensive name=None check fires even when called directly,
        bypassing the public on()/on_state_change() wrappers that normally catch this first.
        """
        with pytest.raises(ListenerNameRequiredError):
            await bus._on_internal(topic="test.topic", handler=handler_a, name=None)


class TestOnCallServiceWhereVariants:
    async def test_where_mapping_builds_service_data_where(self, bus: "Bus") -> None:
        """where=<Mapping> is wrapped in ServiceDataWhere, matching only calls with that service_data."""
        with mock_add_listener(bus):
            sub = await bus.on_call_service(handler=handler_a, name="svc_mapping", where={"entity_id": "light.kitchen"})

        matching = create_call_service_event(
            domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"}
        )
        other = create_call_service_event(
            domain="light", service="turn_on", service_data={"entity_id": "light.bedroom"}
        )
        assert sub.listener.matches(matching) is True
        assert sub.listener.matches(other) is False

    async def test_where_callable_used_directly(self, bus: "Bus") -> None:
        """where=<callable> (not a list/Mapping) is used as the predicate directly."""
        seen = []

        def custom_pred(event) -> bool:
            seen.append(event)
            return True

        with mock_add_listener(bus):
            sub = await bus.on_call_service(handler=handler_a, name="svc_callable", where=custom_pred)

        event = create_call_service_event(domain="light", service="turn_on")
        assert sub.listener.matches(event) is True
        assert seen == [event]

    async def test_where_list_of_only_mappings_adds_no_extra_predicate(self, bus: "Bus") -> None:
        """where=[<Mapping>, ...] with only Mapping entries builds ServiceDataWhere predicates
        and skips the extra-predicate branch entirely (no non-Mapping items to combine).
        """
        with mock_add_listener(bus):
            sub = await bus.on_call_service(
                handler=handler_a, name="svc_mapping_list", where=[{"entity_id": "light.kitchen"}]
            )

        matching = create_call_service_event(
            domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"}
        )
        other = create_call_service_event(
            domain="light", service="turn_on", service_data={"entity_id": "light.bedroom"}
        )
        assert sub.listener.matches(matching) is True
        assert sub.listener.matches(other) is False


class TestDurationGlobRejection:
    async def test_on_state_change_rejects_glob_with_duration(self, bus: "Bus") -> None:
        """duration= with a glob entity_id raises ValueError (glob entities can't hold a single timer)."""
        with pytest.raises(ValueError, match=r"'duration'.*glob"):
            await bus.on_state_change("light.*", handler=handler_a, duration=5.0, name="glob_duration")

    async def test_on_attribute_change_rejects_glob_with_duration(self, bus: "Bus") -> None:
        """Same rejection applies to on_attribute_change's duration= parameter."""
        with pytest.raises(ValueError, match=r"'duration'.*glob"):
            await bus.on_attribute_change(
                "light.*", "brightness", handler=handler_a, duration=5.0, name="glob_attr_duration"
            )


class TestOnAttributeChangeChangedFalse:
    async def test_changed_false_omits_attr_did_change_predicate(self, bus: "Bus") -> None:
        """changed=False skips AttrDidChange — the listener fires even when the attribute is unchanged."""
        with mock_add_listener(bus):
            sub = await bus.on_attribute_change(
                "light.kitchen", "brightness", handler=handler_a, changed=False, name="attr_changed_false"
            )

        old_state = make_state_dict("light.kitchen", "on", attributes={"brightness": 100})
        new_state = make_state_dict("light.kitchen", "on", attributes={"brightness": 100})  # unchanged
        event = make_full_state_change_event("light.kitchen", old_state, new_state)

        assert sub.listener.matches(event) is True


class TestComponentServiceAppKeyFilters:
    async def test_on_component_loaded_with_component_filters(self, bus: "Bus") -> None:
        """component= adds a ValueIs predicate that only matches that component's load event."""
        with mock_add_listener(bus):
            sub = await bus.on_component_loaded(component="mqtt", handler=handler_a, name="mqtt_loaded")

        matching = create_component_loaded_event("mqtt")
        other = create_component_loaded_event("zwave")
        assert sub.listener.matches(matching) is True
        assert sub.listener.matches(other) is False

    async def test_on_component_loaded_without_component_matches_any(self, bus: "Bus") -> None:
        """Omitting component= matches every component_loaded event."""
        with mock_add_listener(bus):
            sub = await bus.on_component_loaded(handler=handler_a, name="any_loaded")

        assert sub.listener.matches(create_component_loaded_event("mqtt")) is True
        assert sub.listener.matches(create_component_loaded_event("zwave")) is True

    async def test_on_service_registered_with_domain_and_service_filters(self, bus: "Bus") -> None:
        """domain= and service= together only match the exact (domain, service) pair."""
        with mock_add_listener(bus):
            sub = await bus.on_service_registered(
                domain="light", service="turn_on", handler=handler_a, name="light_turn_on_registered"
            )

        matching = create_service_registered_event("light", "turn_on")
        wrong_domain = create_service_registered_event("switch", "turn_on")
        wrong_service = create_service_registered_event("light", "turn_off")
        assert sub.listener.matches(matching) is True
        assert sub.listener.matches(wrong_domain) is False
        assert sub.listener.matches(wrong_service) is False

    async def test_on_app_state_changed_with_app_key_filters(self, bus: "Bus") -> None:
        """app_key= adds a ValueIs predicate that only matches that app's state-change events."""
        with mock_add_listener(bus):
            sub = await bus.on_app_state_changed(handler=handler_a, app_key="my_app", name="my_app_state")

        matching_app = make_app_stub(app_key="my_app")
        other_app = make_app_stub(app_key="other_app")
        matching_event = HassetteAppStateEvent.from_data(matching_app, status=ResourceStatus.RUNNING)
        other_event = HassetteAppStateEvent.from_data(other_app, status=ResourceStatus.RUNNING)

        assert sub.listener.matches(matching_event) is True
        assert sub.listener.matches(other_event) is False


class TestStateChangeComparisonCondition:
    async def test_changed_with_comparison_condition_builds_state_comparison(self, bus: "Bus") -> None:
        """changed=<ComparisonCondition> (not True/False) builds a StateComparison predicate."""
        with mock_add_listener(bus):
            sub = await bus.on_state_change("sensor.temp", handler=handler_a, changed=C.Increased(), name="temp_up")

        increased = create_state_change_event(entity_id="sensor.temp", old_value=20, new_value=25)
        decreased = create_state_change_event(entity_id="sensor.temp", old_value=25, new_value=20)
        assert sub.listener.matches(increased) is True
        assert sub.listener.matches(decreased) is False


def make_app_stub(*, app_key: str, index: int = 0, instance_name: str | None = None):
    """Minimal stand-in for an App instance, exposing only what HassetteAppStateEvent.from_data reads."""

    class _AppStub:
        pass

    stub = _AppStub()
    stub.app_key = app_key  # pyright: ignore[reportAttributeAccessIssue]
    stub.index = index  # pyright: ignore[reportAttributeAccessIssue]
    stub.instance_name = instance_name  # pyright: ignore[reportAttributeAccessIssue]
    return stub
