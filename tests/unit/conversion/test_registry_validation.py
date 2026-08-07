"""Tests for registry validation.

The global _isolate_registries fixture in conftest.py snapshots/restores the
state-class catalog before/after every test, so catalog mutations here do not
bleed between tests. TypeRegistry is a stable read-only global after import.
"""

import inspect
from typing import Literal

import pytest

from hassette.conversion import STATE_REGISTRY, TYPE_REGISTRY
from hassette.conversion.state_registry import StateKey, StateRegistry
from hassette.conversion.type_registry import TypeConverterEntry, TypeRegistry
from hassette.conversion.validation import RegistryValidationIssue, validate_registries
from hassette.exceptions import RegistryValidationError
from hassette.models.states import SensorState
from hassette.models.states.base import BaseState
from hassette.models.states.catalog import _STATE_CATALOG, resolve, restore_catalog


class TestRealRegistriesPass:
    def test_real_registries_pass_validation(self) -> None:
        """Running validate_registries() against the real (unmodified) registries produces zero issues."""
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        assert issues == [], f"Expected no issues, got: {issues}"


class TestEmptyRegistryErrors:
    def test_empty_state_registry_error(self) -> None:
        """Clearing the state catalog should produce an error issue with 'empty' in the message."""
        restore_catalog({})
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        state_issues = [i for i in issues if i.registry == "STATE_REGISTRY"]
        assert len(state_issues) >= 1
        error_issues = [i for i in state_issues if i.severity == "error"]
        assert len(error_issues) >= 1
        assert "empty" in error_issues[0].message.lower()

    def test_empty_type_registry_error(self) -> None:
        """Clearing TYPE_REGISTRY.conversion_map should produce an error issue with 'empty' in the message."""
        saved = dict(TypeRegistry.conversion_map)
        TypeRegistry.conversion_map.clear()
        try:
            issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
            type_issues = [i for i in issues if i.registry == "TYPE_REGISTRY"]
            assert len(type_issues) >= 1
            error_issues = [i for i in type_issues if i.severity == "error"]
            assert len(error_issues) >= 1
            assert "empty" in error_issues[0].message.lower()
        finally:
            TypeRegistry.conversion_map.update(saved)


class TestStateRegistryValidation:
    def test_state_registry_none_domain_error(self) -> None:
        """An entry with StateKey(domain=None) should produce an error issue."""

        class NoDomainState(BaseState):
            domain: "str"

        _STATE_CATALOG[StateKey(domain=None)] = NoDomainState
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        state_errors = [i for i in issues if i.registry == "STATE_REGISTRY" and i.severity == "error"]
        assert len(state_errors) >= 1
        # At least one mentions domain or None
        assert any("domain" in i.message.lower() or "none" in i.message.lower() for i in state_errors)

    def test_state_registry_non_subclass_error(self) -> None:
        """An entry whose value is not a BaseState subclass should produce an error issue."""

        class NotAState:
            pass

        _STATE_CATALOG[StateKey(domain="fake_domain")] = NotAState  # pyright: ignore[reportArgumentType]
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        state_errors = [i for i in issues if i.registry == "STATE_REGISTRY" and i.severity == "error"]
        assert len(state_errors) >= 1
        assert any("subclass" in i.message.lower() or "basestate" in i.message.lower() for i in state_errors)

    def test_state_registry_same_domain_overwrites_without_duplicate_warning(self) -> None:
        """Registering a second class under the same domain overwrites the first entry.

        With the domain-only StateKey, the domain *is* the entire key, so two
        registrations for the same domain can never coexist in the catalog dict —
        the second assignment overwrites the first. This is the intended override
        mechanism (see design.md Key Decision #7), and it also means the
        duplicate-domain warning path in validation.py's _validate_state_registry
        can no longer be triggered: there is only ever one entry per domain.
        """

        class StateA(BaseState):
            domain: "str"

        class StateB(BaseState):
            domain: "str"

        _STATE_CATALOG[StateKey(domain="dup_domain")] = StateA
        _STATE_CATALOG[StateKey(domain="dup_domain")] = StateB

        assert _STATE_CATALOG[StateKey(domain="dup_domain")] is StateB
        assert sum(1 for k in _STATE_CATALOG if k == StateKey(domain="dup_domain")) == 1

        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        dup_warnings = [
            i for i in issues if i.registry == "STATE_REGISTRY" and i.severity == "warning" and "dup" in i.message
        ]
        assert dup_warnings == []


