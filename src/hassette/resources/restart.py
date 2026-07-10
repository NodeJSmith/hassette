from dataclasses import dataclass

from hassette.types.enums import RestartType


@dataclass(frozen=True)
class RestartSpec:
    """Specification for how a Service should handle restarts and budget exhaustion.

    Attach to a :class:`Service` subclass as a class attribute::

        class MyService(Service):
            restart_spec = RestartSpec(restart_type=RestartType.PERMANENT)
    """

    restart_type: RestartType = RestartType.TRANSIENT
    """Strategy governing restart and budget-exhaustion behavior."""

    non_retryable_error_names: tuple[str, ...] = ()
    """Exception type names that skip restart and follow the budget-exhaustion path directly."""

    fatal_error_names: tuple[str, ...] = ()
    """Exception type names that always trigger immediate shutdown regardless of restart_type."""

    backoff_base_seconds: float = 2.0
    """Base seconds for exponential backoff between restart attempts."""

    backoff_multiplier: float = 2.0
    """Multiplier applied to backoff on each successive restart attempt."""

    backoff_max_seconds: float = 60.0
    """Maximum backoff delay in seconds."""

    budget_intensity: int = 5
    """Maximum number of restarts allowed within the budget window."""

    budget_period_seconds: float = 300.0
    """Sliding window size in seconds for the restart budget."""

    startup_timeout_seconds: float = 30.0
    """How long to wait for mark_ready() after a restart before considering it failed."""

    cooldown_seconds: float = 300.0
    """Duration in seconds for the long-cooldown phase (TRANSIENT services only)."""

    max_cooldown_cycles: int = 0
    """Maximum cooldown cycles before transitioning to EXHAUSTED_DEAD. 0 = infinite."""


CORE_PERMANENT_RESTART = RestartSpec(
    restart_type=RestartType.PERMANENT,
    budget_intensity=2,
    budget_period_seconds=30,
)
