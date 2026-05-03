"""Tests for registry validation — WP04.

The global _isolate_registries fixture in conftest.py snapshots/restores both
StateRegistry and TypeRegistry before/after every test, so mutations here do
not bleed between tests.
"""

import pytest

from hassette.conversion import STATE_REGISTRY, TYPE_REGISTRY
from hassette.conversion.state_registry import StateKey, StateRegistry
from hassette.conversion.type_registry import TypeConverterEntry, TypeRegistry
from hassette.conversion.validation import RegistryValidationIssue, validate_registries
from hassette.exceptions import RegistryValidationError
from hassette.models.states.base import BaseState

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRealRegistriesPass:
    def test_real_registries_pass_validation(self) -> None:
        """Running validate_registries() against the real (unmodified) registries produces zero issues."""
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        assert issues == [], f"Expected no issues, got: {issues}"


class TestEmptyRegistryErrors:
    def test_empty_state_registry_error(self) -> None:
        """Clearing STATE_REGISTRY should produce an error issue with 'empty' in the message."""
        StateRegistry.restore({})
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        state_issues = [i for i in issues if i.registry == "STATE_REGISTRY"]
        assert len(state_issues) >= 1
        error_issues = [i for i in state_issues if i.severity == "error"]
        assert len(error_issues) >= 1
        assert "empty" in error_issues[0].message.lower()

    def test_empty_type_registry_error(self) -> None:
        """Clearing TYPE_REGISTRY should produce an error issue with 'empty' in the message."""
        TypeRegistry.restore({})
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        type_issues = [i for i in issues if i.registry == "TYPE_REGISTRY"]
        assert len(type_issues) >= 1
        error_issues = [i for i in type_issues if i.severity == "error"]
        assert len(error_issues) >= 1
        assert "empty" in error_issues[0].message.lower()


class TestStateRegistryValidation:
    def test_state_registry_none_domain_error(self) -> None:
        """An entry with StateKey(domain=None) should produce an error issue."""

        class NoDomainState(BaseState):
            domain: "str"

        StateRegistry._registry[StateKey(domain=None)] = NoDomainState
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        state_errors = [i for i in issues if i.registry == "STATE_REGISTRY" and i.severity == "error"]
        assert len(state_errors) >= 1
        # At least one mentions domain or None
        assert any("domain" in i.message.lower() or "none" in i.message.lower() for i in state_errors)

    def test_state_registry_non_subclass_error(self) -> None:
        """An entry whose value is not a BaseState subclass should produce an error issue."""

        class NotAState:
            pass

        StateRegistry._registry[StateKey(domain="fake_domain")] = NotAState  # pyright: ignore[reportArgumentType]
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

        StateRegistry._registry[StateKey(domain="dup_domain")] = StateA
        StateRegistry._registry[StateKey(domain="dup_domain", device_class="some_class")] = StateB
        # Inject another entry with same domain but different key to test duplicate detection
        # Actually, duplicate domain means two keys with the same .domain value
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY)
        dup_warnings = [
            i for i in issues if i.registry == "STATE_REGISTRY" and i.severity == "warning" and "dup" in i.message
        ]
        assert len(dup_warnings) >= 1


class TestTypeRegistryValidation:
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
        StateRegistry.restore({})
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
        StateRegistry._registry[StateKey(domain="warn_domain")] = StateA
        StateRegistry._registry[StateKey(domain="warn_domain", device_class="dc")] = StateB

        # This should not raise — warnings only
        issues = validate_registries(STATE_REGISTRY, TYPE_REGISTRY, strict=True)
        warnings = [i for i in issues if i.severity == "warning"]
        assert len(warnings) >= 1

    def test_nonstrict_mode_logs_warnings(self) -> None:
        """In non-strict mode, validation issues are returned but no exception is raised."""
        StateRegistry.restore({})
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
