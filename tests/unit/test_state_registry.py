import typing

import pytest
from pydantic import model_validator
from whenever import ZonedDateTime

from hassette.models.states import (
    AlertState,
    BaseState,
    GroupState,
    InfraredState,
    LightState,
    RadioFrequencyState,
    ScheduleState,
    TagState,
    WakeWordState,
)
from hassette.testing import make_state_dict

if typing.TYPE_CHECKING:
    from hassette.events import HassStateDict
    from hassette.testing import HassetteHarness


class CustomOuterDefinition(BaseState):
    domain: typing.Literal["custom_outer"]


def test_custom_class_defined_inside_function_still_returns_custom_state(
    hassette_with_state_registry: "HassetteHarness",
) -> None:
    """try_convert_state will return BaseState if a custom state class is defined inside a
    function and not registered.
    """
    hassette = hassette_with_state_registry

    # Register a custom state class for domain 'custom_domain'
    class CustomStateWithoutRegister(BaseState):
        domain: typing.Literal["custom_without_register"]

    state_dict = make_state_dict(
        "custom_without_register.test",
        "test_value",
        {"custom_attr": "value"},
        last_changed="2024-01-01T00:00:00Z",
        last_updated="2024-01-01T00:00:00Z",
    )

    value = hassette.hassette.state_registry.try_convert_state(typing.cast("HassStateDict", state_dict))
    assert value is not None, "State conversion failed"
    assert type(value) is CustomStateWithoutRegister, f"CustomStateWithoutRegister BaseState, got {type(value)}"


def test_custom_class_nested_definition_returns_proper_state_after_register(
    hassette_with_state_registry: "HassetteHarness",
) -> None:
    """try_convert_state will return the correct custom state if the class is registered."""
    hassette = hassette_with_state_registry

    class CustomStateWithRegister(BaseState):
        domain: typing.Literal["custom_with_register"]

    state_dict = make_state_dict(
        "custom_with_register.test",
        "test_value",
        {"custom_attr": "value"},
        last_changed="2024-01-01T00:00:00Z",
        last_updated="2024-01-01T00:00:00Z",
    )

    hassette.hassette.state_registry.register(CustomStateWithRegister, domain="custom_with_register")
    return_value = hassette.hassette.state_registry.try_convert_state(typing.cast("HassStateDict", state_dict))

    assert return_value is not None, "State conversion failed"
    assert type(return_value) is not BaseState, "Expected a specific state class, got BaseState"
    assert isinstance(return_value, CustomStateWithRegister), (
        f"Expected CustomStateWithRegister, got {type(return_value)}"
    )


def test_custom_state_defined_at_module_level_works_without_calling_register(
    hassette_with_state_registry: "HassetteHarness",
) -> None:
    """try_convert_state can handle custom states without calling register if they are defined at module level."""
    hassette = hassette_with_state_registry

    state_dict = make_state_dict(
        "custom_outer.test",
        "outer_value",
        {"outer_attr": "outer"},
        last_changed="2024-01-01T00:00:00Z",
        last_updated="2024-01-01T00:00:00Z",
    )

    return_value = hassette.hassette.state_registry.try_convert_state(typing.cast("HassStateDict", state_dict))

    assert return_value is not None, "State conversion failed"
    assert type(return_value) is not BaseState, "Expected a specific state class, got BaseState"
    assert isinstance(return_value, CustomOuterDefinition), f"Expected CustomOuterDefinition, got {type(return_value)}"


def test_try_convert_state_falls_back_to_base_state_when_domain_class_fails(
    hassette_with_state_registry: "HassetteHarness",
) -> None:
    """try_convert_state returns BaseState when the registered domain class cannot convert the payload."""
    hassette = hassette_with_state_registry

    class AlwaysFailingState(BaseState):
        domain: typing.Literal["always_failing"]

        @model_validator(mode="after")
        def reject(self) -> "AlwaysFailingState":
            raise ValueError("payload rejected")

    hassette.hassette.state_registry.register(AlwaysFailingState, domain="always_failing")

    state_dict = make_state_dict(
        "always_failing.test",
        "value",
        {},
        last_changed="2024-01-01T00:00:00Z",
        last_updated="2024-01-01T00:00:00Z",
    )

    return_value = hassette.hassette.state_registry.try_convert_state(typing.cast("HassStateDict", state_dict))

    assert type(return_value) is BaseState
    assert return_value.entity_id == "always_failing.test"


