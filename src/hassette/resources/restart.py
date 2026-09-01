import warnings
from dataclasses import dataclass

from hassette.types.enums import RestartType

# Shared between RestartSpec's own field defaults and single_point_of_failure()'s parameter
# defaults below, so the two can never silently drift apart.
_DEFAULT_RESTART_TYPE = RestartType.TRANSIENT
_DEFAULT_BUDGET_INTENSITY = 5
_DEFAULT_BUDGET_PERIOD_SECONDS = 300.0
_DEFAULT_STARTUP_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class RestartSpec:
    """Specification for how a Service should handle restarts and budget exhaustion.

    Attach to a :class:`Service` subclass as a class attribute::

        class MyService(Service):
            restart_spec = RestartSpec(restart_type=RestartType.PERMANENT)
    """

    restart_type: RestartType = _DEFAULT_RESTART_TYPE
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

    budget_intensity: int = _DEFAULT_BUDGET_INTENSITY
    """Maximum number of restarts allowed within the budget window."""

    budget_period_seconds: float = _DEFAULT_BUDGET_PERIOD_SECONDS
    """Sliding window size in seconds for the restart budget."""

    startup_timeout_seconds: float = _DEFAULT_STARTUP_TIMEOUT_SECONDS
    """How long to wait for mark_ready() after a restart before considering it failed."""

    cooldown_seconds: float = 300.0
    """Duration in seconds for the long-cooldown phase (TRANSIENT services only)."""

    max_cooldown_cycles: int = 0
    """Maximum cooldown cycles before transitioning to EXHAUSTED_DEAD. 0 = infinite."""

    allow_scoped_degradation: bool | None = None
    """Whether a timeout-only restart refusal, once confirmed quiescent, degrades just this service
    to EXHAUSTED_DEAD instead of escalating to root shutdown. False for services where running the
    rest of the framework without this one is worse than a clean restart.

    Leave unset (``None``) to get the type-appropriate default: ``True`` for `TRANSIENT`/`TEMPORARY`,
    ``False`` for `PERMANENT`. An unset value that resolves to ``True`` -- the direction that lets a
    service silently degrade instead of escalating -- emits a warning naming this field, since a
    plain dataclass has no way to tell "the caller explicitly chose the default" from "the caller
    never noticed this field exists" (the exact way this field went unnoticed on `WebApiService`
    until a ship-time challenge caught it -- see :meth:`RestartSpec.single_point_of_failure` for
    services that should set this to ``False``).

    The ``None`` in the type is only ever observed by ``__post_init__``, which always resolves it
    to a concrete ``bool`` before construction completes -- every consumer of an already-built
    :class:`RestartSpec` can treat this field as a plain ``bool``.
    """

    def __post_init__(self) -> None:
        if self.allow_scoped_degradation is None:
            resolved = self.restart_type is not RestartType.PERMANENT
            if resolved:
                warnings.warn(
                    f"RestartSpec(restart_type={self.restart_type.value}) does not explicitly set "
                    "allow_scoped_degradation -- defaulting to True. If this service "
                    "is a single point of failure where running the framework without it is worse "
                    "than a clean restart (e.g. the sole connection to Home Assistant, or the sole "
                    "dashboard/REST interface), set it to False explicitly -- see "
                    "RestartSpec.single_point_of_failure().",
                    UserWarning,
                    stacklevel=2,
                )
            object.__setattr__(self, "allow_scoped_degradation", resolved)

    @classmethod
    def single_point_of_failure(
        cls,
        *,
        restart_type: RestartType = _DEFAULT_RESTART_TYPE,
        budget_intensity: int = _DEFAULT_BUDGET_INTENSITY,
        budget_period_seconds: float = _DEFAULT_BUDGET_PERIOD_SECONDS,
        startup_timeout_seconds: float = _DEFAULT_STARTUP_TIMEOUT_SECONDS,
    ) -> "RestartSpec":
        """A :class:`RestartSpec` for a service where running the framework without it is worse
        than a clean restart -- opts out of the confirmed-quiescent degrade path so a
        timeout-only refusal still escalates to root shutdown instead of silently leaving the
        service at ``EXHAUSTED_DEAD``.

        Use for a service that is the framework's sole path to some capability nothing else can
        substitute for (e.g. `WebsocketService`'s connection to Home Assistant, `WebApiService`'s
        dashboard/REST interface) -- as distinct from `PERMANENT` services, which use
        :data:`CORE_PERMANENT_RESTART` because losing *them* stops automations from running at
        all.

        Only exposes the fields the framework's own single-point-of-failure services actually
        set today. If a future caller needs to vary a different field too, add it here rather
        than reintroducing an untyped ``**overrides`` passthrough.
        """
        return cls(
            restart_type=restart_type,
            budget_intensity=budget_intensity,
            budget_period_seconds=budget_period_seconds,
            startup_timeout_seconds=startup_timeout_seconds,
            allow_scoped_degradation=False,
        )


CORE_PERMANENT_RESTART = RestartSpec(
    restart_type=RestartType.PERMANENT,
    budget_intensity=2,
    budget_period_seconds=30,
    allow_scoped_degradation=False,
)
