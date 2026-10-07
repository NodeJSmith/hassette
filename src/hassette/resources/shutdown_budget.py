"""Shutdown time-budget allocation for Hassette resources.

Pure arithmetic over a frozen ``ShutdownBudget`` plus the running loop's clock: the budget
constants, ``compute_shutdown_budget()``, and the "seconds remaining" readers that shutdown
stages consult. Nothing here transitions status, creates tasks, or emits events — that lives
in ``hassette.resources.lifecycle``.
"""

import asyncio
import dataclasses
import typing

from hassette.resources.mixins import _LifecycleHostP

if typing.TYPE_CHECKING:
    from hassette.resources.mixins import LifecycleMixin


COORDINATOR_MARGIN_FRACTION = 0.1
"""Fraction of the total shutdown timeout reserved as a gap between the body's own
deadline and the coordinator's outer ``asyncio.wait()`` bound. Guarantees the body
finishes (and its result is observed) before the coordinator abandons it — replacing
the former ``ROOT_SHUTDOWN_BODY_TIMEOUT_FRACTION`` and the ``HOOK_BUDGET_FRACTION``
margin that each addressed the same race from different directions."""

TASK_CANCEL_SECONDS = 1.0
"""Fixed budget for ``_run_task_bucket_shutdown_stage()``. Replaces the former
``CANCEL_BUDGET_FRACTION`` (20% of shrinking remainder)."""

CLEANUP_SECONDS = 0.5
"""Fixed budget for ``cleanup()``. Replaces the former ``CLEANUP_BUDGET_FRACTION``
(50% of shrinking remainder)."""

CHILDREN_FLOOR_SECONDS = 1.0
"""Minimum guaranteed budget for ``_shutdown_children()``. Unchanged from the former
``CHILDREN_SHUTDOWN_BUDGET_FLOOR_SECONDS`` — the floor concept is preserved, but now
children also benefit from any slack the hooks pool didn't use."""

CHILDREN_WAVE_FLOOR_SECONDS = 0.1
"""Minimum guaranteed budget per wave when ``Hassette._shutdown_children()`` divides the
remaining body time across multiple dependency-ordered waves (see
``children_budget_remaining()``'s ``waves_left`` parameter). Applies to waves 2..N; the
final wave (``waves_left=1``) falls back to ``CHILDREN_FLOOR_SECONDS`` via the same default
path ``Resource._shutdown_children()`` uses, giving the most-foundational resources (DB,
sync executor) a bigger grace window. Deliberately much smaller than
``CHILDREN_FLOOR_SECONDS`` — that floor is sized for a single call; applied per-wave across
every wave in a multi-wave shutdown, it can blow past ``COORDINATOR_MARGIN_FRACTION``'s
margin on its own. Worst case with W waves: ``(W-1) * 0.1 + 1.0``. See #1809."""

HOOKS_FLOOR_SECONDS = 0.5
"""Minimum guaranteed budget for hooks/serve-wait/initializer observation, even when the
total timeout is too small to fit the full tail reservation. Without this floor, any
``resource_shutdown_timeout_seconds`` at or below ``(TASK_CANCEL_SECONDS + CLEANUP_SECONDS +
CHILDREN_FLOOR_SECONDS + HOOKS_FLOOR_SECONDS) / (1 - COORDINATOR_MARGIN_FRACTION)`` (~3.33s
with defaults) would compute a zero-length hooks pool, so ``on_shutdown()`` (and every other
shutdown hook) would be cancelled at its first suspension point regardless of how little work
it does. ``LifecycleConfig`` places no lower bound on ``resource_shutdown_timeout_seconds``,
so this floor is reachable in practice."""


