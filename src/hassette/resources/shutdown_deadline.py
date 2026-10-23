"""Shutdown deadlines for Hassette resources.

A shutdown operation's owner sets one absolute deadline on the resource's shutdown attempt: the root
for each exit stage, ``AppLifecycleService`` for a runtime instance operation. Interior nodes
(coordinators, child batches) wait without a bound of their own and pass the deadline down; only the
leaves bound themselves, each by its own cap clamped to what is left of the deadline. Only the
owner walks away when the deadline passes.

Pure arithmetic over the attempt's deadline and the running loop's clock. Nothing here transitions
status, creates tasks, or emits events — that lives in ``hassette.resources.lifecycle``.
"""

import asyncio
import typing

from hassette.resources.mixins import _LifecycleHostP

if typing.TYPE_CHECKING:
    from hassette.resources.mixins import LifecycleMixin


CLEANUP_SECONDS = 0.5
"""Fixed cap on ``cleanup()``, clamped to the attempt's deadline."""


def shutdown_deadline_remaining(resource: _LifecycleHostP) -> float | None:
    """Seconds left until the resource's shutdown deadline, or ``None`` when no owner set one.

    Never negative: a passed deadline reads as 0.
    """
    deadline = typing.cast("LifecycleMixin", resource)._shutdown_deadline
    if deadline is None:
        return None
    return max(0.0, deadline - asyncio.get_running_loop().time())


@typing.overload
def clamp_to_shutdown_deadline(resource: _LifecycleHostP, cap: float) -> float: ...


@typing.overload
def clamp_to_shutdown_deadline(resource: _LifecycleHostP, cap: None) -> float | None: ...


def clamp_to_shutdown_deadline(resource: _LifecycleHostP, cap: float | None) -> float | None:
    """A leaf's bound: ``cap`` shortened to what is left of the deadline.

    ``None`` means unbounded: there is no cap and no deadline.
    """
    remaining = shutdown_deadline_remaining(resource)
    if cap is None:
        return remaining
    if remaining is None:
        return cap
    return min(cap, remaining)


def shutdown_hook_bound(resource: _LifecycleHostP) -> float | None:
    """Bound for one shutdown hook, the serve-task wait, or the initializer observation.

    ``shutdown_timeout_seconds`` clamped to the deadline, except for a resource whose
    ``shutdown_hook_timeout_applies`` is ``False`` (the foundation services, whose framework steps carry
    fixed caps of their own): those are bounded by the deadline alone.
    """
    host = typing.cast("LifecycleMixin", resource)
    cap = host.hassette.config.lifecycle.shutdown_timeout_seconds if host.shutdown_hook_timeout_applies else None
    return clamp_to_shutdown_deadline(resource, cap)


def tighten_shutdown_deadline(resource: _LifecycleHostP, deadline: float | None) -> None:
    """Shorten the resource's shutdown deadline to ``deadline``; never extends it.

    Called by an operation's owner before it starts the shutdown, and by a parent passing its own
    deadline to a child. A caller joining an attempt already in flight can only tighten it.
    """
    if deadline is None:
        return
    host = typing.cast("LifecycleMixin", resource)
    current = host._shutdown_deadline
    host._shutdown_deadline = deadline if current is None else min(current, deadline)


def deadline_in(seconds: float) -> float:
    """The absolute loop time ``seconds`` from now, for use as a shutdown deadline."""
    return asyncio.get_running_loop().time() + seconds


def elapsed_since(start: float) -> float:
    """Seconds elapsed since ``start``, an ``asyncio.get_running_loop().time()`` snapshot.

    Shared by every shutdown-stage timing log so each stage measures its own span with one line.
    """
    return asyncio.get_running_loop().time() - start
