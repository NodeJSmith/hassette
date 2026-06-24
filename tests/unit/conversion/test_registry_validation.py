"""Tests for registry validation.

The global _isolate_registries fixture in conftest.py snapshots/restores the
state-class catalog before/after every test, so catalog mutations here do not
bleed between tests. TypeRegistry is a stable read-only global after import.
"""

import pytest

from hassette.conversion import STATE_REGISTRY, TYPE_REGISTRY
from hassette.conversion.state_registry import StateKey
from hassette.conversion.type_registry import TypeConverterEntry, TypeRegistry
from hassette.conversion.validation import RegistryValidationIssue, validate_registries
from hassette.exceptions import RegistryValidationError
from hassette.models.states.base import BaseState
from hassette.models.states.catalog import _STATE_CATALOG, restore_catalog


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

    def test_state_registry_duplicate_domain_warning(self) -> None:
        """Two entries sharing the same non-None domain should produce a warning issue."""

        class StateA(BaseState):
            domain: "str"

        class StateB(BaseState):
            domain: "str"

        _STATE_CATALOG[StateKey(domain="dup_domain")] = StateA
        _STATE_CATALOG[StateKey(domain="dup_domain", device_class="some_class")] = StateB
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        dup_warnings = [
            i for i in issues if i.registry == "STATE_REGISTRY" and i.severity == "warning" and "dup" in i.message
        ]
        assert len(dup_warnings) >= 1


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

    def test_strict_mode_does_not_raise_on_warnings_only(self) -> None:
        """With strict=True, warning-only issues must not raise RegistryValidationError."""

        class StateA(BaseState):
            domain: "str"

        class StateB(BaseState):
            domain: "str"

        # Inject duplicate domain to generate a warning-only scenario.
        # We need to ensure the real registries are non-empty (no error) but have a duplicate warning.
        _STATE_CATALOG[StateKey(domain="warn_domain")] = StateA
        _STATE_CATALOG[StateKey(domain="warn_domain", device_class="dc")] = StateB

        # This should not raise — warnings only
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY, strict=True)
        warnings = [i for i in issues if i.severity == "warning"]
        assert len(warnings) >= 1

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
