"""Pydantic models for log record and blocking event DB query results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.

For live runtime state models, see ``domain_models.py``.

Separation rationale
--------------------
- ``listener_models.py`` — per-listener summaries, stats, and error records
- ``execution_models.py`` — unified execution records and activity feed
- ``job_models.py`` — per-job summaries, stats, and error records
- ``summary_models.py`` — app-health and global aggregates
- ``log_models.py`` — log records and blocking events (this module)
- ``domain_models.py`` — live state snapshots and WS event payloads
"""

from typing import Literal

from pydantic import BaseModel

from hassette.types.types import LOG_LEVEL_TYPE, BlockingAttributionReason, SourceTier

_BlockingTier = Literal["watchdog", "monkeypatch"]


class LogRecord(BaseModel):
    """Single log record returned by ``get_log_records()`` and ``get_log_records_by_execution()``."""

    id: int
    seq: int
    timestamp: float
    level: LOG_LEVEL_TYPE
    logger_name: str
    func_name: str | None = None
    lineno: int | None = None
    message: str
    exc_info: str | None = None
    app_key: str | None = None
    instance_name: str | None = None
    instance_index: int | None = None
    execution_id: str | None = None
    """UUID string identifying the execution that produced this log record. None for framework logs.

    UUIDv7 for new executions (embeds timestamp); UUIDv4 for historical executions."""
    source_tier: SourceTier | None = None
    """``'app'`` for user automation logs, ``'framework'`` for internal service logs."""


class BlockingEvent(BaseModel):
    """A single blocking event row from the ``blocking_events`` table.

    Written by ``TelemetryRepository.insert_blocking_event`` for every detected
    Tier 1 (watchdog) or Tier 2 (monkeypatch) event. ``app_key`` is nullable so
    unresolved (framework-attributed) owners are recorded, not dropped.
    """

    session_id: int | None
    """Session that was running when the event was detected. None when no session exists yet."""

    app_key: str | None
    """App key of the owner, or ``None`` for unresolved/framework stalls."""

    instance_name: str | None
    instance_index: int | None

    execution_id: str | None
    """UUIDv7 execution that froze the loop. None when no marker was live (Tier 2 off-handler)."""

    tier: _BlockingTier
    """``'watchdog'`` for Tier 1 events; ``'monkeypatch'`` for Tier 2 events."""

    primitive: str | None
    """Blocking primitive name (Tier 2 only, e.g. ``'time.sleep'``). None for Tier 1."""

    source_location: str | None
    """Call-site location string (Tier 2) or loop-thread stack text (Tier 1, when captured)."""

    stall_duration_ms: float | None
    """Stall duration in milliseconds (Tier 1 only). None for Tier 2 events."""

    detected_ts: float
    """Unix epoch seconds when the event was detected (``time.time()``)."""

    source_tier: SourceTier
    """``'app'`` when ``app_key`` is set; ``'framework'`` otherwise. Coarser than ``reason``, which
    splits the ``'framework'`` case into genuinely-unowned (``reason='framework'``) vs
    attribution-withheld (``reason='displaced'``). Kept for backward compatibility with pre-``reason``
    rows and existing queries; new code should prefer ``reason``."""

    reason: BlockingAttributionReason | None = None
    """Why the attribution is what it is. ``'attributed'`` — ``app_key`` names the task that
    actually blocked. ``'framework'`` — no execution was bound (genuine framework/gap block).
    ``'displaced'`` — an execution was bound but a *different* task was frozen on the loop, so
    ``app_key`` was withheld (NULL) rather than blaming the wrong app. ``None`` for rows written
    before migration 007."""