class TestTypeRegistryValidation:
    @pytest.fixture(autouse=True)
    def _restore_conversion_map(self):
        """Snapshot and restore conversion_map around each test that mutates it directly."""
        saved = dict(TypeRegistry.conversion_map)
        yield
        TypeRegistry.conversion_map.clear()
        TypeRegistry.conversion_map.update(saved)

    def test_type_registry_non_callable_func_error(self) -> None:
        """An entry with func=None should produce an error issue."""
        TypeRegistry.conversion_map[(str, int)] = TypeConverterEntry(
            func=None,  # pyright: ignore[reportArgumentType]
            from_type=str,
            to_type=int,
        )
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        type_errors = [i for i in issues if i.registry == "TYPE_REGISTRY" and i.severity == "error"]
        assert len(type_errors) >= 1
        assert any("callable" in i.message.lower() for i in type_errors)

    def test_type_registry_none_from_type_error(self) -> None:
        """An entry with from_type=None should produce an error issue."""
        TypeRegistry.conversion_map[(None, int)] = TypeConverterEntry(  # pyright: ignore[reportIndexIssue]
            func=int,
            from_type=None,  # pyright: ignore[reportArgumentType]
            to_type=int,
        )
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        type_errors = [i for i in issues if i.registry == "TYPE_REGISTRY" and i.severity == "error"]
        assert len(type_errors) >= 1
        assert any("from_type" in i.message.lower() or "type" in i.message.lower() for i in type_errors)


class TestStrictMode:
    def test_strict_mode_raises_on_errors(self) -> None:
        """With strict=True, any error-level issue causes RegistryValidationError to be raised."""
        restore_catalog({})
        with pytest.raises(RegistryValidationError) as exc_info:
            validate_registries(STATE_REGISTRY, TYPE_REGISTRY, strict=True)
        # The exception message should include issue count or summary
        assert str(exc_info.value)

    def test_nonstrict_mode_logs_warnings(self) -> None:
        """In non-strict mode, validation issues are returned but no exception is raised."""
        restore_catalog({})
        # Should not raise even though there are error issues
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY, strict=False)
        assert len(issues) >= 1
        assert any(i.severity == "error" for i in issues)


class TestIssueDataclass:
    def test_issue_is_frozen_dataclass(self) -> None:
        """RegistryValidationIssue should be a frozen dataclass."""
        issue = RegistryValidationIssue(registry="STATE_REGISTRY", severity="error", message="test")
        assert issue.registry == "STATE_REGISTRY"
        assert issue.severity == "error"
        assert issue.message == "test"
        with pytest.raises((AttributeError, TypeError)):
            issue.registry = "other"  # pyright: ignore[reportAttributeAccessIssue]

    def test_validate_registries_returns_list(self) -> None:
        """validate_registries() always returns a list."""
        result = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        assert isinstance(result, list)


class TestDeviceClassDimensionRemoved:
    """The dead device_class dimension is gone from the public writers, and the
    single-key override mechanism it would have complicated still works.
    """

    def test_register_signature_has_no_device_class_param(self) -> None:
        """StateRegistry.register no longer accepts a device_class parameter."""
        params = inspect.signature(StateRegistry.register).parameters
        assert "device_class" not in params
        assert set(params) == {"state_class", "domain"}

    def test_domain_override_replaces_built_in_class(self) -> None:
        """A subclass declaring the same Literal domain as a built-in replaces it in the
        catalog — the documented override pattern (docs/pages/core-concepts/states/
        conversion.md, "Overriding a Domain Mapping").
        """
        assert resolve(domain="sensor") is SensorState

        class CustomSensorState(SensorState):
            domain: Literal["sensor"]  # pyright: ignore[reportIncompatibleVariableOverride]

        assert resolve(domain="sensor") is CustomSensorState
        assert STATE_REGISTRY.resolve(domain="sensor") is CustomSensorState
