import typing

import pytest

from hassette.models.states import BaseState
from hassette.test_utils.helpers import make_state_dict

if typing.TYPE_CHECKING:
    from hassette import Hassette


@pytest.fixture(scope="module")
async def hassette_with_state_registry(hassette_harness, test_config):
    async with hassette_harness(config=test_config, use_bus=True, use_state_registry=True) as harness:
        yield typing.cast("Hassette", harness.hassette)


class CustomOuterDefinition(BaseState):
    domain: typing.Literal["custom_outer"]


def test_custom_class_defined_inside_function_returns_base_state_with_unregistered_class(
    hassette_with_state_registry: "Hassette",
) -> None:
    """try_convert_state will return BaseState if a custom state class is defined inside a
    function and not registered."""
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

    value = hassette.state_registry.try_convert_state(state_dict)
    assert value is not None, "State conversion failed"
    assert type(value) is BaseState, f"Expected BaseState, got {type(value)}"
    assert type(value) is not CustomStateWithoutRegister, (
        "Expected not to get CustomStateWithoutRegister since it was not registered"
    )


def test_custom_class_nested_definition_returns_proper_state_after_register(
    hassette_with_state_registry: "Hassette",
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

    hassette.state_registry.register(CustomStateWithRegister)
    return_value = hassette.state_registry.try_convert_state(state_dict)

    assert return_value is not None, "State conversion failed"
    assert type(return_value) is not BaseState, "Expected a specific state class, got BaseState"
    assert isinstance(return_value, CustomStateWithRegister), (
        f"Expected CustomStateWithRegister, got {type(return_value)}"
    )


def test_custom_state_defined_at_module_level_works_without_calling_register(
    hassette_with_state_registry: "Hassette",
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

    return_value = hassette.state_registry.try_convert_state(state_dict)

    assert return_value is not None, "State conversion failed"
    assert type(return_value) is not BaseState, "Expected a specific state class, got BaseState"
    assert isinstance(return_value, CustomOuterDefinition), f"Expected CustomOuterDefinition, got {type(return_value)}"
