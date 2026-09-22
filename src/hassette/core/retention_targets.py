"""Declarative registry of the tables managed by retention cleanup and the size failsafe.

Two lists live here, and they differ only by :attr:`RetentionTarget.failsafe_exempt`:
:data:`_RETENTION_TABLES` is the full set that age-based retention walks, and
:data:`_FAILSAFE_TABLES` is the subset the size failsafe is allowed to delete from.

The WHERE-clause builders live here too, since they read nothing but ``RetentionTarget`` fields.
"""

import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hassette.types.types import SourceTier

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
    failsafe_exempt: bool = False
    """Exclude this target from the size failsafe's emergency deletion, leaving it managed by
    age-based retention alone. Set for tables that are structurally small relative to the size
    limit — deleting them reclaims almost nothing while destroying the data most needed to
    diagnose whatever caused the overage."""


_RETENTION_TABLES: list[RetentionTarget] = [
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
"""Subset of :data:`_RETENTION_TABLES` the size failsafe may delete from, in the same order."""


def build_tier_where(target: RetentionTarget) -> tuple[str, list[Any]]:
    """Build a ``WHERE source_tier = ?`` clause (with trailing space) for ``target``, or an
    empty clause when it carries no tier filter. Shared by the size failsafe's delete and its
    stale-row probe, which filter by tier alone (no age cutoff).
    """
    if target.source_tier:
        return "WHERE source_tier = ? ", [target.source_tier]
    return "", []


def build_age_where(target: RetentionTarget, cutoff: float) -> tuple[str, list[Any]]:
    """Build the ``WHERE ... < cutoff`` clause (plus tier filter, when set) for ``target``.

    Shared by the age-based retention delete and its stale-row probe.
    """
    where = f"{target.timestamp_col} < ?"
    params: list[Any] = [cutoff]
    if target.source_tier:
        where = f"source_tier = ? AND {where}"
        params.insert(0, target.source_tier)
    return where, params
