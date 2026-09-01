"""Tests for RestartSpec — a frozen dataclass describing service restart/budget behavior.

Verifies:
- Default field values match documented defaults
- Every field can be overridden and the override is stored exactly
- The dataclass is frozen (post-construction mutation raises)
- Equality is value-based, not identity-based
- Frozen + eq=True gives a stable hash, so specs are usable as dict keys / set members
- degrade_on_confirmed_quiescent_refusal's sentinel resolution and "left unset" warning
- RestartSpec.single_point_of_failure() sets the opt-out field by default
"""

import dataclasses
import warnings

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


class TestDegradeOnConfirmedQuiescentRefusal:
    """Ship-time challenge finding (spec 106): the field defaults to unset (None) rather than a
    bare bool, and __post_init__ resolves it -- warning when the resolved value is the dangerous
    direction (True) and the caller never explicitly chose it. A plain bool default gave no way
    to tell "explicitly True" apart from "never noticed this field exists" -- exactly how the
    omission on WebApiService went unnoticed until this same challenge caught it.
    """

    def test_unset_resolves_to_true_for_transient_and_warns(self) -> None:
        with pytest.warns(UserWarning, match="degrade_on_confirmed_quiescent_refusal"):
            spec = RestartSpec(restart_type=RestartType.TRANSIENT)
        assert spec.degrade_on_confirmed_quiescent_refusal is True

    def test_unset_resolves_to_true_for_temporary_and_warns(self) -> None:
        with pytest.warns(UserWarning, match="degrade_on_confirmed_quiescent_refusal"):
            spec = RestartSpec(restart_type=RestartType.TEMPORARY)
        assert spec.degrade_on_confirmed_quiescent_refusal is True

    def test_unset_resolves_to_false_for_permanent_without_warning(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            spec = RestartSpec(restart_type=RestartType.PERMANENT)
        assert spec.degrade_on_confirmed_quiescent_refusal is False

    def test_explicit_true_is_stored_without_warning(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            spec = RestartSpec(restart_type=RestartType.TRANSIENT, degrade_on_confirmed_quiescent_refusal=True)
        assert spec.degrade_on_confirmed_quiescent_refusal is True

    def test_explicit_false_is_stored_without_warning(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            spec = RestartSpec(restart_type=RestartType.TRANSIENT, degrade_on_confirmed_quiescent_refusal=False)
        assert spec.degrade_on_confirmed_quiescent_refusal is False


class TestSinglePointOfFailureRestart:
    """RestartSpec.single_point_of_failure() is the named, self-documenting way to construct a
    RestartSpec for a service where running the framework without it is worse than a clean
    restart -- as distinct from CORE_PERMANENT_RESTART, which serves PERMANENT services for a
    different reason (losing them stops automations entirely).

    Only exposes the fields the framework's own single-point-of-failure services
    (WebsocketService, WebApiService) actually vary today -- restart_type, budget_intensity,
    budget_period_seconds, startup_timeout_seconds -- rather than accepting arbitrary
    **overrides, since nothing has ever needed to override a different field.
    """

    def test_defaults_the_opt_out_field_to_false(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            spec = RestartSpec.single_point_of_failure(restart_type=RestartType.TRANSIENT)
        assert spec.degrade_on_confirmed_quiescent_refusal is False

    def test_other_overrides_pass_through(self) -> None:
        spec = RestartSpec.single_point_of_failure(
            restart_type=RestartType.TRANSIENT,
            budget_intensity=5,
            budget_period_seconds=120,
            startup_timeout_seconds=45,
        )
        assert spec.budget_intensity == 5
        assert spec.restart_type == RestartType.TRANSIENT
        assert spec.budget_period_seconds == 120
        assert spec.startup_timeout_seconds == 45
