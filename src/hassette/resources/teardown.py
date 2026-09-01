"""Immutable teardown safety evidence for Resource, Service, and Hassette lifecycle shutdown.

A completed shutdown attempt is represented by a :class:`TeardownReport`. ``None`` (not an
instance of this class) means "no completed teardown attempt" -- the resource has never shut
down, or a shutdown attempt is still in progress. Because a completed report has only two final
states, :attr:`TeardownReport.is_restart_safe` is derived from the report's recorded
:class:`TeardownCause` values rather than stored separately, so a report can never claim
restart-safe while also carrying negative evidence.

This module defines only the data shape and pure, side-effect-free construction helpers. Lifecycle
coordination -- creating and joining initialization/shutdown tasks, invoking shutdown bodies, and
deciding whether a new attempt may start -- lives in ``hassette.resources.lifecycle`` and stays
internal; see the "Teardown report" and "Minimal lifecycle coordinator" sections of
``design/specs/105-teardown-restart-safety/design.md``.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import TypeVar

T = TypeVar("T")


class TeardownCause(StrEnum):
    """A concrete piece of negative evidence collected during a shutdown attempt.

    Any non-empty set of causes on a :class:`TeardownReport` makes
    :attr:`TeardownReport.is_restart_safe` ``False``. Once recorded, a cause is never removed
    from a report; later evidence may only add to it (see :func:`add_teardown_evidence`).
    """

    SHUTDOWN_HOOK_FAILED = auto()
    """A registered shutdown hook raised during the teardown attempt."""

    SHUTDOWN_BODY_TIMED_OUT = auto()
    """The resource's shutdown body did not complete within its allotted timeout. When the body
    also remains alive past that timeout, its task name is recorded in the report's
    ``pending_tasks`` rather than as a separate cause -- the two checks share the same
    ``SHUTDOWN_BODY_TIMED_OUT`` branch with no suspension point between them, so a distinct
    "pending" cause would record the same fact twice."""

    SHUTDOWN_BODY_FAILED = auto()
    """The resource's shutdown body raised during the teardown attempt."""

    CLEANUP_FAILED = auto()
    """A resource's cleanup step raised during the teardown attempt."""

    CLEANUP_TIMED_OUT = auto()
    """A resource's cleanup step did not complete within its allotted timeout."""

    INITIALIZATION_TASK_PENDING = auto()
    """The resource's initialization task was still pending when teardown began."""

    TASKS_PENDING = auto()
    """One or more tasks owned by the resource were still pending when the report was produced."""

    SERVE_TASK_PENDING = auto()
    """The resource's serve task was still pending when the report was produced."""

    CHILD_SHUTDOWN_FAILED = auto()
    """A child resource's shutdown attempt failed."""

    CHILD_SHUTDOWN_TIMED_OUT = auto()
    """A child resource's shutdown attempt did not complete within its allotted timeout."""

    CHILD_RESTART_UNSAFE = auto()
    """A child resource's own teardown report recorded ``is_restart_safe`` as ``False``."""

    FORCED_TERMINAL = auto()
    """The resource was forced into a terminal state without a normal teardown attempt completing."""

    TOTAL_TIMEOUT = auto()
    """The overall teardown attempt exceeded its total allotted timeout."""

    COORDINATOR_FAILED = auto()
    """The shutdown coordinator itself raised outside the shutdown body (e.g. while observing the
    active initializer or requesting shutdown), not the shutdown body task it dispatches."""


TIMEOUT_ONLY_CAUSES: frozenset[TeardownCause] = frozenset(
    {
        TeardownCause.CLEANUP_TIMED_OUT,
        TeardownCause.TASKS_PENDING,
        TeardownCause.SERVE_TASK_PENDING,
        TeardownCause.SHUTDOWN_BODY_TIMED_OUT,
    }
)
"""The subset of :class:`TeardownCause` values that mean "a task might simply still be finishing
up" rather than an actual failure. Every other cause (a hook or shutdown body raising, cleanup
raising, a child's own unsafe report, a forced-terminal transition, a total timeout, or the
coordinator itself raising) represents real negative evidence, not something that resolves by
waiting longer. See :attr:`TeardownReport.is_timeout_only_refusal`."""


