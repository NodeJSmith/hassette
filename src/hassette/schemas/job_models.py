"""Pydantic models for job (scheduled task) telemetry DB query results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.

For app-registry snapshots, see ``hassette.schemas.app_snapshots``. For the live
system-status snapshot, served models, and WS payloads, see ``hassette_wire``.

See ``schemas/__init__.py`` for the domain-file map.
"""

from typing import Literal

from hassette_wire import SourceTier
from pydantic import BaseModel


class JobGlobalStats(BaseModel):
    """Job aggregate stats within ``GlobalSummary``."""

    total_jobs: int
    executed_jobs: int
    total_executions: int
    total_errors: int
    total_timed_out: int = 0
    avg_duration_ms: float = 0.0


class JobErrorRecord(BaseModel):
    """Job error returned by ``get_recent_errors()``."""

    kind: Literal["job"] = "job"
    job_id: int | None
    app_key: str | None
    job_name: str | None
    handler_method: str | None
    execution_start_ts: float
    duration_ms: float
    source_tier: SourceTier = "app"
    error_type: str | None
    error_message: str | None
    error_traceback: str | None = None
    source_location: str | None = None
    """Source file location of the job handler (e.g. 'my_app.py:99')."""
