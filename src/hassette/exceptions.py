import typing
from typing import Any

from yarl import URL

if typing.TYPE_CHECKING:
    from hassette.models.states import BaseState


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


class FailedMessageError(HassetteError):
    """Custom exception to indicate that a message sent to the WebSocket failed."""

    @classmethod
    def from_error_response(
        cls,
        error: str | None = None,
        original_data: dict | None = None,
    ):
        msg = f"WebSocket message for failed with response '{error}' (data={original_data})"
        return cls(msg)


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
        """Initialize the error."""
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
        """Initialize the error with the offending class.

        Args:
            state_class: The class that lacks a domain annotation.
        """
        super().__init__(
            f"State class {state_class.__name__} does not define a domain annotation or the annotation is empty."
        )
        self.state_class = state_class


class DomainNotFoundError(StateRegistryError):
    """Raised when no state class is found for a given domain."""

    def __init__(self, domain: str):
        """Initialize the error with the offending domain.

        Args:
            domain: The domain that has no associated state class.
        """
        super().__init__(f"No state class found for domain '{domain}'.")
        self.domain = domain


class HassetteNotInitializedError(RuntimeError):
    """Exception raised when Hassette is not initialized in the current context."""


class InvalidDataForStateConversionError(StateRegistryError):
    """Raised when the data provided for state conversion is invalid or malformed."""

    def __init__(self, data: Any):
        """Initialize the error with the offending data.

        Args:
            data: The invalid data provided for state conversion.
        """
        super().__init__(f"Invalid or malformed data provided for state conversion: {data!r}")
        self.data = data


class UnableToConvertStateError(StateRegistryError):
    """Raised when a state dictionary cannot be converted to a specific state class."""

    def __init__(self, entity_id: str, state_class: type["BaseState"]) -> None:
        """Initialize the error with the offending entity ID.

        Args:
            entity_id: The entity ID that could not be converted.
            state_class: The state class that conversion was attempted to.
        """
        super().__init__(f"Unable to convert state for entity_id '{entity_id}' to class {state_class.__name__}.")
        self.entity_id = entity_id
        self.state_class = state_class


class ConvertedTypeDoesNotMatchError(StateRegistryError):
    """Raised when a converted state does not match the expected type."""

    def __init__(self, entity_id: str, expected_class: type["BaseState"], actual_class: type["BaseState"]) -> None:
        """Initialize the error with the offending entity ID.

        Args:
            entity_id: The entity ID that was converted.
            expected_class: The expected state class.
            actual_class: The actual state class returned.
        """
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
        """Initialize the error with the offending entity ID.

        Args:
            entity_id: The invalid entity ID.
        """
        super().__init__(f"Invalid or malformed entity ID: {entity_id!r}")
        self.entity_id = entity_id


class UnableToConvertValueError(HassetteError):
    """Raised when a raw value cannot be converted from one type to another via the TypeRegistry."""
