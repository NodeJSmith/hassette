from typing import TYPE_CHECKING, Any

from yarl import URL

if TYPE_CHECKING:
    from hassette.models.states import BaseState

MAX_ISSUES_IN_SUMMARY = 5


class HassetteError(Exception):
    """Base exception for all Hassette errors."""


class FatalError(HassetteError):
    """Custom exception to indicate a fatal error in the application.

    Exceptions that indicate that the service should not be restarted should inherit from this class.
    """


class BaseUrlRequiredError(FatalError):
    """Custom exception to indicate that the base_url configuration is required."""


class IPV6NotSupportedError(FatalError):
    """Custom exception to indicate that IPv6 addresses are not supported in base_url."""


class SchemeRequiredInBaseUrlError(FatalError):
    """Custom exception to indicate that the base_url must include a scheme (http:// or https://)."""


class ConnectionClosedError(HassetteError):
    """Custom exception to indicate that the WebSocket connection was closed unexpectedly."""


class SchemaVersionError(HassetteError):
    """Raised when the on-disk database schema version is ahead of the code's expected head.

    This indicates the database was created by a newer binary. The service should not
    auto-delete the database in this case; manual intervention is required.

    Listed in ``DatabaseService.restart_spec.fatal_error_names`` so the ServiceWatcher
    triggers immediate shutdown (FAILED path) rather than retrying.
    """


class CouldNotFindHomeAssistantError(FatalError):
    """Custom exception to indicate that the Home Assistant instance could not be found."""

    def __init__(self, url: str):
        yurl = URL(url)
        msg = f"Could not find Home Assistant instance at {url}, ensure it is running and accessible"
        if not yurl.explicit_port:
            msg += " and that the port is specified if necessary"
        super().__init__(msg)


class RetryableConnectionClosedError(ConnectionClosedError):
    """Custom exception to indicate that the WebSocket connection was closed but can be retried."""

    def __init__(self, msg: str, *, close_code: int | None = None) -> None:
        super().__init__(msg)
        self.close_code = close_code


class FailedMessageError(HassetteError):
    """Custom exception to indicate that a message sent to the WebSocket failed.

    Exposes HA's structured error surface as instance attributes so callers can
    react programmatically::

        try:
            await api.update_input_boolean(
                "vacation_mode",
                UpdateInputBooleanParams(initial=False),
            )
        except FailedMessageError as e:
            if e.code == "not_found":
                # Helper was deleted between list and update — recreate it
                ...

    ``code`` is populated when the error originates from an HA error envelope
    (see ``FailedMessageError.from_error_response``). It is ``None`` for
    locally-synthesized failures such as transport timeouts.
    """

    def __init__(
        self,
        msg: str,
        *,
        code: str | None = None,
        original_data: dict | None = None,
    ) -> None:
        super().__init__(msg)
        self.code = code
        self.original_data = original_data

    @classmethod
    def from_error_response(
        cls,
        error: str | None = None,
        code: str | None = None,
        original_data: dict | None = None,
    ) -> "FailedMessageError":
        msg = f"WebSocket message failed with response '{error}' (data={original_data})"
        return cls(msg, code=code, original_data=original_data)


class InvalidAuthError(FatalError):
    """Custom exception to indicate that the authentication token is invalid."""


class InvalidInheritanceError(TypeError, HassetteError):
    """Raised when a class inherits from App incorrectly."""


class UndefinedUserConfigError(TypeError, HassetteError):
    """Raised when a class does not define a user_config_class."""


class EntityNotFoundError(ValueError, HassetteError):
    """Custom error for handling 404 in the Api"""


class ResourceNotReadyError(HassetteError):
    """Custom exception to indicate that a resource is not ready for use."""


class AppPrecheckFailedError(HassetteError):
    """Custom exception to indicate that one or more prechecks for an app failed."""


class CannotOverrideFinalError(TypeError, HassetteError):
    """Custom exception to indicate that a final method or class cannot be overridden."""

    def __init__(
        self,
        method_name: str,
        origin_name: str,
        subclass_name: str,
        suggested_alt: str | None = None,
        location: str | None = None,
    ):
        msg = (
            f"App '{subclass_name}' attempted to override the final lifecycle method "
            f"'{method_name}' defined in {origin_name!r}. "
        )
        if suggested_alt:
            msg += f"Use '{suggested_alt}' instead."
        if location:
            msg += f" (at {location})"
        super().__init__(msg)


class DependencyError(HassetteError):
    """Base class for dependency-related errors."""


class DependencyInjectionError(DependencyError):
    """Raised when dependency injection fails due to invalid handler signature or annotations.

    This exception indicates a user error in handler definition, such as:
    - Using invalid parameter types (*args, positional-only)
    - Missing required type annotations
    - Incompatible annotation types

    These errors should be fixed by updating the handler signature.
    """


class DependencyResolutionError(DependencyError):
    """Raised when dependency injection fails during runtime extraction or conversion.

    This exception indicates a runtime issue with:
    - Extracting parameter values from events
    - Converting values to expected types
    - Type mismatches between extracted values and annotations

    These errors may indicate issues with event data, converter logic, or type registry.
    """


class StateRegistryError(HassetteError):
    """Base exception for state registry errors."""


class RegistryNotReadyError(StateRegistryError):
    """Raised when attempting to use the registry before any classes are registered."""

    def __init__(self) -> None:
        super().__init__(
            "State registry has not been initialized. "
            "No state classes have been registered yet. "
            "Ensure state modules are imported before attempting state conversion."
        )


