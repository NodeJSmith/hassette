"""Module-level structural-operation functions for Hassette resources.

These functions replace methods that previously lived on ``Resource``. They accept the resource
as their first argument instead of being bound methods, so structural operations are invoked as
``start_children_and_wait(resource)`` instead of ``resource.start_children_and_wait()``.
"""

import asyncio
import logging
import typing
from contextlib import suppress

from hassette.resources.lifecycle import create_lifecycle_task, handle_failed, start
from hassette.resources.shutdown_deadline import format_bound, shutdown_hook_bound, tighten_shutdown_deadline
from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult, incomplete, merge_outcomes
from hassette.types.enums import ResourceRole
from hassette.utils.service_utils import WaveOutcome, describe_children, describe_wave_causes, wait_for_wave

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
    """Start all children concurrently and block until each has initialized and is ready.

    All children are started simultaneously — ``depends_on`` ordering is
    not enforced. Use ``Hassette.run_forever()`` for wave-based startup.
    Like a startup wave there, the wait joins each child's initialization
    attempt, so a failed child fails the wait at once.

    Args:
        resource: The resource whose children should be started.
        timeout: Seconds to wait for initialization and readiness. ``None`` uses
            ``config.startup_timeout_seconds``.

    Raises:
        RuntimeError: If any child's initialization fails; chained from the
            first failure.
        TimeoutError: If any child is not ready within the timeout or
            if shutdown is requested during the wait.
    """
    if not resource.children:
        return

    attempts = {child: start(child) for child in resource.children}

    effective_timeout = timeout if timeout is not None else resource.hassette.config.lifecycle.startup_timeout_seconds
    result = await wait_for_wave(attempts, timeout=effective_timeout, shutdown_event=resource.hassette.shutdown_event)
    if result.outcome is WaveOutcome.OK:
        return
    child_statuses = describe_children(resource)
    if result.outcome is WaveOutcome.FAILED:
        causes = describe_wave_causes(result)
        raise RuntimeError(f"Children of {resource.class_name} failed to initialize: {causes}") from result.errors[0]
    if result.outcome is WaveOutcome.SHUTDOWN:
        reason = f"shutdown during wait after {effective_timeout}s; child statuses: {child_statuses}"
    else:
        reason = f"timed out after {effective_timeout}s; child statuses: {child_statuses}"
    raise TimeoutError(f"Children of {resource.class_name} did not become ready: {reason}")


def register_task_bucket_factory(factory: "Callable[[Hassette, Resource], TaskBucket]") -> None:
    """Register the factory used to create a default TaskBucket for each Resource.

    Called once by hassette.task_bucket at module import time so that Resource.__init__
    never needs to import TaskBucket directly.
    """
    from hassette.resources.base import (  # noqa: PLC0415 - break circular import, base.py imports this module
        Resource,  # house-lint: ignore[HSL002] - break circular import, base.py imports this module
    )

    Resource._default_task_bucket_factory = factory


class ShutdownHookTimedOutError(TimeoutError):
    """A shutdown hook outlived its bound and was cancelled.

    Raised by ``run_hooks()`` in place of the bare ``TimeoutError`` from its own bound, so a hook that
    timed out is told apart from one that raised ``TimeoutError`` itself.
    """


