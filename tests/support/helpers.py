import asyncio
import json
import socket
import textwrap
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, suppress
from logging import Logger, getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import tomli_w

from hassette.bus.listeners import (
    DurationConfig,
    HandlerInvoker,
    Listener,
    ListenerIdentity,
    ListenerOptions,
)
from hassette.config.classes import AppManifest
from hassette.core.core import Hassette
from hassette.events import RawStateChangeEvent
from hassette.events.base import HassettePayload
from hassette.events.hassette import HassetteFileWatcherEvent, HassetteServiceEvent, ServiceStatusPayload
from hassette.exceptions import RestartRefusedError
from hassette.resources.teardown import TeardownCause, TeardownReport
from hassette.testing import create_state_change_event
from hassette.testing._simulation import create_component_loaded_event as create_component_loaded_event
from hassette.testing._simulation import create_service_registered_event as create_service_registered_event
from hassette.types.enums import BackpressurePolicy, ExecutionMode, ResourceRole, ResourceStatus, Topic
from hassette.utils.func_utils import callable_name, callable_short_name

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from hassette.bus.bus import Bus
    from hassette.events import HassStateDict
    from hassette.resources.service import Service
    from hassette.types.types import BusErrorHandlerType, HandlerType, Predicate, SourceTier

PLACEHOLDER_SERVICE_NAME = "TestService"
"""Stand-in resource_name for the service-lifecycle event factories below. Tests that don't
assert on the name should take this default rather than inventing another placeholder."""

SETTLE_SECONDS = 0.05
"""Default settle window: seconds to let a stray extra handler call land before a negative assertion."""

SHORT_SHUTDOWN_TIMEOUT_SECONDS = 0.1
"""Short ``resource_shutdown_timeout_seconds`` for tests that force a timeout/force-terminal branch."""


class FakeStateReader:
    """Minimal dict-backed implementation of the StateReader protocol.

    Holds states keyed by entity_id and answers the two members StateReader
    declares: get_state, yield_domain_states.
    """

    def __init__(self, states: "dict[str, HassStateDict]") -> None:
        self.states = states

    def get_state(self, entity_id: str) -> "HassStateDict | None":
        return self.states.get(entity_id)

    def yield_domain_states(self, domain: str) -> "Generator[tuple[str, HassStateDict], Any, None]":
        for eid, state in self.states.items():
            if eid.startswith(f"{domain}."):
                yield eid, state


def noop() -> None:
    """Sync no-op — default handler for create_listener() and scheduler job tests."""


async def async_noop() -> None:
    """Async no-op — call it to get a coroutine object (e.g. bucket.spawn(async_noop()))."""


async def block_until_cancelled(_self: Any) -> None:
    """Service.serve() body: blocks until the task is cancelled.

    Assign as ``serve = block_until_cancelled`` on a test Service subclass — the function
    is bound as an instance method via the normal descriptor protocol.
    """
    await asyncio.Event().wait()


async def settle(seconds: float = SETTLE_SECONDS) -> None:
    """Give a stray extra handler call time to land before a negative assertion."""
    # negative-assertion: no event-driven alternative
    await asyncio.sleep(seconds)


def create_attr_change_event(
    old_attr_value: Any,
    new_attr_value: Any,
    *,
    attr_name: str = "brightness",
    entity_id: str = "light.office",
    old_value: str = "on",
    new_value: str = "on",
) -> RawStateChangeEvent:
    """Create a state-change event where a single attribute changes and the state itself doesn't.

    Collapses the dominant shape used across attribute-predicate tests (AttrFrom/AttrTo/
    AttrDidChange/AttrComparison/DidChange-with-attr-source): the entity's state stays "on",
    and only one attribute (brightness by default) moves from ``old_attr_value`` to
    ``new_attr_value``. Override ``entity_id``/``old_value``/``new_value`` for the handful of
    cases that vary the base state as well.
    """
    return create_state_change_event(
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        old_attrs={attr_name: old_attr_value},
        new_attrs={attr_name: new_attr_value},
    )


def create_app_manifest(
    suffix: str,
    app_dir: Path,
    enabled: bool = True,
    app_config: dict | None = None,
) -> AppManifest:
    """Helper to create an AppManifest instance."""
    app_config = app_config or {}

    key = f"my_app_{suffix}"
    filename = f"my_app_{suffix}.py"
    class_name = f"MyApp{suffix.capitalize()}"
    full_path = app_dir / filename

    return AppManifest(
        app_key=key,
        filename=filename,
        class_name=class_name,
        enabled=enabled,
        app_config=app_config,
        app_dir=app_dir,
        full_path=full_path,
    )


