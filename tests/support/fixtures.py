import asyncio
import json
import os
import random
import typing
from collections.abc import Iterator
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from hassette.core.core import Hassette
from hassette.core.sync_executor import SyncExecutor
from hassette.events import Event, RawStateChangeEvent, create_event_from_hass
from hassette.testing import HassetteHarness
from hassette.testing.config import TEST_SYNC_EXECUTOR_SHUTDOWN_TIMEOUT_SECONDS
from tests.support.factories import make_sync_executor

LOGGER = getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from hassette import Api, HassetteConfig
    from hassette.events.hass.raw import HassEventEnvelopeDict
    from hassette.testing._server import SimpleTestServer


async def _start_module_harness(harness: HassetteHarness, request: pytest.FixtureRequest) -> HassetteHarness:
    """Start *harness* and register synchronous teardown via ``request.addfinalizer()``.

    Every module-scoped harness fixture below shares this shape instead of the
    ``async with harness: yield harness`` pattern used elsewhere in this file, for the
    same reason documented in full in ``tests/integration/conftest.py::hassette_instance``:
    pytest-asyncio resumes a ``yield``-based async-generator fixture's teardown by creating
    a brand-new Task on the shared (session-scoped) event loop. If a test running against
    this harness triggers a real ``hassette.shutdown()`` (e.g. ServiceWatcher exhausting a
    PERMANENT service's restart budget in ``tests/integration/test_service_watcher.py``),
    the loop's task factory -- installed by ``HassetteHarness.start()`` and still pointing
    at this harness's now-sealed root TaskBucket -- rejects that very Task-creation call
    before ``HassetteHarness.stop()`` (which itself correctly restores the previous task
    factory in its own ``finally`` block) ever gets a chance to run. Because that loop is
    shared for the rest of the pytest-xdist worker's session, every later test on the
    worker then fails the same way, regardless of which module it lives in.

    A synchronous ``request.addfinalizer()`` callback sidesteps this: it restores the task
    factory that ``HassetteHarness.start()`` saved (``harness._previous_task_factory``)
    *before* calling ``loop.run_until_complete()``, so that call's own internal Task
    creation (via ``ensure_future()``) is safe, and only then drives ``harness.stop()``
    (which redundantly re-restores the same factory, harmlessly) plus the config reload.
    """
    await harness.start()
    loop = asyncio.get_running_loop()

    def _teardown() -> None:
        # Order matters: restore the task factory before anything that might create a new
        # Task, including run_until_complete()'s own ensure_future() call.
        loop.set_task_factory(harness._previous_task_factory)
        loop.run_until_complete(harness.stop())
        harness.config.reload()

    # PT021: request.addfinalizer() instead of `yield` is deliberate here, not the usual
    # missed-convention case that rule flags -- see the docstring above for why a `yield`
    # based async-generator fixture deadlocks for this specific fixture family.
    request.addfinalizer(_teardown)
    return harness


@pytest.fixture(scope="module")
def hassette_harness(
    unused_tcp_port_factory,
) -> "Callable[[HassetteConfig], HassetteHarness]":
    """Factory fixture that creates a HassetteHarness with a fresh TCP port.

    Returns a factory that accepts a config and returns a bare harness
    ready for builder-method chaining and use as an async context manager.
    """

    def _factory(config: "HassetteConfig") -> HassetteHarness:
        return HassetteHarness(config, unused_tcp_port=unused_tcp_port_factory())

    return _factory


@pytest.fixture(scope="module")
async def hassette_with_sync_executor(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
    request: pytest.FixtureRequest,
) -> HassetteHarness:
    """Harness with the sync executor wired, but no bus/scheduler/app components.

    TaskBucket.run_in_thread delegates to SyncExecutor.submit(), so any
    test that dispatches a sync handler through the bare task bucket needs it.
    """
    return await _start_module_harness(hassette_harness(test_config).with_sync_executor(), request)


@pytest.fixture
def sync_executor() -> Iterator[SyncExecutor]:
    """Standalone SyncExecutor with a real thread pool for tests that need run_in_thread."""
    executor = make_sync_executor()
    try:
        yield executor
    finally:
        executor.shutdown_pool(timeout=TEST_SYNC_EXECUTOR_SHUTDOWN_TIMEOUT_SECONDS)


@pytest.fixture(scope="module")
async def hassette_with_bus(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
    request: pytest.FixtureRequest,
) -> HassetteHarness:
    return await _start_module_harness(hassette_harness(test_config).with_bus(), request)


