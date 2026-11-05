"""Declarative registry of the tables managed by retention cleanup and the size failsafe.

Two lists live here, and they differ only by :attr:`RetentionTarget.failsafe_exempt`:
:data:`_RETENTION_TABLES` is the full set that age-based retention walks, and
:data:`_FAILSAFE_TABLES` is the subset the size failsafe is allowed to delete from.

Targets may overlap: ``debug log records`` selects the DEBUG rows of ``log_records``, which the
exempt ``log records`` target also covers. Both share ``log_retention_days``, so the overlap changes
nothing about which rows expire by age. It matters to the failsafe, where the exempt target
protects INFO and above and the DEBUG target makes persisted DEBUG lines the first thing deleted.
The age pass walks the DEBUG target first, so ``log records`` finds no expired DEBUG rows unless
the DEBUG target hit its per-cycle batch cap.

The WHERE-clause builders live here too, since they read nothing but ``RetentionTarget`` fields.
"""

import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from hassette_wire import SourceTier

if typing.TYPE_CHECKING:
    from hassette.config.config import HassetteConfig


@dataclass(frozen=True)
class RetentionTarget:
    """Declarative specification for a table managed by retention cleanup and size failsafe."""

    table: str
    timestamp_col: str
    priority: int
    """Position in the size failsafe's deletion chain (lower number = deleted first). Carried
    but never read for ``failsafe_exempt`` targets, which the chain skips entirely."""
    retention_days_getter: Callable[["HassetteConfig"], int]
    failsafe_label: str
    source_tier: SourceTier | None = None
    """Restrict this target to rows of one source tier. ``None`` means no tier filter (the
    target's table has no ``source_tier`` column, or every row in it should be managed together)."""
    level: Literal["DEBUG"] | None = None
    """Restrict this target to rows at one log ``level`` (``log_records`` only). ``None`` means no
    level filter. Only ``DEBUG`` is allowed: migration 022's partial index serves ``level = 'DEBUG'``,
    and a filter on another level would scan ``idx_lr_time`` instead."""
    failsafe_exempt: bool = False
    """Exclude this target from the size failsafe's emergency deletion, leaving it managed by
    age-based retention alone. Set for tables that are structurally small relative to the size
    limit — deleting them reclaims almost nothing while destroying the data most needed to
    diagnose whatever caused the overage. ``log records`` carries it, so INFO and above are never
    deleted by size; its DEBUG rows are still deleted by size through the ``debug log records``
    target."""


_RETENTION_TABLES: list[RetentionTarget] = [
    RetentionTarget(
        table="log_records",
        timestamp_col="timestamp",
        priority=0,
        retention_days_getter=lambda cfg: cfg.logging.log_retention_days,
        failsafe_label="debug log records",
        level="DEBUG",
    ),
    RetentionTarget(
        table="executions",
        timestamp_col="execution_start_ts",
        priority=1,
        retention_days_getter=lambda cfg: cfg.database.framework_retention_days,
        failsafe_label="framework executions",
        source_tier="framework",
    ),
    RetentionTarget(
        table="blocking_events",
        timestamp_col="detected_ts",
        priority=2,
        retention_days_getter=lambda cfg: cfg.database.retention_days,
        failsafe_label="blocking events",
    ),
    RetentionTarget(
        table="executions",
        timestamp_col="execution_start_ts",
        priority=3,
        retention_days_getter=lambda cfg: cfg.database.retention_days,
        failsafe_label="app executions",
        source_tier="app",
    ),
    # Deliberately level-agnostic: it matches DEBUG rows too, but its exemption only protects
    # INFO and above, since "debug log records" puts DEBUG rows in the failsafe chain first.
    RetentionTarget(
        table="log_records",
        timestamp_col="timestamp",
        priority=4,
        retention_days_getter=lambda cfg: cfg.logging.log_retention_days,
        failsafe_label="log records",
        failsafe_exempt=True,
    ),
]

_FAILSAFE_TABLES: list[RetentionTarget] = [t for t in _RETENTION_TABLES if not t.failsafe_exempt]
"""Subset of :data:`_RETENTION_TABLES` the size failsafe may delete from, in the same order.

``sessions`` is in neither list: age-based retention deletes it in the parent-guard phase
(``DatabaseRetentionMixin._run_parent_guard_deletes``), and the size failsafe never reclaims it,
since the table is small relative to the size limit."""


def row_filter_terms(target: RetentionTarget) -> tuple[list[str], list[Any]]:
    """Return ``target``'s row-filter terms (``source_tier``, ``level``) and their parameters."""
    terms: list[str] = []
    params: list[Any] = []
    if target.source_tier:
        terms.append("source_tier = ?")
        params.append(target.source_tier)
    if target.level is not None:
        terms.append("level = ?")
        params.append(target.level)
    return terms, params


def build_filter_where(target: RetentionTarget) -> tuple[str, list[Any]]:
    """Build a ``WHERE`` clause (with trailing space) from ``target``'s row filters.

    Returns an empty clause when ``target`` carries no filter. Shared by the size failsafe's
    delete and its stale-row probe, which filter by target alone (no age cutoff).
    """
    terms, params = row_filter_terms(target)
    if not terms:
        return "", []
    return f"WHERE {' AND '.join(terms)} ", params


def build_age_where(target: RetentionTarget, cutoff: float) -> tuple[str, list[Any]]:
    """Build the ``WHERE ... < cutoff`` clause (plus the target's row filters) for ``target``.

    Shared by the age-based retention delete and its stale-row probe.
    """
    terms, params = row_filter_terms(target)
    terms.append(f"{target.timestamp_col} < ?")
    params.append(cutoff)
    return " AND ".join(terms), params