def get_app_manifest_for_toml(app: AppManifest) -> dict[str, Any]:
    """Convert AppManifest to TOML string."""
    data = app.model_dump(exclude_unset=True)
    config_key = "app_config" if "app_config" in data else "config"

    config = data.pop(config_key, {})

    return {**data, "config": config}


def write_app_toml(
    toml_file: Path,
    *,
    app_dir: Path,
    dev_mode: bool = True,
    apps: list[AppManifest] | None = None,
) -> None:
    """Write a hassette.toml with specified apps."""
    apps = apps or []

    apps_section: dict[str, Any] = {
        "directory": app_dir.as_posix(),
        "autodetect": False,
    }

    if apps:
        for app in apps:
            apps_section[app.app_key] = get_app_manifest_for_toml(app)

    hassette_dict: dict[str, Any] = {
        "dev_mode": dev_mode,
        "apps": apps_section,
    }

    toml_dict = {"hassette": hassette_dict}

    # Convert any non-serializable types to strings for TOML compatibility
    toml_dict = json.loads(json.dumps(toml_dict, indent=2, default=str))

    with toml_file.open("wb") as f:
        tomli_w.dump(toml_dict, f)


def write_app(app_dir: Path, filename: str, source: str) -> Path:
    """Write `source` as a module inside `app_dir`, creating the directory if needed.

    For app files whose exact source matters (auto-detect discovery, import behavior). Use
    `write_test_app_with_decorator` instead when a canned App subclass is enough.
    """
    app_dir.mkdir(parents=True, exist_ok=True)
    path = app_dir / filename
    path.write_text(textwrap.dedent(source))
    return path


def write_test_app_with_decorator(
    app_file: Path,
    class_name: str,
    config_fields: dict | None = None,
) -> None:
    """Write a test app Python file."""
    getLogger(__name__).debug("Writing test app to %s", app_file)
    config_fields_str = ""

    if config_fields:
        for field_name, field_type in config_fields.items():
            config_fields_str += f"\n    {field_name}: {field_type} = None"

    content = f'''
from hassette import App, AppConfig

class {class_name}Config(AppConfig):
    """Config for {class_name}."""{config_fields_str}

class {class_name}(App[{class_name}Config]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("{class_name} initialized")
'''

    app_file.write_text(textwrap.dedent(content).lstrip())


async def emit_file_change_event(hassette: "Hassette", changed_paths: set[Path]) -> None:
    """Emit a synthetic file-watcher event for the given paths."""
    event = HassetteFileWatcherEvent.from_paths(changed_file_paths=changed_paths)
    await hassette.send_event(event)


def make_service_failed_event(
    service: "Service",
    exception: Exception | None = None,
) -> HassetteServiceEvent:
    """Create a HassetteServiceEvent with FAILED status for testing."""
    return HassetteServiceEvent.from_service_status(
        resource_name=service.class_name,
        role=service.role,
        status=ResourceStatus.FAILED,
        exception=exception or Exception("test"),
    )


def make_service_running_event(service: "Service") -> HassetteServiceEvent:
    """Create a HassetteServiceEvent with RUNNING status for testing."""
    return HassetteServiceEvent.from_service_status(
        resource_name=service.class_name,
        role=service.role,
        status=ResourceStatus.RUNNING,
    )


def make_crashed_event(
    resource_name: str = PLACEHOLDER_SERVICE_NAME,
    exception_type: str | None = "RuntimeError",
    exception: str | None = "something broke",
    exception_traceback: str | None = "Traceback ...",
) -> HassetteServiceEvent:
    """Build a CRASHED HassetteServiceEvent for testing."""
    return HassetteServiceEvent(
        topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
        payload=HassettePayload(
            data=ServiceStatusPayload(
                resource_name=resource_name,
                role=ResourceRole.SERVICE,
                status=ResourceStatus.CRASHED,
                previous_status=ResourceStatus.FAILED,
                exception=exception,
                exception_type=exception_type,
                exception_traceback=exception_traceback,
                ready=False,
                ready_phase=None,
            ),
        ),
    )


def make_unsafe_restart_refused_error(resource_name: str = PLACEHOLDER_SERVICE_NAME) -> RestartRefusedError:
    """Build a RestartRefusedError carrying a real UNSAFE TeardownReport, for refusal tests."""
    report = TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_FAILED,), failed_operations=("shutdown_hooks",))
    return RestartRefusedError(resource_name, report)


