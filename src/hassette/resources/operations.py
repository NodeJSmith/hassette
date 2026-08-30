"""Module-level structural-operation functions for Hassette resources.

These functions replace methods that previously lived on ``Resource``. They accept the resource
as their first argument instead of being bound methods, so structural operations are invoked as
``restart(resource)`` instead of ``resource.restart()``.
"""

import asyncio
import typing
from contextlib import suppress

from hassette.exceptions import RestartRefusedError
from hassette.resources.lifecycle import handle_failed, hooks_pool_remaining, reject_lifecycle_reentry, start
from hassette.utils.service_utils import wait_for_ready

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import Hassette, TaskBucket
    from hassette.resources.base import Resource


# NOTE: `Resource` is imported only under TYPE_CHECKING above. `hassette.resources.base` imports
# `run_hooks` and `ordered_children_for_shutdown` from this module at module level, so a top-level
# `from hassette.resources.base import Resource` here would be a genuine circular import. Every
# function below only touches `Resource` for type annotations (duck-typed at runtime) except
# `register_task_bucket_factory`, which imports `Resource` locally at call time — by then both
# modules have finished loading, so the deferred import is safe.


async def start_children_and_wait(resource: "Resource", timeout: float | None = None) -> None:
    """Start all children concurrently and block until they are ready.

    All children are started simultaneously — ``depends_on`` ordering is
    not enforced. Use ``Hassette.run_forever()`` for wave-based startup.

    Args:
        resource: The resource whose children should be started.
        timeout: Seconds to wait for readiness. ``None`` uses
            ``config.startup_timeout_seconds``.

    Raises:
        TimeoutError: If any child is not ready within the timeout or
            if shutdown is requested during the wait.
    """
    if not resource.children:
        return

    for child in resource.children:
        start(child)

    effective_timeout = timeout if timeout is not None else resource.hassette.config.lifecycle.startup_timeout_seconds
    ready = await wait_for_ready(
        resource.children, timeout=effective_timeout, shutdown_event=resource.hassette.shutdown_event
    )
    if not ready:
        child_statuses = ", ".join(f"{c.class_name}({c.status.value})" for c in resource.children)
        if resource.hassette.shutdown_event.is_set():
            reason = f"shutdown during wait after {effective_timeout}s; child statuses: {child_statuses}"
        else:
            reason = f"timed out after {effective_timeout}s; child statuses: {child_statuses}"
        raise TimeoutError(f"Children of {resource.class_name} did not become ready: {reason}")


async def restart(resource: "Resource") -> None:
    """Restart the instance by shutting it down and re-initializing it.

    Requires the shutdown attempt to prove ``is_restart_safe`` before initializing — a report
    with ``is_restart_safe`` ``False`` raises ``RestartRefusedError`` without starting a new
    attempt. The direct-``initialize()`` refusal check remains the authoritative gate (callers
    can bypass ``restart()`` entirely); this check exists so ``restart()`` fails fast with a
    clear message instead of relying on ``initialize()`` to raise the same error one call later.
    """
    reject_lifecycle_reentry(resource, "restart")
    resource.logger.debug("Restarting '%s' %s", resource.class_name, resource.role)
    report = await resource.shutdown()
    if not report.is_restart_safe:
        raise RestartRefusedError(resource.unique_name, report)
    await resource.initialize()


def register_task_bucket_factory(factory: "Callable[[Hassette, Resource], TaskBucket]") -> None:
    """Register the factory used to create a default TaskBucket for each Resource.

    Called once by hassette.task_bucket at module import time so that Resource.__init__
    never needs to import TaskBucket directly.
    """
    from hassette.resources.base import (
        Resource,  # house-lint: ignore[HSL002] - break circular import, base.py imports this module
    )

    Resource._default_task_bucket_factory = factory


async def run_hooks(
    resource: "Resource",
    hooks: list[typing.Callable[[], typing.Awaitable[None]]],
    *,
    continue_on_error: bool = False,
    bound_to_shutdown_budget: bool = False,
) -> "tuple[Exception, ...]":
    """Execute lifecycle hooks with error handling.

    Args:
        resource: The resource the hooks belong to.
        hooks: List of async callables to execute in order.
        continue_on_error: If False (initialize), re-raise on Exception.
            If True (shutdown), log and continue to next hook.
        bound_to_shutdown_budget: If True, wrap each hook call in
            ``asyncio.timeout(hooks_pool_remaining(resource))`` so a hook — framework or
            user-authored (e.g. ``App.on_shutdown()``) — cannot hang past the hooks pool
            deadline. Only meaningful for shutdown hooks; initialize hooks pass False
            (they run under a separate startup timeout, not this shutdown budget). A hook that
            times out surfaces as a plain ``TimeoutError``, handled the same as any other
            exception below.

    Returns:
        An immutable tuple of the exceptions handled while continuing past failed
        hooks (``continue_on_error=True``), in the order they occurred. Always empty
        when ``continue_on_error=False`` — that mode re-raises on the first failure
        instead of collecting it.

    Raises:
        Exception: The first hook failure, when ``continue_on_error=False``.
        asyncio.CancelledError: Always re-raised regardless of ``continue_on_error`` —
            cancellation is never treated as a handled, continuable failure.
    """
    handled: list[Exception] = []
    for method in hooks:
        try:
            if bound_to_shutdown_budget:
                budget = hooks_pool_remaining(resource)
                resource.logger.debug(
                    "%s: entering hook %s with %.2fs of hooks pool remaining",
                    resource.unique_name,
                    getattr(method, "__name__", repr(method)),
                    budget,
                )
                async with asyncio.timeout(budget):
                    await method()
            else:
                await method()
        except asyncio.CancelledError as exc:
            if continue_on_error:
                resource.logger.warning("Shutdown hook was cancelled, forcing cleanup")
            with suppress(Exception):
                await handle_failed(resource, exc)
            raise
        except Exception as exc:
            if continue_on_error:
                resource.logger.error("Error during shutdown: %s %s", type(exc).__name__, exc)
                with suppress(Exception):
                    await handle_failed(resource, exc)
                handled.append(exc)
            else:
                with suppress(Exception):
                    await handle_failed(resource, exc)
                raise
    return tuple(handled)


def ordered_children_for_shutdown(resource: "Resource") -> "list[Resource]":
    """Return children in shutdown order (reverse insertion)."""
    return list(reversed(resource.children))
