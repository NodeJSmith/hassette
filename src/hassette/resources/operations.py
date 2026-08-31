"""Module-level structural-operation functions for Hassette resources.

These functions replace methods that previously lived on ``Resource``. They accept the resource
as their first argument instead of being bound methods, so structural operations are invoked as
``restart(resource)`` instead of ``resource.restart()``.
"""

import asyncio
import typing
from contextlib import suppress

from hassette.exceptions import RestartRefusedError
from hassette.resources.lifecycle import (
    create_lifecycle_task,
    handle_failed,
    hooks_pool_remaining,
    reject_lifecycle_reentry,
    start,
)
from hassette.resources.teardown import TeardownCause, TeardownReport, add_teardown_evidence, merge_teardown_reports
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


class ShutdownBatchResult(typing.NamedTuple):
    """One batch's contribution to a caller's aggregated ``TeardownReport``.

    Returned by ``shutdown_batch()``; the caller extends its own running lists with these
    three fields across every batch it runs, then merges once at the end (see
    ``Resource._shutdown_children()`` and ``Hassette._shutdown_children()``).
    """

    reports: list[TeardownReport]
    causes: list[TeardownCause]
    affected: list[str]


async def shutdown_batch(resource: "Resource", batch: "list[Resource]", timeout: float) -> ShutdownBatchResult:
    """Shut down one batch of children concurrently and classify the results.

    Shared by ``Resource._shutdown_children()`` (one batch: all children) and
    ``Hassette._shutdown_children()`` (one batch per dependency wave, called once per wave).
    Each caller owns its own aggregation across batches -- this function only classifies a
    single batch and returns the pieces:

    - A child whose ``shutdown()`` call itself raises unexpectedly adds ``CHILD_SHUTDOWN_FAILED``
      and the child's identity to the affected list. The coordinator stores evidence (e.g.
      ``COORDINATOR_FAILED``) on the child's own report before re-raising -- see
      ``coordinate_shutdown()``'s ``except Exception`` branch in ``lifecycle.py`` -- so that
      report is merged in when present, instead of being replaced by only the generic cause.
    - A child that returns without raising, but whose own report has ``is_restart_safe`` ``False``,
      adds ``CHILD_RESTART_UNSAFE`` and the child's identity -- the child's own causes and
      details are merged in first.
    - A batch that exceeds ``timeout`` adds ``CHILD_SHUTDOWN_TIMED_OUT`` and force-terminates only
      the children still unfinished at that point; a child that already completed keeps its own
      (possibly restart-safe) report unchanged.
    """
    child_reports: list[TeardownReport] = []
    causes: list[TeardownCause] = []
    affected: list[str] = []

    try:
        async with asyncio.timeout(timeout):
            # create_lifecycle_task(), not asyncio.gather()'s own implicit task creation --
            # resource's own TaskBucket is already sealed here; see create_lifecycle_task()'s
            # docstring for why that matters.
            child_tasks = [
                create_lifecycle_task(child.shutdown(), name=f"resource:shutdown_propagate:{child.unique_name}")
                for child in batch
            ]
            results = await asyncio.gather(*child_tasks, return_exceptions=True)
    except TimeoutError:
        resource.logger.error(
            "Timed out waiting for children to shut down after %ss: [%s]",
            timeout,
            ", ".join(child.class_name for child in batch),
        )
        causes.append(TeardownCause.CHILD_SHUTDOWN_TIMED_OUT)
        for child in batch:
            if not child.shutdown_completed:
                child._force_terminal()
                affected.append(child.unique_name)
            child_report = child.teardown_report
            if child_report is not None:
                child_reports.append(child_report)
        return ShutdownBatchResult(child_reports, causes, affected)

    for child, result in zip(batch, results, strict=True):
        if isinstance(result, BaseException):
            resource.logger.error("Child %s shutdown failed: %s", child.unique_name, result)
            causes.append(TeardownCause.CHILD_SHUTDOWN_FAILED)
            affected.append(child.unique_name)
            child_report = child.teardown_report
            if child_report is not None:
                child_reports.append(child_report)
            continue
        child_reports.append(result)
        if not result.is_restart_safe:
            causes.append(TeardownCause.CHILD_RESTART_UNSAFE)
            affected.append(child.unique_name)

    return ShutdownBatchResult(child_reports, causes, affected)


def finalize_shutdown_report(
    reports: list[TeardownReport], causes: list[TeardownCause], affected: list[str]
) -> TeardownReport:
    """Merge accumulated batch reports and stamp on the accumulated causes/affected evidence.

    Shared tail of ``Resource._shutdown_children()`` and ``Hassette._shutdown_children()``: both
    accumulate ``ShutdownBatchResult`` fields across one or more ``shutdown_batch()`` calls, then
    call this once to produce the single aggregated ``TeardownReport`` they return.
    """
    merged = merge_teardown_reports(*reports) if reports else TeardownReport()
    return add_teardown_evidence(merged, causes=tuple(causes), affected_resources=tuple(affected))
