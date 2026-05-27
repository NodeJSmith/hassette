"""Registry validation for Hassette startup.

Provides ``validate_registries()`` which inspects the STATE_REGISTRY and
TYPE_REGISTRY singletons for common misconfiguration issues and returns a
list of ``RegistryValidationIssue`` dataclasses.

In strict mode (``strict=True``) any error-level issue causes
``RegistryValidationError`` to be raised after all issues have been collected
(fail-all, not fail-fast). In non-strict mode issues are logged as WARNINGs.
"""

from dataclasses import dataclass
from logging import getLogger

from hassette.conversion.state_registry import StateKey, StateRegistry
from hassette.conversion.type_registry import TypeRegistry
from hassette.exceptions import RegistryValidationError

LOGGER = getLogger(__name__)


@dataclass(frozen=True)
class RegistryValidationIssue:
    """A single issue found during registry validation.

    Attributes:
        registry: Which registry produced the issue — ``"STATE_REGISTRY"`` or
            ``"TYPE_REGISTRY"``.
        severity: ``"error"`` for issues that indicate broken/missing
            registrations; ``"warning"`` for non-fatal anomalies such as
            duplicate domain registrations.
        message: Human-readable description of the issue.
    """

    registry: str
    severity: str
    message: str


def validate_registries(
    state_registry: StateRegistry,
    type_registry: TypeRegistry,
    *,
    strict: bool = False,
) -> list[RegistryValidationIssue]:
    """Validate STATE_REGISTRY and TYPE_REGISTRY contents at startup.

    Collects ALL issues before raising or logging — never fail-fast.

    Args:
        state_registry: The ``StateRegistry`` singleton to validate.
        type_registry: The ``TypeRegistry`` singleton to validate.
        strict: When ``True``, raise ``RegistryValidationError`` if any
            error-severity issues are found.  When ``False`` (default), log
            each issue as a WARNING.

    Returns:
        A list of ``RegistryValidationIssue`` instances (empty when everything
        is healthy).

    Raises:
        RegistryValidationError: In strict mode when at least one error-level
            issue is present.
    """
    issues: list[RegistryValidationIssue] = []

    issues.extend(_validate_state_registry(state_registry))
    issues.extend(_validate_type_registry(type_registry))

    _apply_mode(issues, strict=strict)
    return issues


def _validate_state_registry(state_registry: StateRegistry) -> list[RegistryValidationIssue]:
    """Run all STATE_REGISTRY checks and return the collected issues."""
    # Deferred import: models.states.base → conversion → validation → models.states.base.
    # Safe here because validate_registries() runs after all modules are loaded.
    from hassette.models.states.base import BaseState

    issues: list[RegistryValidationIssue] = []
    registry_name = "STATE_REGISTRY"

    entries = dict(state_registry._registry)

    if not entries:
        issues.append(
            RegistryValidationIssue(
                registry=registry_name,
                severity="error",
                message=(
                    "STATE_REGISTRY is empty — models package may not be imported. "
                    "Ensure hassette.models.states is imported before wire_services()."
                ),
            )
        )
        return issues

    seen_domains: dict[object, type] = {}

    for key, cls in entries.items():
        try:
            is_subclass = isinstance(cls, type) and issubclass(cls, BaseState)
        except TypeError:
            is_subclass = False

        if not is_subclass:
            issues.append(
                RegistryValidationIssue(
                    registry=registry_name,
                    severity="error",
                    message=(
                        f"Registry entry for key {key!r} is not a BaseState subclass: "
                        f"{cls!r}. Only BaseState subclasses may be registered."
                    ),
                )
            )

        if not isinstance(key, StateKey) or key.domain is None:
            issues.append(
                RegistryValidationIssue(
                    registry=registry_name,
                    severity="error",
                    message=(
                        f"Registry entry for key {key!r} has a None domain. "
                        "Every registered state class must have a non-None domain."
                    ),
                )
            )
            continue

        domain = key.domain

        if domain in seen_domains:
            existing_cls = seen_domains[domain]
            issues.append(
                RegistryValidationIssue(
                    registry=registry_name,
                    severity="warning",
                    message=(
                        f"Duplicate domain '{domain}' registered by both "
                        f"{existing_cls.__name__!r} (wins) and {getattr(cls, '__name__', repr(cls))!r}. "
                        "The first-registered class takes precedence."
                    ),
                )
            )
        else:
            seen_domains[domain] = cls

    return issues


def _validate_type_registry(type_registry: TypeRegistry) -> list[RegistryValidationIssue]:
    """Run all TYPE_REGISTRY checks and return the collected issues."""
    issues: list[RegistryValidationIssue] = []
    registry_name = "TYPE_REGISTRY"

    entries = dict(type_registry.conversion_map)

    if not entries:
        issues.append(
            RegistryValidationIssue(
                registry=registry_name,
                severity="error",
                message=(
                    "TYPE_REGISTRY is empty — conversion module may not have loaded. "
                    "Ensure hassette.conversion is imported before wire_services()."
                ),
            )
        )
        return issues

    for (from_type, to_type), entry in entries.items():
        if not callable(entry.func):
            issues.append(
                RegistryValidationIssue(
                    registry=registry_name,
                    severity="error",
                    message=(
                        f"TypeConverterEntry for ({from_type!r} → {to_type!r}) has a non-callable "
                        f"func: {entry.func!r}. Every converter must be callable."
                    ),
                )
            )

        if not isinstance(from_type, type):
            issues.append(
                RegistryValidationIssue(
                    registry=registry_name,
                    severity="error",
                    message=(
                        f"TypeConverterEntry has invalid from_type={from_type!r} "
                        f"(type: {type(from_type).__name__}). from_type must be a Python type."
                    ),
                )
            )

        if not isinstance(to_type, type):
            issues.append(
                RegistryValidationIssue(
                    registry=registry_name,
                    severity="error",
                    message=(
                        f"TypeConverterEntry has invalid to_type={to_type!r} "
                        f"(type: {type(to_type).__name__}). to_type must be a Python type."
                    ),
                )
            )

        error_types_ok = isinstance(entry.error_types, tuple) and all(
            isinstance(et, type) and issubclass(et, BaseException) for et in entry.error_types
        )
        if not error_types_ok:
            issues.append(
                RegistryValidationIssue(
                    registry=registry_name,
                    severity="error",
                    message=(
                        f"TypeConverterEntry for ({from_type!r} → {to_type!r}) has invalid "
                        f"error_types={entry.error_types!r}. Must be a tuple of BaseException subclasses."
                    ),
                )
            )

    return issues


def _apply_mode(issues: list[RegistryValidationIssue], *, strict: bool) -> None:
    """Log or raise based on issues and mode."""
    if not issues:
        LOGGER.debug("Registry validation: OK")
        return

    error_issues = [i for i in issues if i.severity == "error"]

    if strict and error_issues:
        for issue in issues:
            LOGGER.warning("[%s] %s: %s", issue.severity.upper(), issue.registry, issue.message)
        raise RegistryValidationError(issues)

    for issue in issues:
        LOGGER.warning("[%s] %s: %s", issue.severity.upper(), issue.registry, issue.message)

    LOGGER.warning("Registry validation: %d issue(s) found", len(issues))
