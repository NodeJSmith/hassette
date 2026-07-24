"""EventCapture — intercept and query ``send_event`` calls in tests.

Replaces two fragile patterns that couple tests to ``send_event``'s parameter
list: ``capture_event`` closures monkey-patched onto ``send_event``, and
positional ``call_args`` indexing (``call[0][0]`` / ``call.args[0]``) on a
``send_event`` mock. Installing an ``EventCapture`` and querying it by topic
keeps tests resilient to future signature changes.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hassette.events import Event

if TYPE_CHECKING:
    from collections.abc import Iterator
    from unittest.mock import MagicMock

    from hassette.core.core import Hassette
    from hassette.types import Topic


@dataclass
class EventCapture:
    """Intercept ``send_event`` calls and query the captured events by topic.

    Install onto a real ``Hassette`` or a mock, run the code under test, then
    assert against :attr:`events`, :meth:`by_topic`, :meth:`payloads`, or
    :attr:`topics`.

    For mocks (fresh per test), use :meth:`install` directly. For real
    ``Hassette`` instances where the original must be restored, use
    :meth:`capturing` as a context manager::

        with EventCapture.capturing(hassette) as capture:
            await code_that_emits()
        assert capture.by_topic(Topic.X)
    """

    events: list[Event[Any]] = field(default_factory=list)

    def install(self, target: "Hassette | MagicMock") -> None:
        """Replace ``target.send_event`` with an async function that records events."""

        async def capture(event: Event[Any]) -> None:
            self.events.append(event)

        target.send_event = capture  # pyright: ignore[reportAttributeAccessIssue]

    @classmethod
    @contextmanager
    def capturing(cls, target: "Hassette | MagicMock") -> "Iterator[EventCapture]":
        """Install a capture, yield it, then restore the original ``send_event``."""
        original = target.send_event
        capture = cls()
        capture.install(target)
        try:
            yield capture
        finally:
            target.send_event = original  # pyright: ignore[reportAttributeAccessIssue]

    def by_topic(self, topic: "Topic | str") -> list[Event[Any]]:
        """Return captured events matching ``topic``, in emission order."""
        return [event for event in self.events if event.topic == topic]

    def payloads(self, topic: "Topic | str") -> list[Any]:
        """Return ``payload.data`` for each captured event matching ``topic``, in emission order."""
        return [event.payload.data for event in self.by_topic(topic)]

    @property
    def topics(self) -> list[str]:
        """All captured topics, in emission order."""
        return [str(event.topic) for event in self.events]
