from pathlib import Path
from typing import TYPE_CHECKING, Any

from yarl import URL

if TYPE_CHECKING:
    from hassette.models.states import BaseState
    from hassette.resources.teardown import TeardownReport

MAX_ISSUES_IN_SUMMARY = 5

WS_NOT_CONNECTED_MESSAGE = "WebSocket connection is not established"
"""Shared message for the various ways a caller can observe an unestablished WebSocket connection."""


class HassetteForgottenAwaitWarning(RuntimeWarning):
    """Warning emitted when a protected registration/scheduling method is called without ``await``.

    Fired from ``RegistrationHandle.__del__`` when the handle is garbage-collected without
    ever being awaited, sent to, thrown into, or closed. The message names the owning app
    and the source location of the forgotten call site.

    Integrates with ``-W error``/``pytest.warns``/``filterwarnings`` like any ``RuntimeWarning``.
    """


class HassetteBlockingIOWarning(RuntimeWarning):
    """Warning emitted when blocking I/O is detected on the shared event loop.

    Fired by Tier 1 (responsiveness watchdog) when loop lag exceeds the configured threshold,
    and by Tier 2 (call-site interception) when a blocking primitive is called on the loop thread.
    The message names the offending app, handler/job, and (where available) the source line.

    Integrates with ``-W error``/``pytest.warns``/``filterwarnings`` like any ``RuntimeWarning``.
    """


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


class ServerUrlError(FatalError):
    """Base class for every way a caller-supplied CLI ``--server-url``/``cli.server_url`` target
    fails to resolve to a connectable server, before the CLI opens any network connection to it.

    Kept as one base rather than folding every failure mode into a single exception, so a caller
    that only cares "did the server-url resolve" can catch one type, while a caller that wants to
    render a distinct message per failure mode can catch the specific subclass.
    """


class ServerUrlSchemeRequiredError(ServerUrlError):
    """Custom exception to indicate that a CLI ``server_url`` must include a scheme (http:// or https://).

    Distinct from :class:`SchemeRequiredInBaseUrlError`, which covers ``HassetteConfig.base_url``
    (the Home Assistant connection target) — this covers ``cli.server_url``/``--server-url``
    (the target the CLI itself connects to), a different config field with a different audience.
    """


class ServerUrlApiSuffixError(ServerUrlError):
    """Custom exception to indicate that a CLI ``server_url`` path ends in ``/api``.

    Every command path already starts with ``/api/...``, so a ``server_url`` ending in ``/api``
    would double up (``/api/api/health``). The message names the corrected form so a user who
    copied a URL like ``https://hassette.example.com/hassette/api`` straight out of an issue or
    doc knows exactly what to drop.
    """


class ServerUrlParseError(ServerUrlError):
    """Custom exception to indicate that a CLI ``server_url`` could not be parsed at all.

    Raised when constructing a ``yarl.URL`` from the cleaned ``server_url`` string raises
    ``ValueError`` (e.g. a non-numeric port like ``host:notnum``, or malformed IPv6 brackets like
    ``[bad]``). Wraps the ``yarl`` parse failure with the CLI's structured usage-error path
    (``error_usage()``) instead of letting it propagate as a bare, unhandled traceback.
    """


class ServerUrlHostRequiredError(ServerUrlError):
    """Custom exception to indicate that a CLI ``server_url`` has a valid scheme but no usable host.

    Covers URLs like ``https:///foo``, which parse successfully and have an accepted http/https
    scheme but resolve to an empty/``None`` host — a URL that would otherwise silently build an
    unusable base URL rather than failing with a clear, attributable message.
    """


class CredentialResolutionError(FatalError):
    """Custom exception to indicate that a CLI bearer credential could not be resolved.

    Raised by :func:`hassette.cli.target.resolve_cli_auth_token`'s helpers for both of its
    user-attributable failure modes: an unreadable ``--token-file`` and a credential value that
    is not safe for use as an HTTP header (non-ASCII or containing control characters). Kept as
    its own typed exception — rather than a bare ``ValueError`` — so a caller can catch this
    specific failure and route it through ``error_usage()`` without also swallowing unrelated
    ``ValueError``s raised deeper in the call chain (e.g. from Pydantic validation), matching the
    same convention :class:`ServerUrlSchemeRequiredError`/:class:`ServerUrlApiSuffixError`
    already establish for the URL-resolution side of the same module.
    """


class ConnectionClosedError(HassetteError):
    """Custom exception to indicate that the WebSocket connection was closed unexpectedly."""


