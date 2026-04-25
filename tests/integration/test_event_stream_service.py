"""Integration tests for EventStreamService."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hassette.core.event_stream_service import EventStreamService


def _make_mock_hassette(buffer_size: int = 1000) -> MagicMock:
    hassette = MagicMock()
    hassette.config.hassette_event_buffer_size = buffer_size
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    return hassette


@pytest.fixture
def mock_hassette() -> MagicMock:
    """Create a mock Hassette with the event buffer size config."""
    return _make_mock_hassette()


@pytest.fixture
async def event_stream_service(mock_hassette: MagicMock) -> AsyncIterator[EventStreamService]:
    """Create an EventStreamService with default buffer size, cleaned up after test."""
    service = EventStreamService(mock_hassette, parent=mock_hassette)
    try:
        yield service
    finally:
        if not service.event_streams_closed:
            await service.close_streams()


async def test_send_and_receive(event_stream_service: EventStreamService) -> None:
    """send_event pushes events that are receivable from receive_stream."""
    payload = SimpleNamespace(value=42)
    await event_stream_service.send_event("test.topic", payload)  # pyright: ignore[reportArgumentType]

    topic, event = await event_stream_service.receive_stream.receive()
    assert topic == "test.topic"
    assert event is payload


async def test_event_streams_closed_is_false_initially(event_stream_service: EventStreamService) -> None:
    """Streams start open."""
    assert event_stream_service.event_streams_closed is False


async def test_close_streams_closes_both(event_stream_service: EventStreamService) -> None:
    """close_streams() closes both send and receive streams."""
    await event_stream_service.close_streams()
    assert event_stream_service.event_streams_closed is True


async def test_custom_buffer_size() -> None:
    """Buffer size is read from config, not hardcoded."""
    hassette = _make_mock_hassette(buffer_size=3)
    service = EventStreamService(hassette, parent=hassette)

    try:
        # Fill the buffer (3 events)
        for i in range(3):
            await service.send_event(f"topic.{i}", SimpleNamespace(n=i))  # pyright: ignore[reportArgumentType]

        # The 4th send should block (buffer full) — verify by racing with a short timeout
        send_completed = False

        async def try_send() -> None:
            nonlocal send_completed
            await service.send_event("topic.overflow", SimpleNamespace(n=3))  # pyright: ignore[reportArgumentType]
            send_completed = True

        task = asyncio.create_task(try_send())
        # negative-assertion: no event-driven alternative
        await asyncio.sleep(0.05)
        assert not send_completed, "Expected send to block on full buffer"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await service.close_streams()


async def test_default_buffer_size() -> None:
    """Default buffer size of 1000 is used when config is not explicitly set."""
    hassette = _make_mock_hassette(buffer_size=1000)
    service = EventStreamService(hassette, parent=hassette)

    try:
        # Should be able to send 1000 events without blocking
        for i in range(1000):
            await service.send_event(f"topic.{i}", SimpleNamespace(n=i))  # pyright: ignore[reportArgumentType]
    finally:
        await service.close_streams()


async def test_receive_stream_returns_correct_end(event_stream_service: EventStreamService) -> None:
    """receive_stream property returns the receive end of the channel."""
    stream = event_stream_service.receive_stream
    # Verify it's a receive stream by sending and then receiving
    await event_stream_service.send_event("check", SimpleNamespace())  # pyright: ignore[reportArgumentType]
    topic, _ = await stream.receive()
    assert topic == "check"