@pytest.mark.parametrize(
    ("entity_id", "expected_class"),
    [
        ("wake_word.openwakeword", WakeWordState),
        ("infrared.living_room_blaster", InfraredState),
        ("radio_frequency.garage_transmitter", RadioFrequencyState),
    ],
)
def test_try_convert_state_resolves_timestamp_domains_to_typed_models(
    hassette_with_state_registry: "HassetteHarness",
    entity_id: str,
    expected_class: type[BaseState],
) -> None:
    """Timestamp-state domains resolve to their typed model and parse the state as a ZonedDateTime."""
    hassette = hassette_with_state_registry

    state_dict = make_state_dict(entity_id, "2024-01-01T12:30:00.000+00:00", {})

    return_value = hassette.hassette.state_registry.try_convert_state(typing.cast("HassStateDict", state_dict))

    assert type(return_value) is expected_class
    assert isinstance(return_value.value, ZonedDateTime)


def test_try_convert_state_resolves_alert_to_typed_model(
    hassette_with_state_registry: "HassetteHarness",
) -> None:
    """Alert states resolve to AlertState with the string state preserved."""
    hassette = hassette_with_state_registry

    state_dict = make_state_dict("alert.garage_door", "idle", {})

    return_value = hassette.hassette.state_registry.try_convert_state(typing.cast("HassStateDict", state_dict))

    assert type(return_value) is AlertState
    assert return_value.value == "idle"


def test_try_convert_state_resolves_tag_to_typed_model(
    hassette_with_state_registry: "HassetteHarness",
) -> None:
    """Tag states resolve to TagState with the last-scanned timestamp and tag attributes."""
    hassette = hassette_with_state_registry

    state_dict = make_state_dict(
        "tag.front_door",
        "2024-01-01T12:30:00.000+00:00",
        {"tag_id": "abc-123", "last_scanned_by_device_id": "device-456"},
    )

    return_value = hassette.hassette.state_registry.try_convert_state(typing.cast("HassStateDict", state_dict))

    assert type(return_value) is TagState
    assert isinstance(return_value.value, ZonedDateTime)
    assert return_value.attributes.tag_id == "abc-123"
    assert return_value.attributes.last_scanned_by_device_id == "device-456"


def convert_state(
    harness: "HassetteHarness", entity_id: str, state: str, attributes: dict[str, typing.Any]
) -> BaseState:
    """Convert a raw state dict for ``entity_id`` through the harness's state registry."""
    return harness.hassette.state_registry.try_convert_state(
        typing.cast("HassStateDict", make_state_dict(entity_id, state, attributes))
    )


def test_try_convert_state_resolves_schedule_to_typed_model(
    hassette_with_state_registry: "HassetteHarness",
) -> None:
    """Schedule states parse next_event and keep user-defined block data in extras."""
    block = [{"from": "07:00:00", "to": "09:00:00"}]
    attributes = {"next_event": "2024-01-01T09:00:00+00:00", "monday": block}

    value = convert_state(hassette_with_state_registry, "schedule.weekday_mornings", "on", attributes)

    assert type(value) is ScheduleState
    assert value.value == "on"
    assert isinstance(value.attributes.next_event, ZonedDateTime)
    assert value.attributes.extras["monday"] == block


def test_try_convert_state_resolves_legacy_group_to_typed_model(
    hassette_with_state_registry: "HassetteHarness",
) -> None:
    """Legacy group.* states resolve to GroupState with entity_id, order, and auto."""
    members = ["light.kitchen", "light.hall"]
    attributes = {"entity_id": members, "order": 3, "auto": True}

    value = convert_state(hassette_with_state_registry, "group.downstairs_lights", "on", attributes)

    assert type(value) is GroupState
    assert value.attributes.entity_id == members
    assert value.attributes.order == 3
    assert value.attributes.auto is True


def test_try_convert_state_resolves_light_group_to_light_model(
    hassette_with_state_registry: "HassetteHarness",
) -> None:
    """UI helper light groups are light.* entities and keep resolving to LightState."""
    members = ["light.kitchen", "light.hall"]

    value = convert_state(hassette_with_state_registry, "light.downstairs", "on", {"entity_id": members})

    assert type(value) is LightState
    assert value.attributes.entity_id == members