@pytest.fixture(scope="module")
async def hassette_with_mock_api(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[tuple[Api, SimpleTestServer]]":
    async with hassette_harness(test_config).with_api_mock().with_state_registry() as harness:
        assert harness.hassette.api is not None
        assert harness.api_mock is not None
        yield harness.hassette.api, harness.api_mock


@pytest.fixture(scope="module")
async def hassette_with_scheduler(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
    request: pytest.FixtureRequest,
) -> HassetteHarness:
    return await _start_module_harness(hassette_harness(test_config).with_bus().with_scheduler(), request)


@pytest.fixture(scope="module")
async def hassette_with_file_watcher(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config_with_apps,
    request: pytest.FixtureRequest,
) -> HassetteHarness:
    return await _start_module_harness(
        hassette_harness(test_config_with_apps).with_bus().with_file_watcher().with_api_mock(), request
    )


@pytest.fixture(scope="module")
async def hassette_with_app_handler(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config_with_apps,
    request: pytest.FixtureRequest,
) -> HassetteHarness:
    return await _start_module_harness(
        hassette_harness(test_config_with_apps).with_app_handler().with_scheduler(), request
    )


@pytest.fixture
async def hassette_with_app_handler_custom_config(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config_with_temp_path: "HassetteConfig",
) -> "AsyncIterator[HassetteHarness]":
    async with hassette_harness(test_config_with_temp_path).with_app_handler().with_scheduler() as harness:
        yield harness


@pytest.fixture(scope="module")
async def hassette_with_state_proxy(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
    request: pytest.FixtureRequest,
) -> HassetteHarness:
    """Module-scoped HassetteHarness fixture with state proxy.

    Uses module scope for 5-10x performance improvement.
    State is reset between tests by the autouse cleanup_harness fixture.
    """
    return await _start_module_harness(
        hassette_harness(test_config).with_state_proxy().with_state_registry().with_scheduler(), request
    )


@pytest.fixture(scope="module")
async def hassette_with_state_registry(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
    request: pytest.FixtureRequest,
) -> HassetteHarness:
    return await _start_module_harness(hassette_harness(test_config).with_bus().with_state_registry(), request)


def _load_and_shuffle_events(path: Path) -> list[Event]:
    """Load events from a JSONL file and shuffle with a seeded RNG."""
    events = []
    with open(path) as f:
        for line in f:
            if line.strip():
                line = line.strip().rstrip(",")
                envelope: HassEventEnvelopeDict = json.loads(line)
                events.append(create_event_from_hass(envelope))

    seed = int.from_bytes(os.urandom(8))
    LOGGER.info("Event shuffle seed for %s: %d", path.name, seed)
    rng = random.Random(seed)
    rng.shuffle(events)
    return events


@pytest.fixture(scope="session")
def state_change_events(test_events_path: Path) -> list[RawStateChangeEvent]:
    """Load state change events from test data file."""
    events = _load_and_shuffle_events(test_events_path / "state_change_events.jsonl")
    return [e for e in events if isinstance(e, RawStateChangeEvent)]


@pytest.fixture(scope="session")
def state_change_events_with_new_state(
    state_change_events: list[RawStateChangeEvent],
) -> list[RawStateChangeEvent]:
    """Filter state change events to only those with a new state."""
    return [e for e in state_change_events if e.payload.data.new_state is not None]


@pytest.fixture(scope="session")
def state_change_events_with_old_state(
    state_change_events: list[RawStateChangeEvent],
) -> list[RawStateChangeEvent]:
    """Filter state change events to only those with an old state."""
    return [e for e in state_change_events if e.payload.data.old_state is not None]


@pytest.fixture(scope="session")
def state_change_events_with_both_states(
    state_change_events: list[RawStateChangeEvent],
) -> list[RawStateChangeEvent]:
    """Filter state change events to only those with both old and new states."""
    return [
        e for e in state_change_events if e.payload.data.old_state is not None and e.payload.data.new_state is not None
    ]


@pytest.fixture(scope="session")
def other_events(test_events_path: Path) -> list[Event]:
    """Load other events from test data file."""
    return _load_and_shuffle_events(test_events_path / "other_events.jsonl")


@pytest.fixture(scope="session")
def all_events(
    state_change_events: list[RawStateChangeEvent],
    other_events: list[Event],
) -> list[Event]:
    """Combine all events into a single list."""
    return state_change_events + other_events


@pytest.fixture(scope="session")
def hass_state_dicts(state_change_events: list[RawStateChangeEvent]) -> list[dict[str, typing.Any]]:
    """Extract raw state dictionaries from state change events."""
    states = []
    for event in state_change_events:
        if event.payload.data.new_state:
            states.append(event.payload.data.new_state)

        if event.payload.data.old_state:
            states.append(event.payload.data.old_state)
    return states


def run_hassette_startup_tasks(config: "HassetteConfig") -> None:
    """Run Hassette's one-time startup tasks without wiring services.

    Creates a bare Hassette (no I/O side effects — only field init and logging
    setup) and calls startup_tasks(). The instance is intentionally discarded;
    wire_services() is not called.
    """
    Hassette(config).startup_tasks()
