from yarl import URL


class FatalError(Exception):
    """Custom exception to indicate a fatal error in the application.

    Exceptions that indicate that the service should not be restarted should inherit from this class.
    """


class BaseUrlRequiredError(FatalError):
    """Custom exception to indicate that the base_url configuration is required."""


class IPV6NotSupportedError(FatalError):
    """Custom exception to indicate that IPv6 addresses are not supported in base_url."""


class SchemeRequiredInBaseUrlError(FatalError):
    """Custom exception to indicate that the base_url must include a scheme (http:// or https://)."""


class ConnectionClosedError(Exception):
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


class FailedMessageError(Exception):
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


class InvalidInheritanceError(TypeError):
    """Raised when a class inherits from App incorrectly."""


class UndefinedUserConfigError(TypeError):
    """Raised when a class does not define a user_config_class."""


class EntityNotFoundError(ValueError):
    """Custom error for handling 404 in the Api"""


class ResourceNotReadyError(Exception):
    """Custom exception to indicate that a resource is not ready for use."""


class AppPrecheckFailedError(Exception):
    """Custom exception to indicate that one or more prechecks for an app failed."""


class CannotOverrideFinalError(TypeError):
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
