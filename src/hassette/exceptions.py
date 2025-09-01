class FatalError(Exception):
    """Custom exception to indicate a fatal error in the application.

    Exceptions that indicate that the service should not be restarted should inherit from this class.
    """


class ConnectionClosedError(Exception):
    """Custom exception to indicate that the WebSocket connection was closed unexpectedly."""


class CouldNotFindHomeAssistantError(FatalError):
    """Custom exception to indicate that the Home Assistant instance could not be found."""

    def __init__(self, url: str):
        super().__init__(f"Could not find Home Assistant instance at {url}, ensure it is running and accessible")


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
