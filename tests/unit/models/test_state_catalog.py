"""Tests for the models/states catalog leaf.

Verifies that BaseState.__init_subclass__ registers subclasses at any inheritance
depth into the catalog — not just direct BaseState children.
"""

from typing import Literal

import pytest

from hassette.exceptions import DomainRequiredError
from hassette.models.states.base import BaseState, BoolBaseState
from hassette.models.states.catalog import _STATE_CATALOG, StateKey, register_state_converter, resolve
from hassette.models.states.sensor import SensorState
from hassette.models.states.sensor_shapes import (
    DateSensorState,
    EnumSensorState,
    NumericSensorState,
    TimestampSensorState,
)


class TestInitSubclassDepth:
    def test_grandchild_class_registers_into_catalog(self) -> None:
        """A grandchild of BaseState (via BoolBaseState) registers into the catalog.

        Guards the depth behavior: __init_subclass__ fires for all subclass levels,
        so a class inheriting from BoolBaseState (which inherits from BaseState)
        is still auto-registered by the __init_subclass__ hook.
        """

        class GrandchildBoolState(BoolBaseState):
            domain: Literal["test_grandchild_domain"]  # pyright: ignore[reportIncompatibleVariableOverride]

        key = StateKey(domain="test_grandchild_domain")
        assert key in _STATE_CATALOG, f"GrandchildBoolState not registered; catalog keys: {list(_STATE_CATALOG)}"
        assert _STATE_CATALOG[key] is GrandchildBoolState

    def test_grandchild_domain_resolves_from_registry(self) -> None:
        """resolve() finds a grandchild domain class via the catalog."""

        class AnotherGrandchild(BoolBaseState):
            domain: Literal["test_another_grandchild"]  # pyright: ignore[reportIncompatibleVariableOverride]

        result = resolve(domain="test_another_grandchild")
        assert result is AnotherGrandchild


class TestRegisterRequiresDomain:
    """register_state_converter is the single choke point both StateRegistry.register() and
    BaseState.__init_subclass__ funnel through — guarding it here covers every registration path.
    """

    def test_none_domain_raises_instead_of_corrupting_catalog(self) -> None:
        """domain=None must raise, not silently store a StateKey(domain=None) entry that
        resolve(domain=None) could return before callers validate the result.
        """

        class NoDomainRegistrationState(BaseState):
            domain: Literal["test_register_requires_domain"]  # pyright: ignore[reportIncompatibleVariableOverride]

        with pytest.raises(DomainRequiredError):
            register_state_converter(NoDomainRegistrationState, domain=None)  # pyright: ignore[reportArgumentType]

        assert StateKey(domain=None) not in _STATE_CATALOG
        assert resolve(domain=None) is None


class TestSensorShapeClassesDoNotRegister:
    def test_resolve_sensor_domain_still_returns_sensor_state(self) -> None:
        """Importing the four narrowed sensor shape classes must not clobber `SensorState`.

        None of `NumericSensorState`, `EnumSensorState`, `TimestampSensorState`, or
        `DateSensorState` re-declares `domain`, so `__init_subclass__` should never register
        them into the catalog under `StateKey("sensor")`.
        """
        # Reference the imported classes so importing this module is enough to prove they
        # were defined (and, if buggy, would have registered) before this assertion runs.
        assert NumericSensorState is not None
        assert EnumSensorState is not None
        assert TimestampSensorState is not None
        assert DateSensorState is not None

        assert resolve(domain="sensor") is SensorState
