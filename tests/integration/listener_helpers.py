"""Shared helpers for listener integration tests (test_listeners_*.py).

`make_recording_listener` covers the "handler appends `event.data` to a list" shape only. Tests
whose handler is itself the subject — dependency-injection annotations, or a throwaway handler
passed to a `create_listener` call expected to raise — build their own.
"""

from dataclasses import dataclass
from typing import Any

from hassette.bus.listeners import Listener
from hassette.events import Event
from hassette.task_bucket import TaskBucket
from hassette.types import HandlerType
from tests.support.helpers import create_listener


@dataclass(frozen=True, slots=True)
class MockEvent(Event[str]):
    """Mock event for testing."""

    @property
    def data(self) -> str:
        """Return payload for backward compatibility with tests."""
        return self.payload


def mock_event(data: str = "test") -> MockEvent:
    """Create a MockEvent with a topic and payload."""
    return MockEvent(topic="test_topic", payload=data)


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


async def dispatch_values(listener: Listener, *values: str) -> None:
    """Dispatch one invocation per value through the listener's rate limiter."""
    for value in values:

        async def invoke_fn(val: str = value) -> None:
            await listener.invoker.invoke(mock_event(val))

        await listener.invoker.dispatch(invoke_fn)


async def invoke_handler(bucket: TaskBucket, handler: HandlerType, data: str = "test_data") -> None:
    """Create a listener for `handler` and invoke it once with a mock event carrying `data`."""
    listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")
    await listener.invoker.invoke(mock_event(data))
