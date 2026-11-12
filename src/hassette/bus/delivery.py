"""One event reaching one listener: the unit every dispatch step runs, and every drop site reports.

A ``Delivery`` is created where an event reaches a listener: a live match in ``BusService``, an immediate fire,
a hold's fire-time recheck, or the event that cancels a hold. Every later step takes the delivery itself, so the
event a handler runs for, the event a dropped run reports, and whether that event was built from the cached state
always come from the same place.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hassette.commands import InvokeHandler

if TYPE_CHECKING:
    from hassette_wire import ListenerMissReason

    from hassette.bus.listeners import Listener
    from hassette.core.command_executor import CommandExecutor
    from hassette.events.base import AnyEvent


@dataclass(frozen=True, slots=True)
class Delivery:
    """``event`` reaching ``listener`` on ``topic``."""

    listener: "Listener"
    event: "AnyEvent"
    topic: str
    """The route the event matched on; the listener's own topic for an event built from the cached state."""
    is_synthetic: bool = False
    """Whether ``event`` was built from the cached state (an immediate fire or a hold's recheck), not received live.
    Its run and its near-misses are labelled ``HASSETTE_SYNTHETIC`` (design/specs/147-execution-trigger-detail D7)."""

    def drop(self, reason: "ListenerMissReason", *, filter_index: int | None = None) -> None:
        """Report this event as a near-miss of its listener.

        Reads the listener's reporter now, not when the delivery was made, so a listener removed in the meantime
        records nothing. No-op for a listener with no reporter bound.

        Args:
            reason: Why the handler didn't run.
            filter_index: For ``reason='filter'``, the index in ``listener.filters`` of the filter that rejected it.
        """
        report = self.listener.invoker.report_drop
        if report is not None:
            report(reason, self.event, filter_index=filter_index, is_synthetic=self.is_synthetic)

    async def invoke(self, executor: "CommandExecutor", config_resolver: Callable[[], float | None]) -> None:
        """Run the listener's handler for this event through ``executor``, which records the execution.

        Everything that can change between delivery and run is read now: ``listener.db_id`` (a debounced run can
        start after registration completes; ``None`` still produces an orphan record), the effective timeout
        (``config_resolver`` reflects hot-reloaded config), and the app-level error handler.

        Can propagate ``CancelledError``: the executor re-raises it after recording a cancellation.

        Args:
            executor: Records telemetry and runs the handler.
            config_resolver: Returns the global ``event_handler_timeout_seconds``, or None when none is configured.
        """
        listener = self.listener
        resolver = listener.invoker.app_error_handler_resolver
        cmd = InvokeHandler(
            listener=listener,
            event=self.event,
            topic=self.topic,
            listener_id=listener.db_id,
            source_tier=listener.identity.source_tier,
            effective_timeout=listener.invoker.effective_timeout(config_resolver),
            app_level_error_handler=resolver() if resolver is not None else None,
            is_synthetic=self.is_synthetic,
        )
        await executor.execute(cmd)