def _dedupe_preserve_order(*groups: Iterable[T]) -> tuple[T, ...]:
    """Flatten one or more iterables into one deterministic, deduplicated tuple.

    Preserves first-seen order across every group, in the order the groups are given. This is
    what lets :func:`merge_teardown_reports` combine an existing report's evidence with new
    evidence without reordering or duplicating entries.
    """
    seen: set[T] = set()
    ordered: list[T] = []
    for group in groups:
        for item in group:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
    return tuple(ordered)


@dataclass(frozen=True, slots=True)
class TeardownReport:
    """Immutable evidence collected during one completed shutdown attempt.

    ``is_restart_safe`` is derived from ``causes`` rather than stored, so a report can never
    claim restart-safe while also carrying negative evidence.

    ``failed_operations`` records bounded operation identities -- a hook's qualified name,
    ``"cleanup"``, a child's resource name -- never exception type, message, or traceback. Those
    remain in the framework's existing logs; copying them into the report would make the report
    unbounded and would duplicate observability that already exists.

    Every field is a tuple so a report is hashable and its equality is structural, which is what
    lets tests assert "the exact same report" by value rather than by object identity.
    ``__post_init__`` normalizes each field to a tuple -- ``frozen=True`` blocks reassigning a
    field after construction, but not the type of a value passed in for one; a caller that
    constructs ``TeardownReport(causes=[...])`` with a list would otherwise keep that mutable
    list, letting a later mutation change ``is_restart_safe`` out from under a caller and making
    the report fail to hash where callers rely on structural equality.
    """

    causes: tuple[TeardownCause, ...] = ()
    failed_operations: tuple[str, ...] = ()
    pending_tasks: tuple[str, ...] = ()
    affected_resources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "causes", tuple(self.causes))
        object.__setattr__(self, "failed_operations", tuple(self.failed_operations))
        object.__setattr__(self, "pending_tasks", tuple(self.pending_tasks))
        object.__setattr__(self, "affected_resources", tuple(self.affected_resources))

    @property
    def is_restart_safe(self) -> bool:
        """``True`` only when no causes were recorded; ``False`` otherwise."""
        return not self.causes

    @property
    def is_timeout_only_refusal(self) -> bool:
        """True when every recorded cause is a timeout-only cause (see TIMEOUT_ONLY_CAUSES).

        False when there are no causes at all (nothing to classify -- use is_restart_safe for
        that case) or when any recorded cause falls outside the timeout-only set.
        """
        return bool(self.causes) and all(cause in TIMEOUT_ONLY_CAUSES for cause in self.causes)


def merge_teardown_reports(*reports: TeardownReport) -> TeardownReport:
    """Combine any number of teardown reports into one new, deduplicated report.

    Every field is deduplicated while preserving first-seen order across the reports in the
    order given. Never mutates an input report -- each is immutable and may already be held by
    another caller. Used both to fold one body's evidence together and to aggregate child
    reports into a parent report, which later adds a parent-specific cause (such as
    :attr:`TeardownCause.CHILD_RESTART_UNSAFE`) via :func:`add_teardown_evidence`.
    """
    return TeardownReport(
        causes=_dedupe_preserve_order(*(report.causes for report in reports)),
        failed_operations=_dedupe_preserve_order(*(report.failed_operations for report in reports)),
        pending_tasks=_dedupe_preserve_order(*(report.pending_tasks for report in reports)),
        affected_resources=_dedupe_preserve_order(*(report.affected_resources for report in reports)),
    )


def add_teardown_evidence(
    report: TeardownReport,
    *,
    causes: Iterable[TeardownCause] = (),
    failed_operations: Iterable[str] = (),
    pending_tasks: Iterable[str] = (),
    affected_resources: Iterable[str] = (),
) -> TeardownReport:
    """Return a new report with additional evidence merged onto ``report``.

    Monotonic: every cause, failed operation, pending task, and affected resource already on
    ``report`` is preserved -- this can only add evidence, never remove it. This is the primitive
    later lifecycle code uses to add a parent-specific cause after merging child reports with
    :func:`merge_teardown_reports`, and the primitive force-terminal handling uses to add
    :attr:`TeardownCause.FORCED_TERMINAL` without discarding evidence a body already recorded.
    """
    return merge_teardown_reports(
        report,
        TeardownReport(
            causes=tuple(causes),
            failed_operations=tuple(failed_operations),
            pending_tasks=tuple(pending_tasks),
            affected_resources=tuple(affected_resources),
        ),
    )
