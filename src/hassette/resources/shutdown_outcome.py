"""The outcome of one completed shutdown attempt for Resource, Service, and Hassette.

A completed shutdown attempt is represented by a :class:`ShutdownOutcome`. ``None`` (not an instance of
this class) means "no completed shutdown attempt" -- the resource has never shut down, or a shutdown
attempt is still in progress.

An outcome carries three things, the ones its readers branch on: a ranked :class:`ShutdownResult`, the
names of whatever was still running, and one reason naming the resource and step behind the worst
result. :attr:`ShutdownOutcome.is_restart_safe` answers "may work from this attempt still be running?"
and is derived from the result and the names rather than stored, so an outcome can never claim
restart-safe while naming something still running.

This module defines only the data shape and pure merge helpers. Lifecycle coordination lives in
``hassette.resources.lifecycle``. The design is ``design/specs/141-shutdown-outcome/design.md`` (D1, D2).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum


class ShutdownResult(IntEnum):
    """How a shutdown attempt ended, ranked so that merging keeps the worst.

    Ordered ``DONE`` < ``FAILED`` < ``TIMED_OUT`` < ``INCOMPLETE``, as systemd's ``Result=`` keeps one value
    per unit. Only ``INCOMPLETE`` makes an outcome restart-unsafe on its own; the others describe a teardown
    that has ended. ``TIMED_OUT`` is kept for a shutdown hook cut off at its bound, because an app stop reads it
    as a timed-out stop and fails the stop; a ``cleanup()`` cut off at its bound is ``FAILED``.
    """

    DONE = 0
    """Every step ended normally. Tasks may still be named in ``still_running``."""

    FAILED = 1
    """A shutdown hook raised, or ``cleanup()`` raised or was cut off at its bound, and has ended."""

    TIMED_OUT = 2
    """A shutdown hook was cut off at its bound, and has ended."""

    INCOMPLETE = 3
    """The evidence is incomplete, so work may still be running: a shutdown body that raised or was
    cancelled, a coordinator that raised, a forced terminal state, a child whose shutdown raised, or a
    child cut off at an exit stage's deadline."""


@dataclass(frozen=True, slots=True)
class ShutdownOutcome:
    """The outcome of one completed shutdown attempt.

    ``still_running`` names tasks that were still pending: owned tasks, a serve task, or an initializer
    (by its task name, ``resource:initialize:<unique_name>``). ``reason`` names the resource and step
    behind ``result``; it is ``None`` for ``DONE``. Lesser problems are in the logs only.

    ``result`` alone doesn't say whether work may still run: a ``DONE`` outcome naming tasks in
    ``still_running`` is restart-unsafe. Read ``is_restart_safe`` for that.

    ``__post_init__`` normalizes ``still_running`` to a tuple: ``frozen=True`` blocks reassigning a field,
    but not the type of a value passed in, and a list would let a later mutation change
    ``is_restart_safe`` and make the outcome unhashable.
    """

    result: ShutdownResult = ShutdownResult.DONE
    still_running: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "still_running", tuple(self.still_running))

    @property
    def is_restart_safe(self) -> bool:
        """``False`` when work from this attempt may still be running; ``True`` otherwise.

        Work may still run when anything is named in ``still_running``, or when the result is
        ``INCOMPLETE``. A hook or ``cleanup()`` that raised or timed out and has ended is restart-safe.
        """
        return self.result is not ShutdownResult.INCOMPLETE and not self.still_running


def merge_outcomes(*outcomes: ShutdownOutcome) -> ShutdownOutcome:
    """Combine outcomes into one: the worst result, the union of names, and the worst result's first reason.

    Names are deduplicated in first-seen order. The reason is the first one recorded, in the order the
    outcomes are given, among those at the merged result. Used to fold a body's stages together, to merge
    children into a parent, and to merge a stored outcome with later evidence (stored first, so its reason
    wins a tie). Never mutates an input.
    """
    if not outcomes:
        return ShutdownOutcome()
    result = max(outcome.result for outcome in outcomes)
    reason = next((outcome.reason for outcome in outcomes if outcome.result is result and outcome.reason), None)
    return ShutdownOutcome(
        result=result,
        still_running=tuple(dict.fromkeys(name for outcome in outcomes for name in outcome.still_running)),
        reason=reason,
    )


def incomplete_outcome(reason: str, still_running: Iterable[str] = ()) -> ShutdownOutcome:
    """An ``INCOMPLETE`` outcome with its reason, for the producers that record one."""
    return ShutdownOutcome(ShutdownResult.INCOMPLETE, tuple(still_running), reason)
