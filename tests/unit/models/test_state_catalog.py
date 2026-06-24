"""Tests for the models/states catalog leaf.

Verifies that BaseState.__init_subclass__ registers subclasses at any inheritance
depth into the catalog — not just direct BaseState children.
"""

from typing import Literal

from hassette.models.states.base import BoolBaseState
from hassette.models.states.catalog import _STATE_CATALOG, StateKey, resolve


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
