from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hassette.models.states import BaseState
    from hassette.resources.teardown import TeardownReport

__all__ = [  # packed to stay under the 800-line limit; keep sorted (RUF022) and wrap by hand
    "AppBlockedError", "AppBootstrapNotReleasedError", "AppPrecheckFailedError", "AuthTokenWriteError",
    "BaseUrlRequiredError", "CannotOverrideFinalError", "ConfigError", "ConnectionClosedError",
    "ConvertedTypeDoesNotMatchError", "DependencyError", "DependencyInjectionError", "DependencyResolutionError",
    "DomainNotFoundError", "DomainRequiredError",
    "DuplicateListenerError", "EntityNotFoundError", "EntityNotInViewError", "EntityShapeError", "FailedMessageError",
    "FatalError", "HassetteBlockingIOWarning", "HassetteError", "HassetteForgottenAwaitWarning",
    "HassetteNotInitializedError", "HttpRequestError",
    "IPV6NotSupportedError", "InvalidAuthError", "InvalidDataForStateConversionError",
    "InvalidEntityIdError", "InvalidInheritanceError", "JobRemovedError",
    "LifecycleReentryError", "ListenerNameRequiredError", "NoDomainAnnotationError", "OutcomeUnknownError",
    "RegistryNotReadyError", "RegistryValidationError", "ResourceNotReadyError", "ResponseLostError",
    "ResponseTimeoutError", "RestartRefusedError", "RetryableConnectionClosedError", "SchedulerNameRequiredError",
    "SchemaVersionError", "SchemeRequiredInBaseUrlError", "SensorShapeMismatchError", "ServeEndedError",
    "StateRegistryError", "TaskBucketSealedError", "TelemetryUnavailableError", "TrustedProxyConfigError",
    "UnableToConvertAnnotatedStateError", "UnableToConvertStateError", "UnableToConvertValueError",
    "UndefinedUserConfigError", "WriteQueueUnavailableError",
]  # fmt: skip

MAX_ISSUES_IN_SUMMARY = 5

WS_NOT_CONNECTED_MESSAGE = "WebSocket connection is not established"
"""Shared message for the various ways a caller can observe an unestablished WebSocket connection."""


class HassetteForgottenAwaitWarning(RuntimeWarning):
    """Warning emitted when a protected registration/scheduling method is called without ``await``.

    Fired from ``RegistrationHandle.__del__`` when the handle is garbage-collected without ever being
    awaited, sent to, thrown into, or closed. The message names the owning app and the call site.

    Integrates with ``-W error``/``pytest.warns``/``filterwarnings`` like any ``RuntimeWarning``.
    """


class HassetteBlockingIOWarning(RuntimeWarning):
    """Warning emitted when a blocking call is detected on the shared event loop.

    Fired by Tier 1 (responsiveness watchdog) when loop lag exceeds the configured threshold, whether
    blocking I/O or CPU-bound work held the loop. Also fired by Tier 2 (call-site interception) when a
    blocking I/O primitive is called on the loop thread.
    The message names the offending app, handler/job, and (where available) the source line.

    Integrates with ``-W error``/``pytest.warns``/``filterwarnings`` like any ``RuntimeWarning``.
    """


class HassetteError(Exception):
    """Base exception for all Hassette errors.

    Set ``suggestion`` (as a class attribute or in ``__init__``) on user-facing errors to tell the user how to
    resolve them; ``__str__`` appends it on its own line. Internal errors leave it ``None`` and render unchanged.
    """

    suggestion: str | None = None

    def __str__(self) -> str:
        base = super().__str__()
        if self.suggestion:
            return f"{base}\n  Suggestion: {self.suggestion}"
        return base


class FatalError(HassetteError):
    """Custom exception to indicate a fatal error in the application.

    A service whose ``serve()`` raises one ends CRASHED instead of FAILED; whether that ends the
    process follows the service's ``required`` declaration, like any other serve failure.
    """


class ServeEndedError(HassetteError):
    """A required service's ``serve()`` returned, or its serve task was cancelled, without a shutdown request.

    Reported as that service's failure, so a required service can't stop silently.
    """


class BaseUrlRequiredError(FatalError):
    """Custom exception to indicate that the base_url configuration is required."""

    suggestion = "Set `base_url` in your configuration file to a full URL, e.g. 'http://homeassistant.local:8123'."


