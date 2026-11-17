"""Internal event metadata helpers for framework coordination."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hassette.events.base import AnyEvent


def stamp_websocket_generation(event: "AnyEvent", generation: int | None) -> None:
    """Stamp an event with the WebSocket connection generation it was observed under.

    Args:
        event: The event to stamp. ``Event`` is frozen, so this bypasses `__setattr__`
            via `object.__setattr__` rather than mutating the dataclass normally.
        generation: The connection generation to stamp, or None if there is no current
            connected generation (e.g. the event was produced while disconnected).
    """
    object.__setattr__(event, "websocket_generation", generation)
