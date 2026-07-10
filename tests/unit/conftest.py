"""Shared fixtures for tests/unit/."""

import asyncio
import collections.abc
import gc
import inspect
import logging
import logging.handlers
import queue
import sys
import warnings
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
from hassette.core.sync_executor_service import SYNC_EXECUTOR_THREAD_NAME_PREFIX, SyncExecutorService
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

if TYPE_CHECKING:
    from contextvars import Token

    from hassette import Hassette

TEST_TOKEN = "test-token"


def make_test_config(max_workers: int = 4, shutdown_timeout: float = 5.0) -> HassetteConfig:
    return HassetteConfig(
        token=TEST_TOKEN,
        lifecycle={
            "sync_executor_max_workers": max_workers,
            "sync_executor_shutdown_timeout_seconds": shutdown_timeout,
        },
    )


def make_sync_executor_hassette(max_workers: int = 4, shutdown_timeout: float = 5.0) -> MagicMock:
    config = make_test_config(max_workers=max_workers, shutdown_timeout=shutdown_timeout)
    mock_hassette = MagicMock()
    mock_hassette.config = config
    mock_hassette.task_bucket = MagicMock()
    mock_hassette.shutdown_event = asyncio.Event()
    mock_hassette.children = []
    mock_hassette._should_skip_dependency_check = MagicMock(return_value=True)
    return mock_hassette


def make_service(max_workers: int = 4, shutdown_timeout: float = 5.0) -> SyncExecutorService:
    mock_hassette = make_sync_executor_hassette(max_workers=max_workers, shutdown_timeout=shutdown_timeout)
    svc = SyncExecutorService(mock_hassette)
    svc.executor = InterruptibleThreadPoolExecutor(
        max_workers=mock_hassette.config.lifecycle.sync_executor_max_workers,
        thread_name_prefix=SYNC_EXECUTOR_THREAD_NAME_PREFIX,
    )
    return svc


def capture_saturation_warnings(svc: SyncExecutorService) -> list[tuple]:
    """Patch svc.logger.warning to capture saturation warning calls."""
    calls: list[tuple] = []
    svc.logger.warning = lambda msg, *a: calls.append((msg, *a))  # pyright: ignore[reportAttributeAccessIssue]
    return calls


def make_mock_parent() -> MagicMock:
    """Mock owning App resource with the attributes guard_await and telemetry read."""
    parent = MagicMock()
    parent.app_key = "test_app"
    parent.index = 0
    parent.unique_name = "test_app.0"
    parent.source_tier = "app"
    parent.class_name = "TestApp"
    parent.app_config = MagicMock()
    parent.app_config.forgotten_await_behavior = None
    return parent


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