async def run_hooks(
    resource: "Resource",
    hooks: list[typing.Callable[[], typing.Awaitable[None]]],
    *,
    continue_on_error: bool = False,
    shutdown_bound: bool = False,
) -> "tuple[Exception, ...]":
    """Execute lifecycle hooks with error handling.

    Args:
        resource: The resource the hooks belong to.
        hooks: List of async callables to execute in order.
        continue_on_error: If False (initialize), re-raise on Exception.
            If True (shutdown), log and continue to next hook.
        shutdown_bound: If True, run each hook inline under a cancel-and-wait bound of
            ``shutdown_hook_bound(resource)``: the per-hook ``shutdown_timeout_seconds`` clamped to
            what is left of the operation's deadline. A hook that outlives it is cancelled and
            surfaces as ``ShutdownHookTimedOutError``, handled like any other exception below. Only
            meaningful for shutdown hooks; initialize hooks pass False (they run under a separate
            startup timeout).

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
            if shutdown_bound:
                await run_bounded_hook(resource, method)
            else:
                await method()
        except asyncio.CancelledError as exc:
            if continue_on_error:
                resource.lifecycle_logger.warning("Shutdown hook was cancelled, forcing cleanup")
            with suppress(Exception):
                await handle_failed(resource, exc)
            raise
        except Exception as exc:
            if continue_on_error:
                resource.lifecycle_logger.error("Error during shutdown: %s %s", type(exc).__name__, exc)
                with suppress(Exception):
                    await handle_failed(resource, exc)
                handled.append(exc)
            else:
                # continue_on_error=False means this is an initialization hook (the only caller
                # of that mode -- see Resource._initialize_body() and Service._initialize_body()).
                # App-role resources have an outer, decision-owning catch for this same exception
                # -- AppLifecycleService.initialize_instances()'s `await inst.initialize()` --
                # that already logs it at ERROR, so demote here to avoid a second stacked ERROR
                # traceback for the exact same failure (see #1826). Every other resource has no
                # such outer logger and keeps ERROR.
                log_level = logging.DEBUG if resource.role == ResourceRole.APP else logging.ERROR
                with suppress(Exception):
                    await handle_failed(resource, exc, log_level=log_level)
                raise
    return tuple(handled)


async def run_bounded_hook(resource: "Resource", method: typing.Callable[[], typing.Awaitable[None]]) -> None:
    """Run one shutdown hook inline under ``shutdown_hook_bound(resource)``.

    Raises ``ShutdownHookTimedOutError`` when the bound expires, including when the hook catches the
    cancellation and returns. A hook that swallows the cancellation holds this await until it returns;
    only the operation's owner can walk away from it.
    """
    bound = shutdown_hook_bound(resource)
    name = getattr(method, "__name__", repr(method))
    resource.lifecycle_logger.debug(
        "%s: entering hook %s with %s bound",
        resource.unique_name,
        name,
        format_bound(bound),
    )
    scope = asyncio.timeout(bound)
    timeout_message = f"shutdown hook {name} timed out after {format_bound(bound)}"
    try:
        async with scope:
            await method()
    except TimeoutError as exc:
        if scope.expired():
            raise ShutdownHookTimedOutError(timeout_message) from exc
        raise
    # a hook that caught its cancellation and returned leaves the block without a TimeoutError
    if scope.expired():
        raise ShutdownHookTimedOutError(timeout_message)


def shutdown_hook_outcome(resource_name: str, hook_errors: "tuple[Exception, ...]") -> ShutdownOutcome:
    """The outcome of the shutdown hooks ``run_hooks()`` handled for ``resource_name``.

    A hook cut off by its bound is ``TIMED_OUT``; one that raised is ``FAILED``. When both happened, the
    timed-out hook ranks worse and gives the reason.
    """
    timed_out = [exc for exc in hook_errors if isinstance(exc, ShutdownHookTimedOutError)]
    if timed_out:
        return ShutdownOutcome(ShutdownResult.TIMED_OUT, reason=f"{resource_name}: {timed_out[0]}")
    if hook_errors:
        return ShutdownOutcome(
            ShutdownResult.FAILED, reason=f"{resource_name}: a shutdown hook raised {type(hook_errors[0]).__name__}"
        )
    return ShutdownOutcome()


def ordered_children_for_shutdown(resource: "Resource") -> "list[Resource]":
    """Return children in shutdown order (reverse insertion)."""
    return list(reversed(resource.children))


async def shutdown_batch(resource: "Resource", batch: "list[Resource]", *, deadline: float | None) -> ShutdownOutcome:
    """Shut down one batch of children concurrently and merge their outcomes.

    Shared by ``Resource._shutdown_children()`` (one batch: all children) and the root's exit stages
    (one batch per dependency wave). Each caller merges across its own batches.

    The batch has no bound of its own: each child gets ``deadline`` (tightening any it already has;
    normally the caller's own shutdown deadline), and only the operation's owner walks away when that
    deadline passes.

    - A child whose ``shutdown()`` call itself raises makes the batch ``INCOMPLETE``. The coordinator stores
      an outcome on the child before re-raising (see ``coordinate_shutdown()``'s ``except Exception`` branch
      in ``lifecycle.py``), so that outcome is merged first and its reason, naming the step, wins.
    - A child that returns merges its own outcome in; one that is restart-unsafe makes the batch unsafe
      through the merge, with no evidence of its own.

    Outcomes merge in batch order, so among several children at the worst result the first one's reason
    is kept.
    """
    for child in batch:
        tighten_shutdown_deadline(child, deadline)
    # create_lifecycle_task(), not asyncio.gather()'s own implicit task creation -- resource's own
    # TaskBucket is already sealed here; see create_lifecycle_task()'s docstring for why that matters.
    child_tasks = [
        create_lifecycle_task(child.shutdown(), name=f"resource:shutdown_propagate:{child.unique_name}")
        for child in batch
    ]
    results = await asyncio.gather(*child_tasks, return_exceptions=True)

    outcomes: list[ShutdownOutcome] = []
    for child, result in zip(batch, results, strict=True):
        if isinstance(result, BaseException):
            resource.lifecycle_logger.error("Child %s shutdown failed: %s", child.unique_name, result)
            if (stored := child.shutdown_outcome) is not None:
                outcomes.append(stored)
            outcomes.append(incomplete(f"{child.unique_name}'s shutdown raised {type(result).__name__}"))
            continue
        outcomes.append(result)
    return merge_outcomes(*outcomes)