class NoDomainAnnotationError(StateRegistryError):
    """Raised when a state class does not define a domain annotation or the annotation is empty.

    Generally ignored, this indicates that the class is a base class and not intended to be registered.

    """

    def __init__(self, state_class: type["BaseState[Any]"]) -> None:
        super().__init__(
            f"State class {state_class.__name__} does not define a domain annotation or the annotation is empty."
        )
        self.state_class = state_class


class DomainNotFoundError(StateRegistryError):
    """Raised when no state class is found for a given domain."""

    def __init__(self, domain: str):
        super().__init__(f"No state class found for domain '{domain}'.")
        self.domain = domain


class HassetteNotInitializedError(RuntimeError):
    """Exception raised when Hassette is not initialized in the current context."""


class InvalidDataForStateConversionError(StateRegistryError):
    """Raised when the data provided for state conversion is invalid or malformed."""

    def __init__(self, data: Any):
        super().__init__(f"Invalid or malformed data provided for state conversion: {data!r}")
        self.data = data


class UnableToConvertStateError(StateRegistryError):
    """Raised when a state dictionary cannot be converted to a specific state class."""

    def __init__(self, entity_id: str, state_class: type["BaseState"]) -> None:
        super().__init__(f"Unable to convert state for entity_id '{entity_id}' to class {state_class.__name__}.")
        self.entity_id = entity_id
        self.state_class = state_class


class ConvertedTypeDoesNotMatchError(StateRegistryError):
    """Raised when a converted state does not match the expected type."""

    def __init__(self, entity_id: str, expected_class: type["BaseState"], actual_class: type["BaseState"]) -> None:
        super().__init__(
            f"Converted state for entity_id '{entity_id}' is of type {actual_class.__name__}, "
            f"expected {expected_class.__name__}."
        )
        self.entity_id = entity_id
        self.expected_class = expected_class
        self.actual_class = actual_class


class InvalidEntityIdError(StateRegistryError):
    """Raised when an entity ID is invalid or malformed."""

    def __init__(self, entity_id: Any):
        super().__init__(f"Invalid or malformed entity ID: {entity_id!r}")
        self.entity_id = entity_id


class UnableToConvertValueError(HassetteError):
    """Raised when a raw value cannot be converted from one type to another via the TypeRegistry."""


class InvalidLifecycleTransitionError(HassetteError):
    """Raised when a ResourceStatus transition is invalid in strict lifecycle mode.

    Only raised when ``HassetteConfig.strict_lifecycle`` is True. In non-strict
    mode the same condition logs a WARNING instead.

    Attributes:
        from_status: The status the resource was in before the attempted transition.
        to_status: The status the resource was attempting to transition to.
        resource_name: The unique_name of the resource that made the invalid transition.
    """

    def __init__(self, from_status: Any, to_status: Any, resource_name: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.resource_name = resource_name
        super().__init__(f"Invalid lifecycle transition for '{resource_name}': {from_status!r} → {to_status!r}")


class ListenerNameRequiredError(HassetteError):
    """Raised at call time when ``name=`` is omitted on a DB-registered listener.

    Attributes:
        handler_method: Fully-qualified name of the handler function.
        topic: The event topic the listener was being registered for.
    """

    def __init__(self, handler_method: str, topic: str) -> None:
        self.handler_method = handler_method
        self.topic = topic
        super().__init__(
            f"Listener registration requires a name.\n\n"
            f"  handler: {handler_method}\n"
            f"  topic:   {topic}\n\n"
            f"Provide a stable name via the `name=` parameter:\n\n"
            f'  await self.bus.on_state_change({topic!r}, handler=self.handler, name="my_listener")'
        )


class DuplicateListenerError(HassetteError):
    """Raised at call time when a second listener with the same ``(name, topic)`` is
    registered within the same app instance in the same session.

    Detected in-memory by the Bus before any database write. Cross-session duplicates
    are handled by upsert and are not an error.

    Attributes:
        name: The stable name that collided.
        topic: The event topic both listeners were registered for.
        existing_handler: Fully-qualified name of the already-registered handler.
        duplicate_handler: Fully-qualified name of the handler that triggered the error.
    """

    def __init__(self, name: str, topic: str, existing_handler: str, duplicate_handler: str) -> None:
        self.name = name
        self.topic = topic
        self.existing_handler = existing_handler
        self.duplicate_handler = duplicate_handler
        super().__init__(
            f"A listener named {name!r} is already registered for topic {topic!r}.\n\n"
            f"  existing handler: {existing_handler}\n"
            f"  duplicate handler: {duplicate_handler}\n\n"
            f"Use a different name for the second listener, or remove the first registration before re-registering."
        )


class RegistryValidationError(HassetteError):
    """Raised when startup registry validation finds error-level issues.

    Raised by ``validate_registries(strict=True)`` after collecting all issues.
    ``Hassette.wire_services()`` passes ``strict=config.strict_lifecycle``, so in
    production this only fires when the user explicitly enables strict mode.

    Attributes:
        issues: The full list of validation issues found. Always contains at least
            one error-severity issue when this exception is raised.
    """

    def __init__(self, issues: list[Any]) -> None:
        self.issues = issues
        error_count = sum(1 for i in issues if getattr(i, "severity", None) == "error")
        warning_count = sum(1 for i in issues if getattr(i, "severity", None) == "warning")
        total = len(issues)
        summary_lines = [f"Registry validation failed: {error_count} error(s), {warning_count} warning(s)"]
        summary_lines.extend(
            f"  [{i.severity.upper()}] {i.registry}: {i.message}" for i in issues[:MAX_ISSUES_IN_SUMMARY]
        )
        if total > MAX_ISSUES_IN_SUMMARY:
            summary_lines.append(f"  ... and {total - MAX_ISSUES_IN_SUMMARY} more issue(s)")
        super().__init__("\n".join(summary_lines))
