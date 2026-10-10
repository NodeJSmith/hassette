from enum import StrEnum, auto

from hassette_wire import BackpressurePolicy, ExecutionMode, ResourceStatus
from hassette_wire import ResourceRole as ResourceRole  # public re-export: hassette.types.enums.ResourceRole

# The contract enums (ResourceStatus, ResourceRole, AppStatus, ExecutionMode, BackpressurePolicy,
# ExecutionStatus) are defined in hassette_wire — one definition, no mirrors. App authors import
# the public ones (ResourceStatus, ExecutionMode, BackpressurePolicy, ExecutionStatus) from
# hassette. This module keeps the non-contract enums and the constants that reference the moved
# ones.

DEFAULT_OVERLAP_MODE: ExecutionMode = ExecutionMode.SINGLE
"""Default overlap mode for registration/summary models when none is resolved yet."""


DEFAULT_BACKPRESSURE_POLICY: BackpressurePolicy = BackpressurePolicy.BLOCK
"""Default backpressure policy for registration/summary models when none is specified."""

TERMINAL_STATUSES: frozenset[ResourceStatus] = frozenset({ResourceStatus.STOPPED, ResourceStatus.EXHAUSTED_DEAD})
"""Resource has reached an end state — shutdown can skip the STOPPING transition."""

ACTIVE_STATUSES: frozenset[ResourceStatus] = frozenset(
    {ResourceStatus.NOT_STARTED, ResourceStatus.STARTING, ResourceStatus.RUNNING}
)
"""Resource is in normal lifecycle progression (not failed, stopped, or exhausted)."""


class ForgottenAwaitBehavior(StrEnum):
    """Controls what happens when a protected method is called without ``await``."""

    IGNORE = auto()
    """Suppress the warning entirely — the forgotten await is silently ignored."""

    WARN = auto()
    """Emit a ``HassetteForgottenAwaitWarning`` (default). Integrates with ``-W error``."""

    ERROR = auto()
    """Emit ``HassetteForgottenAwaitWarning`` in a form that ``filterwarnings("error")`` escalates
    to a raised exception. Under normal filters, behaves identically to ``WARN``."""


class BlockingIOBehavior(StrEnum):
    """Controls what happens when a blocking call is detected on the shared event loop."""

    IGNORE = auto()
    """Suppress detection entirely — no warning AND no ``blocking_events`` row is written.
    This is the deliberate exception to the persist-before-warn rule: ``IGNORE`` means
    "I know this app blocks; treat it as if detection never fired," so there is no audit
    trail for ignored events."""

    WARN = auto()
    """Emit a ``HassetteBlockingIOWarning`` (default). Integrates with ``-W error``."""

    ERROR = auto()
    """Emit ``HassetteBlockingIOWarning`` in a form that ``filterwarnings("error")`` escalates
    to a raised exception. Under normal filters, behaves identically to ``WARN`` — the framework
    does not raise on its own; escalation requires the caller to install the error filter
    (``-W error``, a pytest ``filterwarnings`` marker, or ``warnings.filterwarnings`` at startup).

    The effect of escalation differs by detection tier:

    - **Tier 2 (call-site interception)** detects *before* the blocking primitive runs, so an
      escalated warning raises at the call site and prevents the blocking call from executing.
    - **Tier 1 (loop watchdog)** is warn-after: the stall has already completed when the warning
      fires on the off-loop daemon thread. The daemon suppresses the escalation to stay alive, so
      ``ERROR`` cannot retroactively interrupt a Tier 1 stall — it only records and warns."""


class RestartType(StrEnum):
    """Enumeration for service restart strategies."""

    PERMANENT = auto()
    """The service is permanent and should always be restarted on failure."""

    TRANSIENT = auto()
    """The service is transient — restarts on failure but supports cooldown cycling."""

    TEMPORARY = auto()
    """The service is temporary — once its restart budget is exhausted, it stops permanently."""


class Outcome(StrEnum):
    """The result of handing a trigger to an ``ExecutionModeGuard``."""

    RAN = auto()
    """The invocation was started immediately."""

    QUEUED_ACCEPTED = auto()
    """A ``queued`` trigger was accepted into the pending queue; it will run later."""

    SUPPRESSED = auto()
    """A ``single`` re-fire was dropped because a prior invocation is still running."""

    DROPPED = auto()
    """A ``queued`` trigger was dropped because the pending queue is at its cap."""


class Topic(StrEnum):
    """Event topic identifiers for the internal pub/sub bus."""

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

    HASSETTE_EVENT_APP_STATE_CHANGED = "hassette.event.app_state_changed"
    """App instance state change events"""

    HASSETTE_EVENT_EXECUTION_COMPLETED = "hassette.event.execution_completed"
    """Handler or job execution persisted to the telemetry database"""

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


class BlockReason(StrEnum):
    """Reasons an app may be intentionally blocked from starting."""

    ONLY_APP = auto()
    """Hassette is restricted to specific apps via ``run --app``, so this app is excluded."""


class ConnectionState(StrEnum):
    """Enumeration for WebSocket connection states."""

    DISCONNECTED = auto()
    """The WebSocket connection is not established."""

    CONNECTING = auto()
    """The WebSocket connection is being established."""

    CONNECTED = auto()
    """The WebSocket connection is established and active."""
