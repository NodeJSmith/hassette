"""Shared fixtures for tests/unit/."""

import asyncio
import collections.abc
import gc
import inspect
import logging
import logging.handlers
import queue
import sys
import threading
import time
import warnings
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import StringIO
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
import structlog.processors
import structlog.stdlib

from hassette import context
from hassette.api.api import Api
from hassette.config import HassetteConfig
from hassette.core.sync_executor import SyncExecutor
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.logging_ import (
    CorrelationFilter,
    HassetteQueueListener,
    LogCaptureHandler,
    LogPersistenceHandler,
    _extract_record_fields,  # pyright: ignore[reportPrivateUsage]
    add_execution_id,
)
from hassette.models.entities.light import LightEntity
from hassette.models.states import LightState
from hassette.task_bucket.interruptible_executor import InterruptibleThreadPoolExecutor
from hassette.test_utils.factories import make_mock_parent

if TYPE_CHECKING:
    from contextvars import Token

    from hassette import Hassette

TEST_TOKEN = "test-token"

#: Shared timezone for tests that build fixed ZonedDateTime instances — America/Chicago
#: covers DST transitions in a way UTC doesn't, so most scheduler/trigger tests use it.
TZ = "America/Chicago"

#: Upper bound on how long a submitted worker may take to signal that it is running.
WORKER_READY_TIMEOUT = 2.0


def make_sync_executor_config(
    max_workers: int = 4,
    shutdown_timeout: float = 5.0,
    saturation_warn_threshold: float = 0.75,
    saturation_warn_rate_limit_seconds: float = 30.0,
) -> HassetteConfig:
    return HassetteConfig(
        token=TEST_TOKEN,
        lifecycle={
            "sync_executor_max_workers": max_workers,
            "sync_executor_shutdown_timeout_seconds": shutdown_timeout,
            "sync_executor_saturation_warn_threshold": saturation_warn_threshold,
            "sync_executor_saturation_warn_rate_limit_seconds": saturation_warn_rate_limit_seconds,
        },
    )


def make_sync_executor_hassette(
    max_workers: int = 4,
    shutdown_timeout: float = 5.0,
    saturation_warn_threshold: float = 0.75,
    saturation_warn_rate_limit_seconds: float = 30.0,
) -> MagicMock:
    config = make_sync_executor_config(
        max_workers=max_workers,
        shutdown_timeout=shutdown_timeout,
        saturation_warn_threshold=saturation_warn_threshold,
        saturation_warn_rate_limit_seconds=saturation_warn_rate_limit_seconds,
    )
    mock_hassette = MagicMock()
    mock_hassette.config = config
    mock_hassette.task_bucket = MagicMock()
    mock_hassette.shutdown_event = asyncio.Event()
    mock_hassette.children = []
    mock_hassette._should_skip_dependency_check = MagicMock(return_value=True)
    # SyncExecutorService.__init__ reads hassette.sync_executor — the pre-built capability
    # that in production is constructed in Hassette.__init__() before the lifecycle starts.
    # Tests call rebuild_pool() explicitly since the constructor no longer creates one.
    sync_executor = SyncExecutor()
    sync_executor.rebuild_pool(
        max_workers=max_workers,
        saturation_warn_threshold=saturation_warn_threshold,
        saturation_warn_rate_limit_seconds=saturation_warn_rate_limit_seconds,
    )
    mock_hassette.sync_executor = sync_executor
    return mock_hassette


def make_service(
    max_workers: int = 4,
    shutdown_timeout: float = 5.0,
    saturation_warn_threshold: float = 0.75,
    saturation_warn_rate_limit_seconds: float = 30.0,
) -> SyncExecutorService:
    mock_hassette = make_sync_executor_hassette(
        max_workers=max_workers,
        shutdown_timeout=shutdown_timeout,
        saturation_warn_threshold=saturation_warn_threshold,
        saturation_warn_rate_limit_seconds=saturation_warn_rate_limit_seconds,
    )
    return SyncExecutorService(mock_hassette)


def make_api() -> Api:
    """Create an Api instance with mocked WebSocket and REST layers.

    Shared factory used by test_api_coroutine_conversion and
    test_entity_coroutine_conversion. Stubs out:
    - ws_send_and_wait → returns {} (enough for call_service/fire_event)
    - ws_send_json     → returns None
    - post_rest_request → returns a mock response (for set_state)
    - entity_exists    → returns False (simplifies set_state test)
    """
    hassette_mock = MagicMock()
    hassette_mock.config.logging.api = "INFO"
    hassette_mock.config.forgotten_await_behavior = None

    api = Api.__new__(Api)
    api.hassette = hassette_mock
    api._unique_name = "test_api"
    api._error_handler = None
    api.logger = logging.getLogger("hassette.test")

    api.parent = make_mock_parent()

    api.ws_send_and_wait = AsyncMock(return_value={})
    api.ws_send_json = AsyncMock(return_value=None)

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={"state": "on", "entity_id": "light.test"})
    api.post_rest_request = AsyncMock(return_value=mock_resp)
    api.entity_exists = AsyncMock(return_value=False)

    return api


