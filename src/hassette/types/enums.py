from enum import StrEnum, auto


class Topic(StrEnum):
    # hassette events

    HASSETTE_EVENT_SERVICE_STATUS = "hassette.event.service_status"
    """Service status updates"""

    HASSETTE_EVENT_WEBSOCKET_CONNECTED = "hassette.event.websocket_connected"
    """WebSocket connection established"""

    HASSETTE_EVENT_WEBSOCKET_DISCONNECTED = "hassette.event.websocket_disconnected"
    """WebSocket connection lost"""

    HASSETTE_EVENT_FILE_WATCHER = "hassette.event.file_watcher"
    """File watcher events"""

    HASSETTE_EVENT_APP_LOAD_COMPLETED = "hassette.event.app_load_completed"
    """Application load completion events"""

    # Home Assistant events

    HASS_EVENT_STATE_CHANGED = "hass.event.state_changed"
    """State change events"""

    HASS_EVENT_CALL_SERVICE = "hass.event.call_service"
    """Service call events"""

    HASS_EVENT_COMPONENT_LOADED = "hass.event.component_loaded"
    """Component loaded events"""

    HASS_EVENT_SERVICE_REGISTERED = "hass.event.service_registered"
    """Service registered events"""

    HASS_EVENT_SERVICE_REMOVED = "hass.event.service_removed"
    """Service removed events"""

    HASS_EVENT_LOGBOOK_ENTRY = "hass.event.logbook_entry"
    """Logbook entry events"""

    HASS_EVENT_USER_ADDED = "hass.event.user_added"
    """User added events"""

    HASS_EVENT_USER_REMOVED = "hass.event.user_removed"
    """User removed events"""

    HASS_EVENT_AUTOMATION_TRIGGERED = "hass.event.automation_triggered"
    """Automation triggered events"""

    HASS_EVENT_SCRIPT_STARTED = "hass.event.script_started"
    """Script started events"""


class ResourceStatus(StrEnum):
    """Enumeration for resource status."""

    NOT_STARTED = auto()
    """The resource has not been started yet."""

    STARTING = auto()
    """The resource is in the process of starting."""

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
