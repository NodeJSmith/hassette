"""Tracked invocation function builder for listener dispatch.

Encapsulates timeout resolution, error handler resolution, InvokeHandler
construction, and executor dispatch into a single reusable factory function.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from hassette.core.commands import InvokeHandler

if TYPE_CHECKING:
    from hassette.bus.listeners import Listener
    from hassette.core.command_executor import CommandExecutor
    from hassette.events.base import Event


def build_tracked_invoke_fn(
    listener: "Listener",
    event: "Event[Any]",
    topic: str,
    executor: "CommandExecutor",
    config_resolver: Callable[[], float | None],
    is_synthetic: bool = False,
) -> Callable[[], Awaitable[None]]:
    """Build an invoke function for a listener with telemetry.

    The returned closure reads ``listener.db_id`` lazily at call time (not capture
    time) so that debounced handlers see the correct ``db_id`` after async registration
    completes.  When ``db_id`` is still ``None`` at fire time, ``InvokeHandler`` is
    created with ``listener_id=None`` and produces an orphan record.

    ``config_resolver`` is called lazily at fire time (not capture time) to preserve
    hot-reload correctness for debounced handlers — config changes applied between
    registration and dispatch are reflected in the effective timeout.

    Can propagate ``CancelledError`` — the ``CommandExecutor`` re-raises it after
    recording a cancellation record.

    Args:
        listener: The listener to invoke.
        event: The event to pass to the handler.
        topic: The event topic this handler is being invoked for.
        executor: CommandExecutor that records telemetry and runs the handler.
        config_resolver: Callable that returns the current event_handler_timeout_seconds,
            or None if no global timeout is configured.
        is_synthetic: True when the event was synthesized by hassette (e.g., immediate=True
            initial fire). Synthetic events suppress trigger_context_id recording.

    Returns:
        An async callable that, when awaited, invokes the listener handler with
        telemetry and applies timeout and error handler logic.
    """

    async def execute_fn() -> None:
        # Resolve effective timeout lazily at fire time (not capture time) so that
        # debounced handlers see config changes applied via hot reload.
        if listener.options.timeout_disabled:
            effective_timeout = None
        elif listener.options.timeout is not None:
            effective_timeout = listener.options.timeout
        else:
            effective_timeout = config_resolver()

        # Resolve the app-level error handler at dispatch time from the owning Bus.
        # The resolver is a closure set by Bus.on() that reads Bus._error_handler lazily,
        # so this always reflects the current handler at the moment of dispatch.
        resolver = listener.invoker.app_error_handler_resolver
        app_level_error_handler = resolver() if resolver is not None else None

        cmd = InvokeHandler(
            listener=listener,
            event=event,
            topic=topic,
            listener_id=listener.db_id,
            source_tier=listener.identity.source_tier,
            effective_timeout=effective_timeout,
            app_level_error_handler=app_level_error_handler,
            is_synthetic=is_synthetic,
        )
        await executor.execute(cmd)

    return execute_fn