def make_light_entity(api: Api) -> "tuple[LightEntity, Token[Hassette]]":
    """Create a LightEntity wired to the given api via HASSETTE_INSTANCE context.

    Shared factory: used by test_entity_coroutine_conversion and
    test_sync_entity_facade. The caller resets the returned token in a finally block.
    """
    hassette_mock = MagicMock()
    hassette_mock.api = api
    token = context.HASSETTE_INSTANCE.set(hassette_mock)

    state = LightState.model_validate({"entity_id": "light.kitchen", "state": "off", "attributes": {}, "context": {}})
    entity = LightEntity(state=state)
    return entity, token


def public_async_methods(cls: type) -> set[str]:
    """Return public async/Coroutine-returning method names defined directly on cls (not inherited).

    Uses ``vars(cls)`` (not ``inspect.getmembers``) so that ``Resource`` lifecycle methods
    inherited by both ``Api`` and ``RecordingApi`` do NOT appear in the comparison.

    Uses OR semantics: matches both classic ``async def`` methods and plain ``def`` methods
    whose ``-> Coroutine[...]`` return annotation identifies them as de-asynced (design/071).
    ``getattr(..., "__origin__", None)`` is required — non-generic return types have no
    ``__origin__``, and a bare attribute access would raise AttributeError.
    """

    def _is_async_or_coroutine(member: object) -> bool:
        if inspect.iscoroutinefunction(member):
            return True
        # Inspect the raw return annotation, not get_type_hints(member): get_type_hints
        # evaluates EVERY annotation, so one TYPE_CHECKING-only parameter name (e.g.
        # HandlerType) raises NameError and would silently drop a valid coroutine method
        # from the parity comparison. Follows the same approach as
        # tests/unit/test_forgotten_await_completeness.py::_is_detected — keep them in sync.
        ann = getattr(member, "__annotations__", {})
        ret = ann.get("return")
        if ret is None:
            return False
        if isinstance(ret, str):
            mod = sys.modules.get(getattr(member, "__module__", ""))
            if mod is None:
                return False
            try:
                ret = eval(ret, vars(mod))  # noqa: S307 — resolving module annotation
            except Exception:
                return False
        return getattr(ret, "__origin__", None) is collections.abc.Coroutine

    return {name for name, member in vars(cls).items() if not name.startswith("_") and _is_async_or_coroutine(member)}


@dataclass
class LoggingPipelineFixture:
    """Holds all components of a local logging pipeline."""

    stream: StringIO
    stream_handler: logging.StreamHandler
    capture: LogCaptureHandler
    listener: HassetteQueueListener
    queue_handler: logging.handlers.QueueHandler
    logger: logging.Logger


@pytest.fixture
def logging_pipeline() -> "LoggingPipelineFixture":  # pyright: ignore[reportReturnType]
    """Local logging pipeline for unit tests — no module globals.

    Constructs a self-contained QueueListener + stream/capture handlers, wires them
    to the hassette logger, yields the fixture, then tears down cleanly.
    """
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        add_execution_id,
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            _extract_record_fields,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    stream = StringIO()
    stream_handler = logging.StreamHandler(stream)
    stream_handler.setLevel(logging.NOTSET)
    stream_handler.setFormatter(formatter)

    capture = LogCaptureHandler(buffer_size=100)

    q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=100)
    queue_handler = logging.handlers.QueueHandler(q)
    queue_handler.addFilter(CorrelationFilter())

    listener = HassetteQueueListener(q, stream_handler, capture)
    listener.start()

    logger = logging.getLogger("hassette")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(queue_handler)

    fixture_obj = LoggingPipelineFixture(
        stream=stream,
        stream_handler=stream_handler,
        capture=capture,
        listener=listener,
        queue_handler=queue_handler,
        logger=logger,
    )

    yield fixture_obj  # pyright: ignore[reportReturnType]

    listener.stop()
    logger.removeHandler(queue_handler)


@dataclass
class PersistenceFixture:
    """Holds a LogPersistenceHandler wired to a mock DatabaseService."""

    handler: LogPersistenceHandler
    db_service: MagicMock
    enqueued_batches: list[list[dict]]


@pytest.fixture
def persistence_handler() -> PersistenceFixture:
    """LogPersistenceHandler with a mock DatabaseService.

    - spec=[] on mocks prevents auto-attribute creation (avoids MagicMock deadlock).
    - call_soon_threadsafe executes immediately — makes flush deterministic.
    - enqueued_batches captures every batch passed to _insert_log_records.
    """
    enqueued_batches: list[list[dict]] = []

    mock_db_service = MagicMock(spec=[])
    mock_db_service.enqueue = MagicMock(return_value=True)

    def capture_insert(records: list[dict]) -> object:
        enqueued_batches.append(records)
        return AsyncMock()()

    mock_db_service._insert_log_records = MagicMock(side_effect=capture_insert)

    mock_loop = MagicMock(spec=[])
    mock_loop.call_soon_threadsafe = MagicMock(side_effect=lambda fn: fn())
    mock_loop.is_running = MagicMock(return_value=True)

    handler = LogPersistenceHandler(mock_db_service, mock_loop, persistence_level=logging.DEBUG)

    return PersistenceFixture(
        handler=handler,
        db_service=mock_db_service,
        enqueued_batches=enqueued_batches,
    )


