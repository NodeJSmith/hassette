"""Module-level structural-operation functions for Hassette resources.

These functions replace methods that previously lived on ``Resource``. They accept the resource
as their first argument instead of being bound methods, so structural operations are invoked as
``restart(resource)`` instead of ``resource.restart()``.
"""

import asyncio
import typing
from contextlib import suppress

from hassette.resources.lifecycle import handle_failed, start
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
    """Restart the instance by shutting it down and re-initializing it."""
    resource.logger.debug("Restarting '%s' %s", resource.class_name, resource.role)
    await resource.shutdown()
    await resource.initialize()


def register_task_bucket_factory(factory: "Callable[[Hassette, Resource], TaskBucket]") -> None:
    """Register the factory used to create a default TaskBucket for each Resource.

    Called once by hassette.task_bucket at module import time so that Resource.__init__
    never needs to import TaskBucket directly.
    """
    from hassette.resources.base import Resource  # lazy-import: break circular import — base.py imports this module

    Resource._default_task_bucket_factory = factory


async def run_hooks(
    resource: "Resource",
    hooks: list[typing.Callable[[], typing.Awaitable[None]]],
    *,
    continue_on_error: bool = False,
) -> None:
    """Execute lifecycle hooks with error handling.

    Args:
        resource: The resource the hooks belong to.
        hooks: List of async callables to execute in order.
        continue_on_error: If False (initialize), re-raise on Exception.
            If True (shutdown), log and continue to next hook.
    """
    for method in hooks:
        try:
            await method()
        except asyncio.CancelledError:
            if continue_on_error:
                resource.logger.warning("Shutdown hook was cancelled, forcing cleanup")
            with suppress(Exception):
                await handle_failed(resource, asyncio.CancelledError())
            raise
        except Exception as exc:
            if continue_on_error:
                resource.logger.error("Error during shutdown: %s %s", type(exc).__name__, exc)
                with suppress(Exception):
                    await handle_failed(resource, exc)
            else:
                with suppress(Exception):
                    await handle_failed(resource, exc)
                raise


def ordered_children_for_shutdown(resource: "Resource") -> "list[Resource]":
    """Return children in shutdown order (reverse insertion)."""
    return list(reversed(resource.children))