class IPV6NotSupportedError(FatalError):
    """Custom exception to indicate that IPv6 addresses are not supported in base_url."""

    suggestion = "Use the IPv4 address or hostname of your Home Assistant instance instead."


class SchemeRequiredInBaseUrlError(FatalError):
    """Custom exception to indicate that the base_url must include a scheme (http:// or https://)."""

    suggestion = "Prefix `base_url` with 'http://' or 'https://'."


class ConnectionClosedError(HassetteError):
    """Custom exception to indicate that the WebSocket connection was closed unexpectedly."""


class TelemetryUnavailableError(HassetteError):
    """The telemetry store could not satisfy a read (down, slow, or closed)."""


class SchemaVersionError(HassetteError):
    """Raised when the on-disk database schema version is ahead of the code's expected head.

    This indicates the database was created by a newer binary, so the service must not auto-delete
    it; manual intervention is required. ``DatabaseService`` is a required service, so this ends the
    process like any other of its failures.
    """


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
            await api.helpers.update("vacation_mode", UpdateInputBooleanParams(initial=False))
        except FailedMessageError as exc:
            if exc.code == "not_found":
                # Helper was deleted between list and update — recreate it
                ...

    ``code`` is populated when the error originates from an HA error envelope
    (see ``FailedMessageError.from_error_response``). It is ``None`` for
    locally-synthesized failures such as transport timeouts.

    ``original_data`` is the HA error envelope for an HA-side failure. On a
    :class:`ResponseTimeoutError` it is instead the outgoing request payload,
    since no envelope arrived.
    """

    def __init__(self, msg: str, *, code: str | None = None, original_data: dict | None = None) -> None:
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
        """Build the error from an HA error response, folding the error text and payload into the message.

        Returns:
            A new instance carrying ``code`` and ``original_data``.
        """
        msg = f"WebSocket message failed with response '{error}' (data={original_data})"
        return cls(msg, code=code, original_data=original_data)


class OutcomeUnknownError(HassetteError):
    """A command was sent, but no response arrived, so it may or may not have applied.

    Catch this to handle both ways it happens: :class:`ResponseTimeoutError` (no response
    within the timeout) and :class:`ResponseLostError` (the connection dropped while waiting).

    Don't blindly re-send a write after this error: if it already applied, a re-send applies it
    twice. Check state instead. After a helper ``create``/``update``/``delete``, call
    ``api.helpers.list(domain)`` to see whether it landed (the "Managing helpers" docs page shows
    the pattern). After ``fire_event`` or ``call_service``, check the side effect yourself, for
    example by reading the target entity's state.
    """


class ResponseTimeoutError(OutcomeUnknownError, FailedMessageError):
    """No response arrived within the response timeout, so the command may or may not have applied.

    ``code`` is ``None`` (locally synthesized). ``original_data`` is the outgoing request payload,
    not an HA response envelope. The message names only the command ``type``, message id, and
    timeout, never payload values.
    """


class ResponseLostError(OutcomeUnknownError, RetryableConnectionClosedError):
    """The connection dropped while waiting for a response, so the command may or may not have applied.

    Still a :class:`RetryableConnectionClosedError` (``close_code`` included), but "retryable"
    refers to the connection, not the command — see :class:`OutcomeUnknownError` before
    re-sending a write.
    """


class InvalidAuthError(HassetteError):
    """Home Assistant rejected the access token.

    Not fatal: an expired or not-yet-valid token can recover, so on the WebSocket ``WebsocketService``
    retries ``AUTH_RETRIES`` times (``hassette.core.websocket_reconnect``) and then stays up without
    reconnecting until the process restarts.
    """

    suggestion = "Verify your long-lived access token in Home Assistant under Profile -> Security."


class AuthTokenWriteError(HassetteError):
    """Raised when a freshly generated web API auth token could not be persisted to disk.

    Deliberately a plain :class:`HassetteError`, not :class:`FatalError` — an auth failure
    must not crash ``WebApiService``. Startup fails loudly here rather than silently falling back
    to an ephemeral in-memory token: every process restart would otherwise mint a fresh token and
    invalidate whatever credential the operator was just given.

    Attributes:
        path: The token file path that could not be written.
        original_error: The underlying ``OSError`` that caused the failure.
    """

    def __init__(self, path: Path, original_error: OSError) -> None:
        self.path = path
        self.original_error = original_error
        super().__init__(f"Could not write web API auth token to {path}: {original_error}")


class TrustedProxyConfigError(HassetteError):
    """Raised when a ``trusted_proxies`` entry is invalid config.

    Covers two failure modes, both fail-loud at startup rather than silently skipping the bad
    entry: an entry that is neither a valid IP/CIDR literal nor a name any DNS lookup could resolve
    (empty, a mistyped literal like ``10.0.0.300`` or one containing ``/`` or ``:``, an empty or
    over-long label), and a literal that
    matches the entire IPv4/IPv6 address space (``0.0.0.0/0``, ``::/0`` — an auth *bypass*, not an
    additive check). A hostname that doesn't resolve right now is not a config error
    and never raises this; it trusts no peer until the periodic refresh resolves it. Deliberately a
    plain :class:`HassetteError`, not :class:`FatalError` — the caller
    (``WebApiService.on_initialize()``) decides how to surface it at startup.
    """


class InvalidInheritanceError(TypeError, HassetteError):
    """Raised when a class inherits from App incorrectly."""


class UndefinedUserConfigError(TypeError, HassetteError):
    """Raised when a class does not define a user_config_class."""


class EntityNotFoundError(ValueError, HassetteError):
    """Custom error for handling 404 in the Api."""


class HttpRequestError(HassetteError):
    """Raised when a Home Assistant REST request fails with a non-404 HTTP status.

    A 404 raises :class:`EntityNotFoundError` instead. The original
    ``aiohttp.ClientResponseError`` is chained as ``__cause__``.

    Attributes:
        status: The HTTP status code Home Assistant returned.
        message: The HTTP reason phrase from the response.
        method: The HTTP method of the failed request.
        url: The request URL, relative to the REST API base.
    """

    def __init__(self, status: int, message: str, *, method: str, url: str) -> None:
        self.status = status
        self.message = message
        self.method = method
        self.url = url
        super().__init__(f"{method} {url} failed with HTTP {status}: {message}")


class ResourceNotReadyError(HassetteError):
    """Custom exception to indicate that a resource is not ready for use."""


class TaskBucketSealedError(RuntimeError, HassetteError):
    """Raised when a sealed ``TaskBucket`` rejects new work.

    Subclasses ``RuntimeError`` so callers that only care that spawning failed keep working.
    The distinct type exists so a call site willing to accept *this* specific rejection can
    catch it without also swallowing unrelated ``spawn()`` failures — the reason the sync
    removal paths catch it rather than pre-checking ``TaskBucket.is_sealed``.

    A pre-check cannot be correct for a cross-thread caller: ``spawn()`` hands the work to
    the loop thread via ``call_soon_threadsafe`` and re-checks the seal there, so a caller
    on a worker thread can read ``is_sealed`` as ``False`` and still be rejected when the
    loop thread seals the bucket before the queued callback runs. Catching at the spawn
    boundary makes the admission decision atomic with the spawn itself.
    """


class WriteQueueUnavailableError(RuntimeError, HassetteError):
    """Raised by ``DatabaseService.submit()``/``enqueue()`` when the write queue is gone.

    Subclasses ``RuntimeError`` so existing callers that only care "submission failed" keep
    working. The distinct type exists so ``update_heartbeat()`` can count exactly this
    rejection as a heartbeat failure without also swallowing an unrelated ``RuntimeError``
    raised from inside the submitted coroutine (e.g. ``Hassette.session_id`` racing a session
    teardown) under the same except clause.
    """


class AppBootstrapNotReleasedError(HassetteError):
    """Raised when an app start/reload is requested before bootstrap release opens."""


class AppBlockedError(HassetteError):
    """Raised when a manual start/reload is requested for an app the exclusive-app filter has blocked.

    The filter is set by ``--app``. Without this, the caller would get a lying 202 "accepted" for a
    request the registry silently no-ops — see AppLifecycleService's blocked-app guards.
    """


class AppPrecheckFailedError(HassetteError):
    """Custom exception to indicate that one or more prechecks for an app failed."""


class ConfigError(ValueError, HassetteError):
    """The configuration is invalid as written and must be edited; ``hassette run`` exits 78 on it."""


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
            f"'{method_name}' defined in {origin_name!r}."
        )
        if location:
            msg += f" (at {location})"
        super().__init__(msg)
        if suggested_alt:
            self.suggestion = f"Use '{suggested_alt}' instead."


class DependencyError(HassetteError):
    """Base class for dependency-related errors."""


class DependencyInjectionError(DependencyError):
    """Raised when a handler or predicate signature or its annotations can't be used.

    The signature checks apply to every bus handler and scheduler ``where=`` predicate,
    whether or not it uses ``D.*`` annotations. This exception indicates a user error
    in the callable's definition, such as:
    - Using invalid parameter types (*args, positional-only)
    - Missing required type annotations
    - Incompatible annotation types

    These errors should be fixed by updating the handler signature.
    """

    suggestion = (
        "See the supported handler signatures at "
        "https://hassette.readthedocs.io/en/stable/pages/core-concepts/bus/dependency-injection/"
    )


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

    A class may optionally set :attr:`~hassette.models.states.base.BaseState.accessor_hint` to name
    a dedicated ``StateManager`` accessor that exists for exactly this case — e.g. the four narrowed
    sensor-shape classes in ``models/states/sensor_shapes.py``, which deliberately do not re-declare
    ``domain`` and so always hit this error via ``self.states[<class>]``. When set, the hint becomes
    the error's ``suggestion``; every other state class gets a suggestion to declare ``domain``.
    """

    def __init__(self, state_class: type["BaseState[Any]"], accessor_hint: str | None = None) -> None:
        msg = f"State class {state_class.__name__} does not define a domain annotation or the annotation is empty."
        super().__init__(msg)
        if accessor_hint is not None:
            self.suggestion = f"Use self.states.{accessor_hint} instead."
        else:
            self.suggestion = f"Declare the domain on {state_class.__name__}, e.g. `domain: Literal['light']`."
        self.state_class = state_class
        self.accessor_hint = accessor_hint