@dataclasses.dataclass(frozen=True)
class ShutdownBudget:
    """Pre-computed budget allocation for a single shutdown attempt.

    Computed once by ``compute_shutdown_budget()`` at the top of
    ``_run_shutdown_coordinator()`` and stored on the resource. Each stage reads its
    own field directly — no stage derives its budget from "what's left of a shrinking
    remainder."

    The ``hooks_pool_deadline`` is the one place where sequential "remaining" logic
    still applies: hooks run sequentially and each gets whatever remains of the pool.
    The pool itself is a fixed allocation from the total, so compounding within it
    cannot starve the mandatory tail (task cancel, cleanup, children).
    """

    hooks_pool_deadline: float
    """Absolute loop time by which all hooks, serve-wait, and initializer observation
    must finish. Each consumer reads ``max(0, hooks_pool_deadline - loop.time())``."""

    task_cancel_seconds: float
    """Fixed duration for ``_run_task_bucket_shutdown_stage()``."""

    cleanup_seconds: float
    """Fixed duration for ``cleanup()``."""

    children_floor_seconds: float
    """Minimum guaranteed duration for ``_shutdown_children()``."""

    body_deadline: float
    """Absolute loop time by which the entire ``_shutdown_body()`` must finish.
    Children get the remaining time after task-cancel and cleanup have run — so
    early-finishing hooks pass their slack to children naturally. For single-batch
    callers this is floored at ``children_floor_seconds``; for multi-wave callers
    the remaining time is divided across waves (see ``children_budget_remaining()``).
    Also the deadline the root's own ``Hassette._shutdown_body()`` bounds itself with
    internally, via its own ``asyncio.timeout()`` -- deliberately *tighter* than
    ``total_deadline`` below so its graceful ``TOTAL_TIMEOUT``/stream-closing fallback
    gets a chance to run before the coordinator's cruder outer force-cancel does."""

    total_deadline: float
    """Absolute loop time by which the coordinator's own outer wait on the whole shutdown
    body task gives up -- ``now + total_seconds`` from ``compute_shutdown_budget()``,
    *not* reduced by ``COORDINATOR_MARGIN_FRACTION`` the way ``body_deadline`` is. This is
    what ``_run_shutdown_coordinator()``'s outer ``asyncio.wait()`` bound reads (via
    ``total_deadline_remaining()``): using ``body_deadline`` there instead would collapse
    the margin gap this budget exists to create, racing the coordinator's blunt cancel
    against the body's own graceful internal deadline instead of only backstopping it.
    Using the fixed ``total_seconds`` again (rather than measuring afresh from whenever the
    outer wait happens to start) is what keeps a shutdown attempt whose
    initializer-observation phase already spent real time from this same budget bounded to
    the *original* configured timeout instead of that time plus a full timeout again."""


def compute_shutdown_budget(
    total_seconds: float, now: float, task_cancel_ceiling: float = TASK_CANCEL_SECONDS
) -> ShutdownBudget:
    """Allocate shutdown time across stages up front, from the total.

    Called once per shutdown attempt. The allocation is:

    1. ``COORDINATOR_MARGIN_FRACTION`` of total reserved for the coordinator/body gap.
    2. ``task_cancel_ceiling`` (normally ``lifecycle.task_cancellation_timeout_seconds``)
       + ``CLEANUP_SECONDS`` + ``CHILDREN_FLOOR_SECONDS`` reserved for the mandatory tail.
    3. Everything else becomes the hooks pool (hooks, serve-wait, initializer observation).

    If the total is too small to fit the full tail reservation plus ``HOOKS_FLOOR_SECONDS``,
    every stage — hooks included — scales down proportionally instead of the hooks pool
    dropping to 0. A resource with a configured timeout too small to fit any of this ends up
    with a proportionally tiny but still nonzero share for every stage.
    """
    tail_reservation = task_cancel_ceiling + CLEANUP_SECONDS + CHILDREN_FLOOR_SECONDS
    full_reservation = tail_reservation + HOOKS_FLOOR_SECONDS

    margin = total_seconds * COORDINATOR_MARGIN_FRACTION
    body_budget = total_seconds - margin

    if body_budget >= full_reservation:
        hooks_pool = body_budget - tail_reservation
        task_cancel = task_cancel_ceiling
        cleanup = CLEANUP_SECONDS
        children_floor = CHILDREN_FLOOR_SECONDS
    else:
        scale = body_budget / full_reservation if full_reservation > 0 else 0.0
        hooks_pool = HOOKS_FLOOR_SECONDS * scale
        task_cancel = task_cancel_ceiling * scale
        cleanup = CLEANUP_SECONDS * scale
        children_floor = CHILDREN_FLOOR_SECONDS * scale

    return ShutdownBudget(
        hooks_pool_deadline=now + hooks_pool,
        task_cancel_seconds=task_cancel,
        cleanup_seconds=cleanup,
        children_floor_seconds=children_floor,
        body_deadline=now + body_budget,
        total_deadline=now + total_seconds,
    )


def _current_shutdown_budget(resource: _LifecycleHostP) -> ShutdownBudget | None:
    """The resource's ``ShutdownBudget`` for the current shutdown attempt, or ``None`` if the
    coordinator has not set one yet (should not happen in normal operation).
    """
    return typing.cast("LifecycleMixin", resource)._shutdown_budget