class TelemetryUnavailableError(HassetteError):
    """The telemetry store could not satisfy a read (down, slow, or closed)."""


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
            await api.helpers.update(
                "vacation_mode",
                UpdateInputBooleanParams(initial=False),
            )
        except FailedMessageError as exc:
            if exc.code == "not_found":
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


class AuthTokenWriteError(HassetteError):
    """Raised when a freshly generated web API auth token could not be persisted to disk.

    Deliberately a plain :class:`HassetteError`, not :class:`FatalError` — an auth failure
    must not crash or block-restart ``WebApiService``. Startup fails loudly here rather than
    silently falling back to an ephemeral in-memory token: every ``WebApiService`` restart
    (it is ``RestartType.TRANSIENT``) would otherwise mint a fresh token and invalidate
    whatever credential the operator was just given.

    Attributes:
        path: The token file path that could not be written.
        original_error: The underlying ``OSError`` that caused the failure.
    """

    def __init__(self, path: Path, original_error: OSError) -> None:
        self.path = path
        self.original_error = original_error
        super().__init__(f"Could not write web API auth token to {path}: {original_error}")


class TrustedProxyConfigError(HassetteError):
    """Raised when a ``trusted_proxies`` entry cannot be parsed or resolved.

    Covers three failure modes, all fail-loud at config-load/first-resolution time rather than
    silently skipping the bad entry: an entry that is neither a valid IP/CIDR literal nor a
    resolvable hostname, a literal that matches the entire IPv4/IPv6 address space (``0.0.0.0/0``,
    ``::/0`` — an auth *bypass*, not an additive check), and a hostname that resolves to zero
    addresses. Deliberately a plain :class:`HassetteError`, not :class:`FatalError` — a bad
    ``trusted_proxies`` entry should not crash or block-restart ``WebApiService``; the caller
    (``WebApiService.on_initialize()``) decides how to surface it at startup.
    """


class InvalidInheritanceError(TypeError, HassetteError):
    """Raised when a class inherits from App incorrectly."""


class UndefinedUserConfigError(TypeError, HassetteError):
    """Raised when a class does not define a user_config_class."""


class EntityNotFoundError(ValueError, HassetteError):
    """Custom error for handling 404 in the Api."""


class ResourceNotReadyError(HassetteError):
    """Custom exception to indicate that a resource is not ready for use."""


class AppBootstrapNotReleasedError(HassetteError):
    """Raised when an app start/reload is requested before bootstrap release opens."""


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

    A class may optionally set :attr:`~hassette.models.states.base.BaseState.accessor_hint` to name
    a dedicated ``StateManager`` accessor that exists for exactly this case — e.g. the four narrowed
    sensor-shape classes in ``models/states/sensor_shapes.py``, which deliberately do not re-declare
    ``domain`` and so always hit this error via ``self.states[<class>]``. When set, the hint is
    appended to the message; every other state class has no hint and keeps the plain message.
    """

    def __init__(self, state_class: type["BaseState[Any]"], accessor_hint: str | None = None) -> None:
        msg = f"State class {state_class.__name__} does not define a domain annotation or the annotation is empty."
        if accessor_hint is not None:
            msg += f" Use self.states.{accessor_hint} instead."
        super().__init__(msg)
        self.state_class = state_class
        self.accessor_hint = accessor_hint


class DomainNotFoundError(StateRegistryError):
    """Raised when no state class is found for a given domain."""

    def __init__(self, domain: str):
        super().__init__(f"No state class found for domain '{domain}'.")
        self.domain = domain


class DomainRequiredError(StateRegistryError):
    """Raised when ``register_state_converter`` (or ``StateRegistry.register``) is called
    with ``domain=None``.

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
    """Raised when a state dict fails Pydantic validation against a dependency-injection-annotated
    state class.

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
    """Raised when a dependency-injection-annotated narrowed sensor shape class does not match the
    entity's actual value shape, even when coercion would otherwise succeed.

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
    """Raised when direct lookup finds an entity that exists in its domain but is not a member of
    a filtered ``DomainStates`` view — its state either fails the view's membership predicate, or
    its current value does not convert to the view's model.

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


class RestartRefusedError(FatalError):
    """Raised when a lifecycle front door refuses to start a new attempt after teardown proved
    restart-unsafe.

    Carries the resource identity and the exact stored ``TeardownReport`` (``is_restart_safe`` is
    always ``False`` whenever this exception is raised) so ``ServiceWatcher`` and any other caller can inspect why
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
    """Raised when a lifecycle front door (``initialize()``, ``start()``, ``restart()``, or
    ``shutdown()``) is invoked from the resource's own active initialization coordinator,
    shutdown coordinator, or shutdown body.

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
    """Raised when submitting or otherwise acting on a scheduler job whose registration
    has been removed.

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