class DomainNotFoundError(StateRegistryError):
    """Raised when no state class is found for a given domain."""

    def __init__(self, domain: str):
        super().__init__(f"No state class found for domain '{domain}'.")
        self.domain = domain
        self.suggestion = (
            f"Check the domain for typos, or define a custom state class with `domain: Literal['{domain}']`."
        )


class DomainRequiredError(StateRegistryError):
    """Raised when ``register_state_converter`` (or ``StateRegistry.register``) gets ``domain=None``.

    A concrete domain is required to register a class in the catalog — ``None`` would
    silently store an unresolvable ``StateKey(domain=None)`` entry that ``resolve(domain=None)``
    could return before any caller validates the result. Contrast with
    :class:`NoDomainAnnotationError`, which fires during *automatic* registration when a
    class's own ``Literal`` annotation is absent; that path is expected for base classes and
    is suppressed by ``BaseState.__init_subclass__``. This error covers the *explicit*
    registration path, where a missing domain is always a caller mistake.
    """

    def __init__(self, state_class: type["BaseState[Any]"]) -> None:
        msg = (
            f"Cannot register {state_class.__name__} with domain=None. Pass an explicit domain, "
            f"e.g. register_state_converter({state_class.__name__}, domain='my_domain')."
        )
        super().__init__(msg)
        self.state_class = state_class


