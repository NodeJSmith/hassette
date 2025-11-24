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


class UnableToExtractParameterError(HassetteError):
    """Custom exception to indicate that a parameter could not be extracted for dependency injection
    due to an unexpected error.
    """

    def __init__(self, parameter_name: str, parameter_type: type, original_exception: Exception):
        param_type_name = getattr(parameter_type, "__name__", str(parameter_type))

        msg = (
            f"Unable to extract parameter '{parameter_name}' of type '{param_type_name}' "
            f"for dependency injection: {type(original_exception).__name__}: {original_exception}"
        )
        super().__init__(msg)


class InvalidDependencyReturnTypeError(Exception):
    """Exception raised when a dependency is found but cannot be resolved to the expected type."""

    def __init__(self, resolved_type: Any):
        self.resolved_type = resolved_type


class CallListenerError(HassetteError):
    """Custom exception to indicate that a listener could not be called.

    This will also be raised if a DI annotation cannot be resolved to the expected type.
    """


class StateRegistryError(HassetteError):
    """Base exception for state registry errors."""


class StateNotRegisteredError(StateRegistryError):
    """Raised when attempting to access a state class that hasn't been registered."""

    def __init__(self, domain: str) -> None:
        """Initialize the error with the missing domain.

        Args:
            domain: The domain that wasn't found in the registry.
        """
        super().__init__(f"No state class registered for domain: {domain}")
        self.domain = domain


class DuplicateDomainError(StateRegistryError):
    """Raised when attempting to register a domain that's already registered."""

    def __init__(self, domain: str, existing_class: type["BaseState"], new_class: type["BaseState"]) -> None:
        """Initialize the error with domain and conflicting classes.

        Args:
            domain: The domain that's already registered.
            existing_class: The class that's currently registered for this domain.
            new_class: The class that attempted to register for this domain.
        """
        super().__init__(
            f"Domain '{domain}' is already registered to {existing_class.__name__}, "
            f"cannot register {new_class.__name__}"
        )
        self.domain = domain
        self.existing_class = existing_class
        self.new_class = new_class


class RegistryNotReadyError(StateRegistryError):
    """Raised when attempting to use the registry before any classes are registered."""

    def __init__(self) -> None:
        """Initialize the error."""
        super().__init__(
            "State registry has not been initialized. "
            "No state classes have been registered yet. "
            "Ensure state modules are imported before attempting state conversion."
        )
