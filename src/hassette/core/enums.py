from enum import StrEnum, auto


class ResourceStatus(StrEnum):
    """Enumeration for resource status."""

    NOT_STARTED = auto()
    """The resource has not been started yet."""

    RUNNING = auto()
    """The resource is currently running."""

    STOPPED = auto()
    """The resource has been stopped without errors."""

    FAILED = auto()
    """The resource has failed with a recoverable error."""

    CRASHED = auto()
    """The resource has crashed unexpectedly and cannot recover."""


class ResourceRole(StrEnum):
    """Enumeration for resource roles."""

    CORE = "Core"
    """Only used by Hassette directly, as it does not inherit from Resource."""

    BASE = "Base"
    """The base role for all resources."""

    SERVICE = "Service"
    """A service resource."""

    RESOURCE = "Resource"
    """A generic resource."""

    APP = "App"
    """An application resource."""

    UNKNOWN = "Unknown"
    """An unknown or unclassified resource."""
