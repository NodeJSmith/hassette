"""Handler invocation for bus listeners: ``HandlerInvoker`` and the near-miss ``DropReporter`` protocol."""

import typing
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from logging import getLogger
from typing import Any, cast

from hassette_wire import ExecutionMode

from hassette.bus.injection import ParameterInjector
from hassette.bus.rate_limiter import RateLimiter
from hassette.exceptions import TaskBucketSealedError
from hassette.execution_mode import (
    ExecutionModeGuard,
    Outcome,
    describe_stall_threshold,
    release_and_drain,
    resolve_effective_timeout,
    run_parallel,
    run_through_guard,
)
from hassette.utils.func_utils import callable_name, callable_short_name
from hassette.utils.type_utils import get_typed_signature

if typing.TYPE_CHECKING:
    import asyncio

    from hassette_wire import ListenerMissReason

    from hassette import TaskBucket
    from hassette.bus.delivery import Delivery
    from hassette.bus.listeners import ListenerOptions
    from hassette.core.command_executor import CommandExecutor
    from hassette.events.base import AnyEvent
    from hassette.types import AsyncHandlerType, HandlerType
    from hassette.types.types import BusErrorHandlerType

LOGGER = getLogger(__name__)


class DropReporter(typing.Protocol):
    """Records one event that reached an app listener and didn't run its handler (a near-miss).

    ``BusService`` binds one per app listener at registration. Drop sites don't call it directly: they call
    ``Delivery.drop``, which passes the delivery's event and synthetic flag.
    """

    def __call__(
        self,
        reason: "ListenerMissReason",
        event: "AnyEvent",
        *,
        filter_index: int | None = None,
        is_synthetic: bool = False,
    ) -> None: ...


