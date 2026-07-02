"""Tests for RestartSpec — a frozen dataclass describing service restart/budget behavior.

Verifies:
- Default field values match documented defaults
- Every field can be overridden and the override is stored exactly
- The dataclass is frozen (post-construction mutation raises)
- Equality is value-based, not identity-based
- Frozen + eq=True gives a stable hash, so specs are usable as dict keys / set members
"""

import dataclasses

import pytest

from hassette.resources.restart import RestartSpec
from hassette.types.enums import RestartType


class TestDefaults:
    """RestartSpec() with no arguments produces the documented default profile."""

    def test_default_restart_type_is_transient(self) -> None:
        spec = RestartSpec()
        assert spec.restart_type == RestartType.TRANSIENT

    def test_default_error_name_tuples_are_empty(self) -> None:
        spec = RestartSpec()
        assert spec.non_retryable_error_names == ()
        assert spec.fatal_error_names == ()

    def test_default_backoff_values(self) -> None:
        spec = RestartSpec()
        assert spec.backoff_base_seconds == 2.0
        assert spec.backoff_multiplier == 2.0
        assert spec.backoff_max_seconds == 60.0

    def test_default_budget_values(self) -> None:
        spec = RestartSpec()
        assert spec.budget_intensity == 5
        assert spec.budget_period_seconds == 300.0

    def test_default_timing_values(self) -> None:
        spec = RestartSpec()
        assert spec.startup_timeout_seconds == 30.0
        assert spec.cooldown_seconds == 300.0
        assert spec.max_cooldown_cycles == 0


class TestFieldOverrides:
    """Every field can be overridden independently and the value round-trips exactly."""

    def test_restart_type_override(self) -> None:
        spec = RestartSpec(restart_type=RestartType.PERMANENT)
        assert spec.restart_type == RestartType.PERMANENT

        spec = RestartSpec(restart_type=RestartType.TEMPORARY)
        assert spec.restart_type == RestartType.TEMPORARY

    def test_non_retryable_error_names_override(self) -> None:
        spec = RestartSpec(non_retryable_error_names=("ValueError", "KeyError"))
        assert spec.non_retryable_error_names == ("ValueError", "KeyError")

    def test_fatal_error_names_override(self) -> None:
        spec = RestartSpec(fatal_error_names=("SystemExit",))
        assert spec.fatal_error_names == ("SystemExit",)

    def test_backoff_fields_override(self) -> None:
        spec = RestartSpec(backoff_base_seconds=1.0, backoff_multiplier=3.0, backoff_max_seconds=120.0)
        assert spec.backoff_base_seconds == 1.0
        assert spec.backoff_multiplier == 3.0
        assert spec.backoff_max_seconds == 120.0

    def test_budget_fields_override(self) -> None:
        spec = RestartSpec(budget_intensity=10, budget_period_seconds=60.0)
        assert spec.budget_intensity == 10
        assert spec.budget_period_seconds == 60.0

    def test_timing_fields_override(self) -> None:
        spec = RestartSpec(startup_timeout_seconds=5.0, cooldown_seconds=15.0, max_cooldown_cycles=3)
        assert spec.startup_timeout_seconds == 5.0
        assert spec.cooldown_seconds == 15.0
        assert spec.max_cooldown_cycles == 3


class TestImmutability:
    """RestartSpec is declared @dataclass(frozen=True) — verify that contract holds."""

    def test_mutation_raises_frozen_instance_error(self) -> None:
        spec = RestartSpec()
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.restart_type = RestartType.PERMANENT  # pyright: ignore[reportAttributeAccessIssue]

    def test_mutation_of_numeric_field_raises(self) -> None:
        spec = RestartSpec()
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.budget_intensity = 99  # pyright: ignore[reportAttributeAccessIssue]


class TestEqualityAndHashing:
    """Frozen dataclasses with eq=True (the default) compare and hash by field values."""

    def test_equal_specs_with_same_values(self) -> None:
        spec1 = RestartSpec(restart_type=RestartType.PERMANENT, budget_intensity=3)
        spec2 = RestartSpec(restart_type=RestartType.PERMANENT, budget_intensity=3)
        assert spec1 == spec2
        assert spec1 is not spec2

    def test_unequal_specs_with_different_values(self) -> None:
        spec1 = RestartSpec(budget_intensity=3)
        spec2 = RestartSpec(budget_intensity=5)
        assert spec1 != spec2

    def test_default_and_explicit_default_are_equal(self) -> None:
        assert RestartSpec() == RestartSpec(restart_type=RestartType.TRANSIENT)

    def test_hashable_and_usable_as_dict_key(self) -> None:
        spec1 = RestartSpec(budget_intensity=3)
        spec2 = RestartSpec(budget_intensity=3)
        spec3 = RestartSpec(budget_intensity=7)

        lookup = {spec1: "profile-a"}
        # spec2 is equal-by-value to spec1, so it must hash the same and find the entry.
        assert lookup[spec2] == "profile-a"
        assert spec3 not in lookup

    def test_distinct_specs_form_a_two_element_set(self) -> None:
        specs = {RestartSpec(budget_intensity=3), RestartSpec(budget_intensity=3), RestartSpec(budget_intensity=5)}
        assert len(specs) == 2