def _shutdown_timeout_fallback(resource: _LifecycleHostP) -> float:
    """Configured ``resource_shutdown_timeout_seconds``, used when no ``ShutdownBudget`` has been
    set yet.
    """
    return typing.cast("LifecycleMixin", resource).hassette.config.lifecycle.resource_shutdown_timeout_seconds


def hooks_pool_remaining(resource: _LifecycleHostP) -> float:
    """Seconds left in the hooks pool for the current shutdown attempt.

    Used by ``run_hooks()`` (each hook), the serve-task wait, and
    ``_observe_active_initializer()`` — everything that shares the discretionary pool. A hook
    body may also read it to sub-divide its own share, as ``DatabaseService.on_shutdown()`` does
    to bound its write-queue drain; the list above is the framework's own consumers, not a
    closed set.
    Returns ``resource_shutdown_timeout_seconds`` when no budget has been set yet (the
    coordinator always sets one before any consumer runs; this is a defensive fallback,
    not the normal path), and 0 only once the pool itself is exhausted.
    """
    budget = _current_shutdown_budget(resource)
    if budget is None:
        return _shutdown_timeout_fallback(resource)
    return max(0.0, budget.hooks_pool_deadline - asyncio.get_running_loop().time())


def children_budget_remaining(resource: _LifecycleHostP, *, waves_left: int = 1) -> float:
    """Seconds available for the next ``_shutdown_children()`` wave.

    Children run last and benefit from any slack the earlier stages left behind. Returns at
    least ``children_floor_seconds`` when ``waves_left=1`` (the default — matches
    ``Resource._shutdown_children()``'s single ``shutdown_batch()`` call, and also the final
    wave of a multi-wave shutdown) even when the body is over budget.

    When more than one wave shares this budget (``Hassette._shutdown_children()``'s
    dependency-ordered waves), pass the actual remaining wave count via ``waves_left`` so the
    remaining time is divided across waves instead of each wave independently claiming a fresh
    floor — otherwise W hung waves could overrun ``body_deadline`` by up to W * the floor,
    exceeding the coordinator's own margin. The final wave (``waves_left=1``) naturally falls
    back to the larger ``children_floor_seconds`` floor, giving the most-foundational
    resources a bigger grace window. See #1809.
    """
    budget = _current_shutdown_budget(resource)
    if budget is None:
        return _shutdown_timeout_fallback(resource)
    remaining = budget.body_deadline - asyncio.get_running_loop().time()
    if waves_left <= 1:
        return max(budget.children_floor_seconds, remaining)
    return max(CHILDREN_WAVE_FLOOR_SECONDS, remaining / waves_left)


def total_deadline_remaining(resource: _LifecycleHostP) -> float:
    """Seconds left until the coordinator's own outer wait on the shutdown body gives up.

    Used by ``_run_shutdown_coordinator()``'s outer ``asyncio.wait()`` bound on the body
    task. Deliberately reads ``total_deadline`` (the *un*-margin-reduced deadline), not
    ``body_deadline`` -- the outer wait is meant to be the coordinator's last-resort
    backstop, strictly looser than the body's own internal deadline (e.g. the root's
    ``Hassette._shutdown_body()`` bounds itself with ``body_deadline``, deliberately
    tighter, so its graceful ``TOTAL_TIMEOUT`` fallback gets a chance to run first). Also
    what keeps a shutdown attempt whose initializer-observation phase already spent real
    time from the same budget bounded to the original configured timeout, rather than that
    time plus a full timeout again. Returns ``resource_shutdown_timeout_seconds`` when no
    budget has been set yet, and 0 once the deadline has already passed.
    """
    budget = _current_shutdown_budget(resource)
    if budget is None:
        return _shutdown_timeout_fallback(resource)
    return max(0.0, budget.total_deadline - asyncio.get_running_loop().time())


def elapsed_since(start: float) -> float:
    """Seconds elapsed since ``start``, an ``asyncio.get_running_loop().time()`` snapshot.

    Shared by every shutdown-stage timing log (waves, task-bucket cancel, cleanup,
    child propagation, initializer observation, shutdown-body wait, and the coordinator
    itself) so each stage measures its own span with one line instead of repeating the
    subtraction.
    """
    return asyncio.get_running_loop().time() - start