async def wire_up_app_state_listener(
    bus: "Bus",
    event: asyncio.Event,
    app_key: str,
    status: ResourceStatus,
) -> None:
    """Wire up a listener that fires when a specific app reaches the given status."""

    async def handler() -> None:
        bus.task_bucket.post_to_loop(event.set)

    await bus.on_app_state_changed(
        handler=handler,
        app_key=app_key,
        status=status,
        once=True,
        name=f"tests.support.wire_up_{app_key}_{status}",
        # Once-listeners participate in collision tracking, so re-wiring the same
        # (app_key, status) — e.g. across a hot-reload — would raise without replace.
        if_exists="replace",
    )


async def wire_up_app_running_listener(bus: "Bus", event: asyncio.Event, app_key: str) -> None:
    """Wire up a listener that fires when a specific app reaches RUNNING status."""
    await wire_up_app_state_listener(bus, event, app_key, ResourceStatus.RUNNING)


def make_task_bucket() -> MagicMock:
    """Create a MagicMock TaskBucket suitable for Listener construction in tests.

    ``spawn`` creates a real ``asyncio.Task`` when a loop is running so the execution-mode
    guard (which spawns and awaits the cancellable child handler task) behaves like production.
    Outside a running loop it returns a MagicMock so sync-context construction still works.

    ``pending_task_names()`` defaults to an empty tuple (not an unconfigured, truthy
    ``MagicMock``) so callers that check it for shutdown evidence (e.g. the Resource shutdown
    stages in ``hassette.resources.base``) see "nothing pending" by default, matching a real,
    freshly constructed ``TaskBucket``. ``cancel_all()`` defaults to an ``AsyncMock`` returning
    the same empty tuple, mirroring the real ``TaskBucket.cancel_all()`` return shape.
    """
    tb = MagicMock()
    tb.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    tb.pending_task_names = MagicMock(return_value=())
    tb.cancel_all = AsyncMock(return_value=())

    def spawn_side_effect(coro: Any, *, name: str | None = None) -> Any:  # noqa: ARG001
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No loop (sync-context test): close the coroutine so it isn't reported as
            # "never awaited", then hand back a MagicMock standing in for the Task.
            if asyncio.iscoroutine(coro):
                coro.close()
            return MagicMock()
        return asyncio.create_task(coro)

    tb.spawn = MagicMock(side_effect=spawn_side_effect)
    return tb


class ControlledClock:
    """Mutable clock for deterministic `RateLimiter` throttle tests.

    Defaults to starting at 1.0, but a zero-origin clock (`start=0.0`) works too —
    `RateLimiter` tracks "no prior call" with `_throttle_last_time = None`, not `0.0`, so
    a monotonic clock that legitimately returns `0.0` on its first call still fires.
    Callable directly as a `RateLimiter(clock=...)` argument.
    """

    def __init__(self, start: float = 1.0) -> None:
        self.time = start

    def __call__(self) -> float:
        return self.time

    def advance_to(self, value: float) -> None:
        self.time = value


def make_controlled_clock(start: float = 1.0) -> ControlledClock:
    """Create a `ControlledClock` starting at `start` for injecting into `RateLimiter(clock=...)`."""
    return ControlledClock(start)


def make_addrinfo(ip: str) -> tuple[Any, ...]:
    """Build one ``socket.getaddrinfo``-shaped result tuple for ``ip``.

    Shared by ``trusted_proxies`` hostname-resolution tests (``tests/unit/web/test_auth.py``,
    ``tests/integration/web_api/test_auth.py``, ``tests/unit/core/test_web_api_service.py``) that
    patch the event loop's resolver (see :func:`patch_loop_getaddrinfo`) and need a fixed-shape
    stdlib stand-in for its return value — ``loop.getaddrinfo`` returns the identical tuple shape
    as ``socket.getaddrinfo``.
    """
    if ":" in ip:
        return (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))


def patch_loop_getaddrinfo(
    *, return_value: list[tuple[Any, ...]] | None = None, side_effect: BaseException | None = None
) -> AbstractContextManager[AsyncMock]:
    """Patch the running event loop's DNS resolver for ``trusted_proxies`` hostname-resolution tests.

    ``hassette.web.auth.trusted_proxies._resolve_hostname`` resolves hostnames via
    ``asyncio.get_running_loop().getaddrinfo(...)`` (bounded by an explicit timeout) rather than
    calling the blocking ``socket.getaddrinfo`` directly, so tests must patch
    ``asyncio.BaseEventLoop.getaddrinfo`` — the coroutine method looked up on whatever concrete
    loop class is running — with an async replacement, not the synchronous stdlib call. Shared by
    ``tests/unit/web/test_auth_trusted_proxies.py``, ``tests/integration/web_api/test_auth.py``,
    and ``tests/unit/core/test_web_api_service.py``.

    Pass exactly one of ``return_value`` (a list of :func:`make_addrinfo`-shaped tuples, the
    success case) or ``side_effect`` (an exception instance to raise, e.g.
    ``socket.gaierror("no such host")``, the failure case).
    """
    if side_effect is not None:
        return patch("asyncio.BaseEventLoop.getaddrinfo", new_callable=AsyncMock, side_effect=side_effect)
    return patch("asyncio.BaseEventLoop.getaddrinfo", new_callable=AsyncMock, return_value=return_value)


