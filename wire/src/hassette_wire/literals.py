from typing import Annotated, Literal

from hassette_wire.lenient import LenientValue, UnknownValue

SourceTier = Literal["app", "framework"]
"""Identifies whether a telemetry record originates from a user app or the framework itself.

Log lines use ``LogAuthor`` instead: same values, but it names who wrote the line, not who owns the record.
"""

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
"""Log levels for configuring logging."""

LogAuthor = Literal["app", "framework"]
"""Who wrote a log line: a user app's own code, or Hassette (including framework code acting for an app).

Not ``SourceTier``: an app's Bus or Api logs as ``'framework'`` even though its records' ``SourceTier`` is ``'app'``.
"""

CLOSED_VOCABULARIES = (SourceTier, LogLevel, LogAuthor)
"""Vocabularies that stay strict in response models: adding a value to one is a breaking wire change, not
version skew. Every other enum or ``Literal`` a response carries uses an ``Open<TypeName>`` alias."""

QuerySourceTier = Literal["app", "framework", "all"]
"""Valid source_tier values for query-side filtering. 'all' disables the filter."""

QueryAuthor = Literal["app", "framework", "all"]
"""Valid ``author`` values for log queries. 'all' disables the filter; omitting it applies the default view."""

ErrorRateClass = Literal["good", "warn", "bad"]
"""CSS classification for error rate percentage."""

OpenErrorRateClass = Annotated[ErrorRateClass | UnknownValue, LenientValue("ErrorRateClass")]

HealthStatus = Literal["excellent", "good", "warning", "critical"]
"""Health bar classification from success-rate percentage.

Does NOT include ``"unknown"`` — zero-invocation apps return ``"excellent"``.
"""

OpenHealthStatus = Annotated[HealthStatus | UnknownValue, LenientValue("HealthStatus")]

ListenerKind = Literal["state change", "service call", "event"]
"""Kind of listener event (3 values)."""

OpenListenerKind = Annotated[ListenerKind | UnknownValue, LenientValue("ListenerKind")]

SystemHealthStatus = Literal["ok", "degraded", "starting"]
"""System-level health status (3 values).

Mirrors ``SystemStatusResponse.status`` defined in this package (``health.py``).
"""

OpenSystemHealthStatus = Annotated[SystemHealthStatus | UnknownValue, LenientValue("SystemHealthStatus")]

ExecutionKind = Literal["handler", "job"]
"""Whether an execution is a bus handler invocation or a scheduled-job execution."""

OpenExecutionKind = Annotated[ExecutionKind | UnknownValue, LenientValue("ExecutionKind")]

BootIssueSeverity = Literal["err", "warn"]
"""Severity of a boot-time issue."""

OpenBootIssueSeverity = Annotated[BootIssueSeverity | UnknownValue, LenientValue("BootIssueSeverity")]

HandlerKind = Literal["listener", "job"]
"""Whether a handler reference names a bus listener or a scheduled job."""

OpenHandlerKind = Annotated[HandlerKind | UnknownValue, LenientValue("HandlerKind")]

AppAction = Literal["start", "stop", "reload"]
"""A lifecycle action requested on an app or one of its instances."""

OpenAppAction = Annotated[AppAction | UnknownValue, LenientValue("AppAction")]

InstanceResult = Literal["succeeded", "failed", "refused"]
"""What an app action did to one instance: see ``InstanceOutcome``."""

OpenInstanceResult = Annotated[InstanceResult | UnknownValue, LenientValue("InstanceResult")]

AcceptedStatus = Literal["accepted"]
"""The ``status`` of a response confirming the server accepted a requested action."""

OpenAcceptedStatus = Annotated[AcceptedStatus | UnknownValue, LenientValue("AcceptedStatus")]

LivenessStatus = Literal["live"]
"""The ``status`` of a liveness probe answer."""

OpenLivenessStatus = Annotated[LivenessStatus | UnknownValue, LenientValue("LivenessStatus")]

ApiWriteKind = Literal[
    "call_service", "fire_event", "set_state", "delete_entity", "helper_create", "helper_update", "helper_delete"
]
"""Which named ``Api`` write produced a recorded API write. ``turn_on``/``turn_off``/``toggle``, ``notify`` and the
counter helpers record as ``call_service``."""

OpenApiWriteKind = Annotated[ApiWriteKind | UnknownValue, LenientValue("ApiWriteKind")]

ApiWriteOutcome = Literal["pending", "success", "rejected", "connection_lost", "unresolved", "not_sent"]
"""How a recorded API write ended. ``pending``: not resolved yet. ``success``: Home Assistant's handler returned,
not that the device changed. ``rejected``: Home Assistant answered with an error. ``connection_lost``: sent, then the
connection ended or the request was abandoned before a reply; outcome unknown. ``unresolved``: sent, but how it ended
wasn't recorded (evicted from tracking, or still pending at the next start); outcome unknown. ``not_sent``: never
reached Home Assistant."""

OpenApiWriteOutcome = Annotated[ApiWriteOutcome | UnknownValue, LenientValue("ApiWriteOutcome")]

ListenerMissReason = Literal[
    "filter",
    "throttled",
    "debounce_superseded",
    "once_spent",
    "busy",
    "queue_full",
    "backpressure",
    "hold_cancelled",
    "hold_recheck_failed",
    "hold_entity_missing",
]
"""Why an event that reached an app listener didn't run its handler. ``filter``: a ``where``, ``changed_from``,
``changed_to`` or caller-passed ``changed=`` filter rejected it. ``throttled``: inside the throttle window.
``debounce_superseded``: a later event restarted the debounce. ``once_spent``: a ``once=True`` listener had already
fired. ``busy``: a ``single`` listener was still running. ``queue_full``: a ``queued`` listener's queue was full.
``backpressure``: dispatch was saturated and the listener uses ``drop_newest``. ``hold_cancelled``: the entity left
the target state during a ``duration`` hold. ``hold_recheck_failed``: at the end of the hold the cached state no
longer matched. ``hold_entity_missing``: at the end of the hold the entity was missing from the cache."""

OpenListenerMissReason = Annotated[ListenerMissReason | UnknownValue, LenientValue("ListenerMissReason")]