class HassetteNotInitializedError(RuntimeError, HassetteError):
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


class EntityShapeError(StateRegistryError):
    """Base for state-conversion errors carrying ``(entity_id, device_class, state_class)`` context.

    Shared by :class:`UnableToConvertAnnotatedStateError`, :class:`SensorShapeMismatchError`, and
    :class:`EntityNotInViewError` — same three-parameter shape, same three attribute assignments,
    differing only in the message template. Subclasses override :meth:`_build_message` and should not
    override ``__init__``, so the attribute assignments stay in one place. The sole exception is
    :class:`EntityNotInViewError`, which mixes in ``KeyError`` and must re-delegate explicitly — see
    the comment on its ``__init__`` for why.

    Matches design.md's documented exception convention ("a message plus structured attributes, not
    a bare string"; see ``UnableToConvertStateError``) — that convention constrains the shape of each
    subclass's public surface, not whether they share an implementation.
    """

    def __init__(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> None:
        super().__init__(self._build_message(entity_id, device_class, state_class))
        self.entity_id = entity_id
        self.device_class = device_class
        self.state_class = state_class

    def _build_message(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> str:
        raise NotImplementedError


class UnableToConvertAnnotatedStateError(EntityShapeError):
    """Raised when a state dict fails Pydantic validation against a DI-annotated state class.

    Wraps the underlying ``pydantic.ValidationError`` (chained via ``raise ... from exc``) with a
    message that names the entity, its actual device class, and the annotated class — legible where
    a bare Pydantic error is not.

    Distinct from :class:`UnableToConvertStateError`, which is raised by
    ``StateRegistry.conversion_with_error_handling`` for the ``try_convert_state``/``self.states``
    path. This one is raised directly by ``convert_state_dict_to_model``, which the dependency
    injection annotation converter (``hassette.conversion.annotation_converter``) calls without
    going through that wrapper — so without this error, a DI conversion failure surfaced a raw
    Pydantic ``ValidationError`` with no entity context.
    """

    def _build_message(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> str:
        return (
            f"Unable to convert state for entity_id '{entity_id}' (device_class: {device_class!r}) "
            f"to annotated class {state_class.__name__}."
        )


class SensorShapeMismatchError(EntityShapeError):
    """Raised when a DI-annotated narrowed sensor shape class does not match the entity's value shape.

    Raised even when coercion would otherwise succeed.

    Only triggered for the four narrowed sensor shape classes (``NumericSensorState``,
    ``EnumSensorState``, ``TimestampSensorState``, ``DateSensorState``) from
    ``hassette.models.states.sensor_shapes`` — annotating plain ``SensorState`` makes no shape claim
    and is never checked. An entity whose shape classifies as ``SensorShape.UNKNOWN`` contradicts no
    claim and does not raise this error.
    """

    def _build_message(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> str:
        return (
            f"Entity '{entity_id}' (device_class: {device_class!r}) does not match the value shape "
            f"declared by annotated class {state_class.__name__}."
        )


class EntityNotInViewError(KeyError, EntityShapeError):
    """Raised when direct lookup finds an entity in its domain that is not in a filtered ``DomainStates`` view.

    The entity's state either fails the view's membership predicate, or its current value does
    not convert to the view's model.

    Subclasses both ``KeyError`` and the state-error hierarchy: ``Mapping.get()`` is implemented by
    catching ``KeyError``, so ``.get()`` returns ``None`` for non-members — consistent with
    ``__contains__`` returning ``False`` and iteration silently skipping the entity — while ``[]``
    still fails loudly with a legible message. Only raised by views built with an explicit
    membership predicate (e.g. the narrowed sensor-shape accessors); a plain ``DomainStates`` with
    no predicate keeps raising the underlying conversion error directly.
    """

    def __init__(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> None:
        # Must delegate explicitly rather than inherit EntityShapeError.__init__. On Python <= 3.13
        # KeyError carries its own __init__ slot, and KeyError precedes EntityShapeError in this
        # class's MRO, so an inherited __init__ resolves to KeyError's — leaving entity_id,
        # device_class, and state_class unset, so every read of them raises AttributeError. Python
        # 3.14 drops that slot and resolves to EntityShapeError, which is why the bug only surfaced
        # on the supported lower bound. super().__init__() would hit KeyError too; name the base
        # directly. Pinned by test_entity_not_in_view_error_defines_own_init.
        EntityShapeError.__init__(self, entity_id, device_class, state_class)

    def _build_message(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> str:
        return (
            f"Entity '{entity_id}' (device_class: {device_class!r}) is not a member of this view; "
            f"it does not match the shape expected by {state_class.__name__}."
        )


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


class RestartRefusedError(FatalError):
    """Raised when a lifecycle front door refuses a new attempt because work from the last teardown may still run.

    Carries the resource identity and the exact stored ``TeardownReport`` (``is_restart_safe`` is
    always ``False`` whenever this exception is raised: a task was still pending, or the evidence is
    incomplete) so a caller can inspect why
    restart was refused without re-deriving evidence from logs. The message lists the report's
    causes and any populated bounded detail fields (failed operations, pending tasks, affected
    resources) so existing exception logging remains useful on its own. Inherits ``FatalError``
    because a restart-unsafe object can never recover safely in-process; only process replacement
    can, and that is the embedding host or supervisor's responsibility.

    Attributes:
        resource_name: The ``unique_name`` of the resource that refused to restart.
        report: The stored ``TeardownReport``.
    """

    def __init__(self, resource_name: str, report: "TeardownReport") -> None:
        self.resource_name = resource_name
        self.report = report

        causes = ", ".join(report.causes) if report.causes else "no recorded causes"
        msg = f"Restart refused for '{resource_name}': teardown was not proven restart-safe ({causes})."

        details: list[str] = []
        if report.failed_operations:
            details.append(f"failed_operations={list(report.failed_operations)}")
        if report.pending_tasks:
            details.append(f"pending_tasks={list(report.pending_tasks)}")
        if report.affected_resources:
            details.append(f"affected_resources={list(report.affected_resources)}")
        if details:
            msg += " " + "; ".join(details)

        super().__init__(msg)


class LifecycleReentryError(HassetteError):
    """Raised when a lifecycle front door is invoked from the resource's own active lifecycle code.

    The front doors are ``initialize()``, ``start()``, and ``shutdown()``; the
    guarded callers are the resource's own active initialization coordinator, shutdown
    coordinator, or shutdown body.

    A hook that calls back into its own owner's lifecycle orchestration cannot be joined,
    cancelled, or awaited safely -- the calling task *is* the coordinator or body being awaited,
    so joining or cancelling it would create a self-referential deadlock or cancellation cycle.
    Raised before creating, joining, or cancelling another lifecycle task. A hook that cannot
    continue should raise or return and let its lifecycle owner decide recovery.

    Detection is limited to a resource re-entering its own active coordinator or body task.
    Cross-resource lifecycle cycles -- a child's hook calling into its parent's lifecycle, or two
    resources awaiting each other -- are not detected here and rely on the whole-body shutdown
    timeout to eventually force-terminate.

    Attributes:
        resource_name: The ``unique_name`` of the resource whose lifecycle was re-entered.
        method_name: The name of the front-door method that detected the re-entrant call.
    """

    def __init__(self, resource_name: str, method_name: str) -> None:
        self.resource_name = resource_name
        self.method_name = method_name
        super().__init__(
            f"Lifecycle re-entry detected for '{resource_name}': '{method_name}' was called from "
            "its own active initialization coordinator, shutdown coordinator, or shutdown body. "
            "Hooks must not call back into lifecycle orchestration; raise or return instead."
        )


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


class SchedulerNameRequiredError(HassetteError):
    """Raised at call time when ``name=`` is omitted on a scheduled job.

    Attributes:
        handler_method: Fully-qualified name of the handler function.
        trigger_description: Human-readable description of the trigger the job was being scheduled with.
    """

    def __init__(self, handler_method: str, trigger_description: str) -> None:
        self.handler_method = handler_method
        self.trigger_description = trigger_description
        super().__init__(
            f"Scheduled job registration requires a name.\n\n"
            f"  handler: {handler_method}\n"
            f"  trigger: {trigger_description}\n\n"
            f"Provide a stable name via the `name=` parameter:\n\n"
            f'  await self.scheduler.run_in(self.handler, 5, name="my_job")'
        )


class JobRemovedError(HassetteError):
    """Raised when submitting or otherwise acting on a scheduler job whose registration was removed.

    Raised by ``SchedulerService.submit_job()`` when a job's ``db_id`` no longer maps to
    the same live object in the service's registry — the registration was removed (via
    ``Job.remove()``, ``Scheduler.remove_job()``/``remove_group()``, owner shutdown, or
    ``if_exists="replace"``) after the caller obtained its handle. The HTTP layer translates
    this into a 409 response for remote submission of a non-live persisted job.
    """

    def __init__(self, job_name: str, db_id: int | None = None) -> None:
        self.job_name = job_name
        self.db_id = db_id
        super().__init__(f"Job {job_name!r} (db_id={db_id!r}) is no longer registered and cannot be submitted.")


class DuplicateListenerError(HassetteError):
    """Raised at call time when a second listener with the same ``(name, topic)`` is registered.

    Applies within the same app instance in the same session.

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

    Raised only by ``validate_registries(strict=True)`` after collecting all issues.
    ``Hassette.wire_services()`` calls it without ``strict``, so a running instance
    logs registry issues as warnings and never raises this exception.

    Attributes:
        issues: The full list of validation issues found. Always contains at least
            one error-severity issue when this exception is raised.
    """

    def __init__(self, issues: list[Any]) -> None:
        self.issues = issues
        error_count = sum(1 for i in issues if i.severity == "error")
        warning_count = sum(1 for i in issues if i.severity == "warning")
        total = len(issues)
        summary_lines = [f"Registry validation failed: {error_count} error(s), {warning_count} warning(s)"]
        summary_lines.extend(
            f"  [{i.severity.upper()}] {i.registry}: {i.message}" for i in issues[:MAX_ISSUES_IN_SUMMARY]
        )
        if total > MAX_ISSUES_IN_SUMMARY:
            summary_lines.append(f"  ... and {total - MAX_ISSUES_IN_SUMMARY} more issue(s)")
        super().__init__("\n".join(summary_lines))