@dataclass(slots=True)
class HandlerInvoker:
    """Owns handler invocation, async wrapping, parameter injection, rate limiting, and the once-guard."""

    orig_handler: "HandlerType"
    """Original handler function provided by the user."""

    async_handler: "AsyncHandlerType"
    """Async-wrapped handler function."""

    injector: ParameterInjector
    """Parameter injector for dependency injection."""

    kwargs: Mapping[str, Any] | None
    """Keyword arguments to pass to the handler."""

    error_handler: "BusErrorHandlerType | None"
    """Optional per-listener error handler."""

    app_error_handler_resolver: "Callable[[], BusErrorHandlerType | None] | None"
    """Closure that resolves the app-level error handler at dispatch time."""

    rate_limiter: RateLimiter | None
    """Rate limiter for debounce/throttle. None when no rate limiting is configured."""

    task_bucket: "TaskBucket"
    """TaskBucket used to spawn the cancellable child handler task for non-parallel modes."""

    guard: ExecutionModeGuard
    """Per-listener overlap state machine. Owns the running-task reference and live counters."""

    options: "ListenerOptions"
    """The listener's behavioral options. Dispatch reads ``once``, ``mode`` and the timeout fields from here."""

    handler_short_name: str
    """Short handler name, captured for the stall WARNING and debug logs."""

    backpressure_dropped: int = 0
    """Count of events dropped at the dispatch acquire gate due to DROP_NEWEST backpressure.
    Incremented only in BusService.dispatch — one writer, on the event loop, no await between
    the locked() check and the increment. Live-only; resets on restart, never persisted."""

    fired: bool = field(default=False, init=False)
    """Guard for once=True: set before the first invocation to prevent double-fire."""

    report_drop: DropReporter | None = field(default=None, init=False)
    """Near-miss reporter, bound by BusService at registration for app listeners, and unbound by
    Listener.cancel() so a removed listener records nothing more. None records nothing."""

    pending_done: "set[asyncio.Future[None]]" = field(default_factory=set, init=False)
    """Unresolved per-invocation completion futures for non-parallel modes.

    Each ``run_with_mode`` call (single/restart/queued) parks its outer dispatch task on a future
    that resolves when the handler actually runs (or is dropped/released). A queued trigger accepted
    into the deque has no live child until drain time, so its future would hang forever if the
    listener is released first. ``release_guard`` resolves every remaining future here so those outer
    dispatch tasks unwind and ``_dispatch_pending`` settles."""

    @classmethod
    def create(
        cls,
        task_bucket: "TaskBucket",
        handler: "HandlerType",
        kwargs: Mapping[str, Any] | None,
        options: "ListenerOptions",
        error_handler: "BusErrorHandlerType | None" = None,
        app_error_handler_resolver: "Callable[[], BusErrorHandlerType | None] | None" = None,
        clock: "Callable[[], float] | None" = None,
    ) -> "HandlerInvoker":
        """Construct a HandlerInvoker from a handler and options.

        Builds the async wrapper, injector, and rate limiter, and keeps a reference to ``options``.

        Args:
            task_bucket: TaskBucket for async adapter and rate limiter.
            handler: The user-supplied handler callable.
            kwargs: Optional keyword arguments to pass to the handler.
            options: Behavioral options (once, debounce, throttle).
            error_handler: Optional per-listener error handler.
            app_error_handler_resolver: Closure for app-level error handler resolution.
            clock: Zero-arg callable returning the current monotonic time, forwarded to the
                RateLimiter for deterministic throttle timing in tests. Defaults to
                ``time.monotonic`` when None (see RateLimiter).
        """
        handler_name = callable_name(handler)
        signature = get_typed_signature(handler)
        async_handler = make_async_handler(handler, task_bucket)
        injector = ParameterInjector(handler_name, signature)

        rate_limiter: RateLimiter | None = None
        if options.debounce is not None or options.throttle is not None:
            rate_limiter = RateLimiter(
                task_bucket=task_bucket,
                debounce=options.debounce,
                throttle=options.throttle,
                handler_name=handler_name,
                clock=clock,
            )

        return cls(
            orig_handler=handler,
            async_handler=async_handler,
            injector=injector,
            kwargs=kwargs,
            error_handler=error_handler,
            app_error_handler_resolver=app_error_handler_resolver,
            rate_limiter=rate_limiter,
            task_bucket=task_bucket,
            guard=ExecutionModeGuard(options.mode),
            options=options,
            handler_short_name=callable_short_name(handler),
        )

    def mark_fired(self) -> None:
        """Mark this once-invoker as having fired. Called by dispatch() and Listener.cancel()."""
        self.fired = True

    async def dispatch(
        self,
        delivery: "Delivery",
        executor: "CommandExecutor",
        config_resolver: Callable[[], float | None],
    ) -> None:
        """Run ``delivery`` through the once-guard, rate limiter, and overlap mode.

        Order: once-guard → rate limiter (whether to start) → mode guard (overlap of started
        invocations). The run itself is ``delivery.invoke(executor, config_resolver)`` (tracked telemetry).
        ``delivery`` is for this invoker's listener.

        Once-guard: if ``once=True`` and the invoker has already fired, returns immediately. Safe
        without a lock — no ``await`` between check-and-set.

        Mode guard: ``parallel`` runs ``invoke_fn`` as a child task in ``task_bucket`` (the owning
        ``Bus``'s) and awaits it through ``run_parallel``, so the owner's teardown cancels it; a sealed
        bucket means the owner is stopping, and the invocation is skipped. For
        ``single``/``restart``/``queued`` the guard receives a run-and-track callable that spawns a
        fresh child task through ``task_bucket``; this method then awaits that child so the outer
        dispatch task stays pending and remains counted by ``_dispatch_pending``. A ``restart``
        cancellation of the child surfaces as ``CancelledError`` inside the child only — it is swallowed
        here so the outer dispatch task does not crash.

        ``config_resolver`` returns the global handler timeout, the same one the run
        enforces. BusService owns it, so a listener's stall threshold follows that timeout however the
        listener was built.

        Every step that drops the delivery reports it with ``delivery.drop``.
        """
        if self.options.once:
            if self.fired:
                delivery.drop("once_spent")
                return
            self.mark_fired()

        if self.rate_limiter:
            await self.rate_limiter.call(delivery, lambda ran: self.run_with_mode(ran, executor, config_resolver))
        else:
            await self.run_with_mode(delivery, executor, config_resolver)

    async def run_with_mode(
        self,
        delivery: "Delivery",
        executor: "CommandExecutor",
        config_resolver: Callable[[], float | None],
    ) -> None:
        """Apply the overlap mode guard to a single started invocation, reporting a ``busy``/``queue_full`` drop."""

        def invoke_fn() -> Awaitable[None]:
            return delivery.invoke(executor, config_resolver)

        if self.options.mode is ExecutionMode.PARALLEL:
            try:
                await run_parallel(
                    spawn=lambda coro, *, name: self.task_bucket.spawn(coro, name=name),
                    invoke=invoke_fn,
                    spawn_name=f"bus:parallel_invocation:{self.handler_short_name}",
                )
            except TaskBucketSealedError:
                LOGGER.debug(
                    "Owner of handler '%s' is shutting down, so the invocation didn't run", self.handler_short_name
                )
            return

        outcome = await run_through_guard(
            guard=self.guard,
            spawn=lambda coro, *, name: self.task_bucket.spawn(coro, name=name),
            pending_done=self.pending_done,
            invoke=invoke_fn,
            warn=self.warn_stalled,
            spawn_name="bus:mode_invocation",
            resolve_timeout=lambda: self.effective_timeout(config_resolver),
        )
        if outcome is Outcome.SUPPRESSED:
            delivery.drop("busy")
        elif outcome is Outcome.DROPPED:
            delivery.drop("queue_full")

    def effective_timeout(self, config_resolver: Callable[[], float | None]) -> float | None:
        """Return the timeout enforced for one invocation, or ``None`` if it has none.

        The enforced timeout and the stall threshold both read this, so they can't disagree.
        """
        return resolve_effective_timeout(self.options.timeout, self.options.timeout_disabled, config_resolver)

    def warn_stalled(self, threshold: float, effective_timeout: float | None) -> None:
        """Emit the feature's stall WARNING: a non-parallel handler is still holding its guard."""
        LOGGER.warning(
            "Handler '%s' has held its %s execution-mode guard for over %s and is still running",
            self.handler_short_name,
            self.options.mode.value,
            describe_stall_threshold(threshold, effective_timeout),
        )

    def cancel(self) -> None:
        """Cancel any pending rate-limiter tasks."""
        if self.rate_limiter:
            self.rate_limiter.cancel()

    async def release_guard(self) -> None:
        """Release the execution-mode guard: cancel the in-flight task and drop queued factories.

        Called when a listener is cancelled or replaced so no event/listener/app references leak.
        ``parallel`` listeners hold no guard state, so this is a cheap no-op for them.

        Queued triggers still parked in the guard's deque never spawn a child once released, so
        their outer dispatch tasks are parked on ``done`` futures that nothing else will resolve.
        ``release_and_drain`` resolves every remaining one so those tasks unwind and
        ``_dispatch_pending`` settles.
        """
        await release_and_drain(self.guard, self.pending_done)

    async def invoke(self, event: "AnyEvent") -> None:
        """Invoke the handler with dependency injection."""
        kwargs = self.injector.inject_parameters(event, **(self.kwargs or {}))
        await self.async_handler(**kwargs)


def make_async_handler(fn: "HandlerType", task_bucket: "TaskBucket") -> "AsyncHandlerType":
    """Wrap a function to ensure it is always called as an async handler.

    If the function is already an async function, it will be called directly.
    If it is a regular function, it will be run in an executor to avoid blocking the event loop.

    Args:
        fn: The function to adapt.
        task_bucket: TaskBucket used to create the async adapter (runs sync handlers in executor).

    Returns:
        An async handler that wraps the original function.
    """
    return cast("AsyncHandlerType", task_bucket.make_async_adapter(fn))
