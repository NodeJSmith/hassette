"""Shared helpers for listener integration tests (test_listeners_*.py).

`make_recording_listener` covers the "handler appends `event.data` to a list" shape only. Tests
whose handler is itself the subject — dependency-injection annotations, or a throwaway handler
passed to a `create_listener` call expected to raise — build their own.
"""

from dataclasses import dataclass
from typing import Any

from hassette.bus.listeners import Listener
from hassette.events import Event, EventPayload
from hassette.task_bucket import TaskBucket
from hassette.types import HandlerType
from tests.support.factories import make_mock_invoking_executor
from tests.support.helpers import create_listener, make_delivery

TEST_DELIVERY = make_delivery()
"""The delivery the rate-limiter tests pass alongside their own handler closures; nothing invokes it."""


@dataclass(frozen=True, slots=True)
class MockEvent(Event[EventPayload[str]]):
    """Mock event for testing."""

    @property
    def data(self) -> str:
        """Return the payload's data so handlers can record it directly."""
        return self.payload.data


def mock_event(data: str = "test") -> MockEvent:
    """Create a MockEvent with a topic and payload."""
    return MockEvent(topic="test_topic", payload=EventPayload(data=data))


def make_recording_listener(
    bucket: TaskBucket, *, topic: str = "t", **listener_kwargs: Any
) -> tuple[Listener, list[str]]:
    """Create a listener whose handler records each event's data, alongside the list it records into.

    Args:
        bucket: TaskBucket the listener runs its handler in.
        topic: Listener topic. Invocation-level tests call `invoke()`/`dispatch()` directly, so
            this only matters for tests that route through topic matching.
        listener_kwargs: Forwarded to `create_listener` — typically the rate-limiting option
            under test (`debounce=`, `throttle=`, `once=`).
    """
    calls: list[str] = []

    def handler(event: MockEvent) -> None:
        calls.append(event.data)

    listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic=topic, **listener_kwargs)
    return listener, calls


async def invoke_with(listener: Listener, data: str) -> None:
    """Invoke the listener's handler once with a mock event carrying `data`."""
    await listener.invoker.invoke(mock_event(data))


async def dispatch_values(listener: Listener, *values: str) -> None:
    """Dispatch one delivery per value through the listener's invoker, each carrying a mock event with that value.

    The handler runs for the delivery's own event, so what it records is what was dispatched.
    """
    executor = make_mock_invoking_executor()
    for value in values:
        await listener.invoker.dispatch(make_delivery(listener, mock_event(value)), executor, lambda: None)


async def invoke_handler(bucket: TaskBucket, handler: HandlerType, data: str = "test_data") -> None:
    """Create a listener for `handler` and invoke it once with a mock event carrying `data`."""
    listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")
    await invoke_with(listener, data)
