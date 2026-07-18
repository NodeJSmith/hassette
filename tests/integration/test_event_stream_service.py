"""Integration tests for EventStreamService."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from hassette.core.event_stream_service import EventStreamService
from hassette.test_utils import make_mock_hassette


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette with the event buffer size config."""
    return make_mock_hassette(sealed=False)


@pytest.fixture
async def event_stream_service(mock_hassette) -> AsyncIterator[EventStreamService]:
    """Create an EventStreamService with default buffer size, cleaned up after test."""
    service = EventStreamService(mock_hassette, parent=mock_hassette)
    try:
        yield service
    finally:
        if not service.event_streams_closed:
            await service.close_streams()


async def test_send_and_receive(event_stream_service: EventStreamService) -> None:
    """send_event pushes events that are receivable from receive_stream."""
    payload = SimpleNamespace(topic="test.topic", value=42)
    await event_stream_service.send_event(payload)  # pyright: ignore[reportArgumentType]

    event = await event_stream_service.receive_stream.receive()
    assert event is payload
    assert event.topic == "test.topic"


async def test_event_streams_closed_is_false_initially(event_stream_service: EventStreamService) -> None:
    """Streams start open."""
    assert event_stream_service.event_streams_closed is False


async def test_close_streams_closes_both(event_stream_service: EventStreamService) -> None:
    """close_streams() closes both send and receive streams."""
    await event_stream_service.close_streams()
    assert event_stream_service.event_streams_closed is True


async def test_custom_buffer_size() -> None:
    """Buffer size is read from config, not hardcoded."""
    hassette = make_mock_hassette(sealed=False, hassette_event_buffer_size=3)
    service = EventStreamService(hassette, parent=hassette)

    try:
        # Fill the buffer (3 events)
        for i in range(3):
            await service.send_event(SimpleNamespace(topic=f"topic.{i}", n=i))  # pyright: ignore[reportArgumentType]

        # The 4th send should block (buffer full) — verify by racing with a short timeout
        send_completed = False

        async def try_send() -> None:
            nonlocal send_completed
            await service.send_event(SimpleNamespace(topic="topic.overflow", n=3))  # pyright: ignore[reportArgumentType]
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
    hassette = make_mock_hassette(sealed=False, hassette_event_buffer_size=1000)
    service = EventStreamService(hassette, parent=hassette)

    try:
        # Should be able to send 1000 events without blocking
        for i in range(1000):
            await service.send_event(SimpleNamespace(topic=f"topic.{i}", n=i))  # pyright: ignore[reportArgumentType]
    finally:
        await service.close_streams()


async def test_receive_stream_returns_correct_end(event_stream_service: EventStreamService) -> None:
    """receive_stream property returns the receive end of the channel."""
    stream = event_stream_service.receive_stream
    # Verify it's a receive stream by sending and then receiving
    await event_stream_service.send_event(SimpleNamespace(topic="check"))  # pyright: ignore[reportArgumentType]
    event = await stream.receive()
    assert event.topic == "check"
