"""Pydantic models for TelemetryQueryService results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.
"""

from pydantic import BaseModel


class AppHealthSummary(BaseModel):
    """Per-app health summary returned by ``get_all_app_summaries()``."""

    handler_count: int
    job_count: int
    total_invocations: int
    total_errors: int
    total_executions: int
    total_job_errors: int
    avg_duration_ms: float
    last_activity_ts: float | None

    @property
    def error_rate(self) -> float:
        """Handler error rate as a percentage (0.0-100.0)."""
        if self.total_invocations == 0:
            return 0.0
        return self.total_errors / self.total_invocations * 100

    @property
    def success_rate(self) -> float:
        """Handler success rate as a percentage (0.0-100.0)."""
        if self.total_invocations == 0:
            return 100.0
        return 100.0 - self.error_rate


class ListenerSummary(BaseModel):
    """Per-listener summary returned by ``get_listener_summary()``."""

    listener_id: int
    app_key: str
    instance_index: int
    handler_method: str
    topic: str
    debounce: float | None
    throttle: float | None
    once: int
    priority: int
    predicate_description: str | None
    human_description: str | None
    source_location: str
    registration_source: str | None
    total_invocations: int
    successful: int
    failed: int
    di_failures: int
    cancelled: int
    total_duration_ms: float
    avg_duration_ms: float
    min_duration_ms: float
    max_duration_ms: float
    last_invoked_at: float | None
    last_error_type: str | None
    last_error_message: str | None


class HandlerInvocation(BaseModel):
    """Single invocation record returned by ``get_handler_invocations()``."""

    execution_start_ts: float
    duration_ms: float
    status: str
    error_type: str | None
    error_message: str | None
    error_traceback: str | None


class JobSummary(BaseModel):
    """Per-job summary returned by ``get_job_summary()``."""

    job_id: int
    app_key: str
    instance_index: int
    job_name: str
    handler_method: str
    trigger_type: str | None
    trigger_value: str | None
    repeat: int
    args_json: str
    kwargs_json: str
    source_location: str
    registration_source: str | None
    total_executions: int
    successful: int
    failed: int
    last_executed_at: float | None
    total_duration_ms: float
    avg_duration_ms: float


class JobExecution(BaseModel):
    """Single execution record returned by ``get_job_executions()``."""

    execution_start_ts: float
    duration_ms: float
    status: str
    error_type: str | None
    error_message: str | None


class ListenerGlobalStats(BaseModel):
    """Listener aggregate stats within ``GlobalSummary``."""

    total_listeners: int
    invoked_listeners: int
    total_invocations: int
    total_errors: int
    total_di_failures: int
    avg_duration_ms: float | None


class JobGlobalStats(BaseModel):
    """Job aggregate stats within ``GlobalSummary``."""

    total_jobs: int
    executed_jobs: int
    total_executions: int
    total_errors: int


class GlobalSummary(BaseModel):
    """Aggregate telemetry summary returned by ``get_global_summary()``."""

    listeners: ListenerGlobalStats
    jobs: JobGlobalStats


class SessionSummary(BaseModel):
    """Current-session summary returned by ``get_current_session_summary()``."""

    started_at: float
    last_heartbeat_at: float
    total_invocations: int
    invocation_errors: int
    total_executions: int
    execution_errors: int
