"""EventStreamService — owns the anyio memory channel for event routing."""

import typing

from anyio import create_memory_object_stream

from hassette.resources.base import Resource

if typing.TYPE_CHECKING:
    from typing import Any

    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

    from hassette import Hassette
    from hassette.events import Event


class EventStreamService(Resource):
    """Owns the anyio memory channel that routes events from producers to the bus.

    This is a Resource (no background task). It creates the send/receive streams
    at construction time and tears them down on shutdown.
    """

    _send_stream: "MemoryObjectSendStream[tuple[str, Event[Any]]]"
    _receive_stream: "MemoryObjectReceiveStream[tuple[str, Event[Any]]]"

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        buffer_size = hassette.config.hassette_event_buffer_size
        self._send_stream, self._receive_stream = create_memory_object_stream[tuple[str, "Event[Any]"]](buffer_size)

    @property
    def receive_stream(self) -> "MemoryObjectReceiveStream[tuple[str, Event[Any]]]":
        """The receive end of the event stream, for BusService to clone."""
        return self._receive_stream

    async def send_event(self, event_name: str, event: "Event[Any]") -> None:
        """Send an event to the bus via the memory channel."""
        await self._send_stream.send((event_name, event))

    @property
    def event_streams_closed(self) -> bool:
        """Check if both streams are closed."""
        return self._send_stream._closed and self._receive_stream._closed  # pyright: ignore[reportPrivateUsage]

    async def on_shutdown(self) -> None:
        """Close both streams."""
        await self._send_stream.aclose()
        await self._receive_stream.aclose()
