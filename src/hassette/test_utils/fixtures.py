import contextlib
import json
import random
import typing
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from hassette.events import Event, RawStateChangeEvent, create_event_from_hass

from .harness import HassetteHarness

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from hassette import Api, Hassette, HassetteConfig
    from hassette.events.hass.raw import HassEventEnvelopeDict
    from hassette.test_utils.test_server import SimpleTestServer


@contextlib.asynccontextmanager
async def _build_harness(**kwargs) -> "AsyncIterator[HassetteHarness]":
    harness = HassetteHarness(**kwargs)
    try:
        await harness.start()
        yield harness
    finally:
        await harness.stop()
        harness.config.reload()


@pytest.fixture(scope="module")
def hassette_harness(
    unused_tcp_port_factory,
) -> "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]":
    def _factory(**kwargs) -> contextlib.AbstractAsyncContextManager[HassetteHarness]:
        return _build_harness(**kwargs, unused_tcp_port=unused_tcp_port_factory())

    return _factory


@pytest.fixture(scope="module")
async def hassette_with_nothing(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(config=test_config) as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture(scope="module")
async def hassette_with_bus(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(config=test_config, use_bus=True) as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture(scope="module")
async def hassette_with_mock_api(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[tuple[Api, SimpleTestServer]]":
    async with hassette_harness(
        config=test_config, use_bus=True, use_api_mock=True, use_state_registry=True
    ) as harness:
        assert harness.hassette.api is not None
        assert harness.api_mock is not None
        yield harness.hassette.api, harness.api_mock


@pytest.fixture(scope="module")
async def hassette_with_real_api(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(config=test_config, use_bus=True, use_api_real=True, use_websocket=True) as harness:
        assert harness.hassette.api is not None
        yield cast("Hassette", harness.hassette)


@pytest.fixture(scope="module")
async def hassette_with_scheduler(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(config=test_config, use_bus=True, use_scheduler=True) as harness:
        assert harness.hassette._scheduler is not None
        yield cast("Hassette", harness.hassette)


@pytest.fixture(scope="module")
async def hassette_with_file_watcher(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config_with_apps,
) -> "AsyncIterator[Hassette]":
    config = test_config_with_apps

    async with hassette_harness(config=config, use_bus=True, use_file_watcher=True, use_api_mock=True) as harness:
        assert harness.hassette._file_watcher is not None
        assert harness.hassette._bus_service is not None

        yield cast("Hassette", harness.hassette)


@pytest.fixture
async def hassette_with_app_handler(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config_with_apps,
) -> "AsyncIterator[Hassette]":
    # TODO: see if we can get this to be module scoped - currently fails
    # because there are config changes that persist between tests
    async with hassette_harness(
        config=test_config_with_apps,
        use_bus=True,
        use_app_handler=True,
        use_scheduler=True,
    ) as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture(scope="module")
async def hassette_with_state_proxy(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    """Module-scoped Hassette fixture with state proxy.

    Uses module scope for 5-10x performance improvement.
    Tests should use the cleanup_state_proxy_fixture to reset state between tests.
    """
    async with hassette_harness(
        config=test_config, use_bus=True, use_state_proxy=True, use_state_registry=True
    ) as harness:
        assert harness.hassette._state_proxy is not None
        assert harness.hassette.api is not None
        yield cast("Hassette", harness.hassette)


@pytest.fixture(scope="module")
async def hassette_with_state_registry(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(config=test_config, use_bus=True, use_state_registry=True) as harness:
        yield typing.cast("Hassette", harness.hassette)


@pytest.fixture(scope="session")
def state_change_events(test_events_path: Path) -> list[RawStateChangeEvent]:
    """Load state change events from test data file."""
    events = []
    with open(test_events_path / "state_change_events.jsonl") as f:
        for line in f:
            if line.strip():
                # Strip trailing comma if present (JSONL files may have them)
                line = line.strip().rstrip(",")
                envelope: HassEventEnvelopeDict = json.loads(line)
                event = create_event_from_hass(envelope)
                if isinstance(event, RawStateChangeEvent):
                    events.append(event)

    # randomize order
    random.shuffle(events)

    return events


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
    events = []
    with open(test_events_path / "other_events.jsonl") as f:
        for line in f:
            if line.strip():
                # Strip trailing comma if present (JSONL files may have them)
                line = line.strip().rstrip(",")
                envelope: HassEventEnvelopeDict = json.loads(line)
                event = create_event_from_hass(envelope)
                events.append(event)

    # randomize order
    random.shuffle(events)

    return events


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


@pytest.fixture(autouse=True)
async def cleanup_state_proxy_fixture(request: pytest.FixtureRequest):
    """Automatically reset state proxy before each test when using hassette_with_state_proxy.

    This autouse fixture resets the state proxy BEFORE each test to ensure a clean state.
    It only resets if the test actually uses the hassette_with_state_proxy fixture.
    """
    from hassette.test_utils.reset import reset_state_proxy

    # Before test runs, check if hassette_with_state_proxy will be used and reset it
    if "hassette_with_state_proxy" in request.fixturenames:
        try:
            hassette = request.getfixturevalue("hassette_with_state_proxy")
            if hassette._state_proxy is not None:
                await reset_state_proxy(hassette._state_proxy)
                print(f"Reset StateProxy for test {request.node.name}")
        except Exception:
            # If fixture wasn't instantiated yet or reset fails, that's okay
            # First test in the module will get a fresh fixture
            pass

    return