def create_listener(
    handler: "HandlerType" = noop,
    *,
    topic: str = "state_changed.light.test",
    owner_id: str = "test_owner",
    task_bucket: Any = None,
    where: "Predicate | Sequence[Predicate] | None" = None,
    kwargs: Mapping[str, Any] | None = None,
    once: bool = False,
    debounce: float | None = None,
    throttle: float | None = None,
    timeout: float | None = None,
    timeout_disabled: bool = False,
    priority: int = 0,
    mode: "ExecutionMode | str" = ExecutionMode.PARALLEL,
    backpressure: "BackpressurePolicy | str" = BackpressurePolicy.BLOCK,
    app_key: str = "",
    instance_index: int = 0,
    name: str | None = None,
    source_tier: "SourceTier" = "app",
    immediate: bool = False,
    duration: float | None = None,
    entity_id: str | None = None,
    is_attribute_listener: bool = False,
    hold_predicate: "Predicate | None" = None,
    error_handler: "BusErrorHandlerType | None" = None,
    app_error_handler_resolver: "Callable[[], BusErrorHandlerType | None] | None" = None,
    source_location: str = "",
    registration_source: str = "",
    logger: Logger | None = None,
    clock: "Callable[[], float] | None" = None,
) -> Listener:
    """Test factory: build a Listener from simple kwargs.

    Constructs sub-structs internally and delegates to Listener.create().
    Default handler is a sync no-op (`noop`); default task_bucket is a MagicMock.

    Args:
        clock: Zero-arg callable returning the current monotonic time, forwarded to the
            RateLimiter built for debounce/throttle. Defaults to ``time.monotonic`` when
            None. Use to inject a controlled clock for deterministic throttle tests.
    """
    # duration + debounce/throttle incompatibility is validated by Listener.create() below.
    if duration is not None and not entity_id:
        raise ValueError("'duration' requires an entity_id — use on_state_change() or on_attribute_change()")
    if immediate and not entity_id:
        raise ValueError("'immediate' requires an entity_id — use on_state_change() or on_attribute_change()")

    if task_bucket is None:
        task_bucket = make_task_bucket()

    handler_name = callable_name(handler)
    short_name = callable_short_name(handler)

    identity = ListenerIdentity(
        owner_id=owner_id,
        app_key=app_key,
        instance_index=instance_index,
        name=name,
        source_tier=source_tier,
        handler_name=handler_name,
        handler_short_name=short_name,
        source_location=source_location,
        registration_source=registration_source,
    )

    options = ListenerOptions(
        once=once,
        debounce=debounce,
        throttle=throttle,
        timeout=timeout,
        timeout_disabled=timeout_disabled,
        priority=priority,
        mode=ExecutionMode(mode),
        backpressure=BackpressurePolicy(backpressure),
    )

    invoker = HandlerInvoker.create(
        task_bucket=task_bucket,
        handler=handler,
        kwargs=kwargs,
        options=options,
        error_handler=error_handler,
        app_error_handler_resolver=app_error_handler_resolver,
        clock=clock,
    )

    duration_config: DurationConfig | None = None
    if entity_id:
        # DurationConfig carries entity_id even when duration/immediate are None —
        # BusService uses entity_id for cancel-listener topic construction and state reads.
        duration_config = DurationConfig(
            entity_id=entity_id,
            duration=duration,
            immediate=immediate,
            is_attribute_listener=is_attribute_listener,
            hold_predicate=hold_predicate,
        )

    return Listener.create(
        topic=topic,
        identity=identity,
        options=options,
        invoker=invoker,
        where=where,
        duration_config=duration_config,
        logger=logger or getLogger("test"),
    )


async def cleanup_hassette_streams(instance: Hassette) -> None:
    """Close event streams and the bus service's cloned receive stream.

    Both underlying close operations are idempotent, so no pre-check is needed —
    suppress(Exception) alone handles the not-yet-wired and already-closed cases.
    """
    with suppress(Exception):
        await instance.event_stream_service.close_streams()
    with suppress(Exception):
        await instance.bus_service.stream.aclose()