@pytest.fixture
def drain_forgotten_await_handles():
    """Drain handles dropped during a test so stray warnings cannot fail unrelated tests.

    With ``filterwarnings = ["error"]`` active globally, a ``RegistrationHandle`` GC'd
    after its test ends would raise ``HassetteForgottenAwaitWarning`` inside whatever
    test happens to trigger the collection. The test body runs with no blanket ignore
    filter (so ``pytest.warns`` assertions work); after the yield, a ``gc.collect()``
    inside a suppression context drains any dropped handles.

    Warning-heavy test modules opt in with a one-line module-level autouse wrapper.
    """
    yield
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", HassetteForgottenAwaitWarning)
        gc.collect()


def await_worker_ready(ready: threading.Event) -> None:
    """Block until a submitted worker signals that it is actually running."""
    assert ready.wait(timeout=WORKER_READY_TIMEOUT), "worker did not signal ready in time"


def busy_loop_worker(
    ready: threading.Event,
    *,
    terminated: threading.Event | None = None,
    reraise: bool = False,
) -> Callable[[], None]:
    """Build a Python-level busy loop that signals `ready`, then spins until interrupted.

    Only Python bytecode runs in the loop, so ``async_raise`` lands on the next instruction —
    the property the shutdown-interrupt tests rely on. SystemExit is swallowed by default so
    pytest's threadexception plugin does not treat the interrupted worker as a test failure;
    `reraise` keeps it propagating for tests asserting that the executor suppresses it.
    `terminated` is set when the interrupt is observed.

    Keep the loop body a bare ``pass``. Giving it any other shape (an ``if`` on a closure
    variable, for instance) makes CPython 3.14 deliver the async SystemExit at a point the
    frame's exception table does not route to this handler, so it escapes the thread instead
    of being caught — verified empirically, not a theoretical concern.
    """

    def run() -> None:
        ready.set()
        try:
            while True:
                pass
        except SystemExit:
            if terminated is not None:
                terminated.set()
            if reraise:
                raise

    return run


def sleeping_loop_worker(ready: threading.Event, interval: float = 0.01) -> Callable[[], None]:
    """Build a loop of short C sleeps that signals `ready`, then runs until interrupted.

    Unlike `busy_loop_worker`, the worker yields between iterations; each sleep returns to
    Python promptly, so ``async_raise`` still reaches it. SystemExit is swallowed.
    """

    def run() -> None:
        ready.set()
        try:
            while True:
                time.sleep(interval)
        except SystemExit:
            pass

    return run


def c_blocked_worker(ready: threading.Event, seconds: float = 60.0) -> Callable[[], None]:
    """Build a worker that signals `ready`, then blocks in a C-level sleep.

    ``async_raise`` cannot interrupt this until the call returns to Python, so shutdown must
    abandon the thread at budget expiry instead of waiting for it.
    """

    def run() -> None:
        ready.set()
        time.sleep(seconds)

    return run


def start_busy_thread(*, name: str | None = None, terminated: threading.Event | None = None) -> threading.Thread:
    """Start a daemon thread running `busy_loop_worker` and wait until it is spinning."""
    ready = threading.Event()
    thread = threading.Thread(target=busy_loop_worker(ready, terminated=terminated), name=name, daemon=True)
    thread.start()
    await_worker_ready(ready)
    return thread


def start_sleeping_thread(interval: float = 0.01) -> threading.Thread:
    """Start a daemon thread running `sleeping_loop_worker` and wait until it is looping."""
    ready = threading.Event()
    thread = threading.Thread(target=sleeping_loop_worker(ready, interval), daemon=True)
    thread.start()
    await_worker_ready(ready)
    return thread


def submit_busy_worker(
    executor: ThreadPoolExecutor, *, terminated: threading.Event | None = None, reraise: bool = False
) -> None:
    """Submit a Python busy-loop worker to `executor` and wait until it is spinning."""
    ready = threading.Event()
    executor.submit(busy_loop_worker(ready, terminated=terminated, reraise=reraise))
    await_worker_ready(ready)


def submit_c_blocked_worker(executor: ThreadPoolExecutor, seconds: float = 60.0) -> None:
    """Submit a C-blocked worker to `executor` and wait until it is blocked."""
    ready = threading.Event()
    executor.submit(c_blocked_worker(ready, seconds))
    await_worker_ready(ready)


def timed_shutdown(executor: InterruptibleThreadPoolExecutor, budget: float) -> float:
    """Shut `executor` down through the join/interrupt loop; return elapsed wall-clock seconds."""
    wall_start = time.monotonic()
    executor.shutdown(join_threads_or_timeout=True, timeout=budget)
    return time.monotonic() - wall_start
