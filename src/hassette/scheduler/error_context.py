"""Error context dataclass for scheduler job failures."""

from dataclasses import dataclass
from typing import Any

from hassette.error_context import ErrorContext


@dataclass(frozen=True)
class SchedulerErrorContext(ErrorContext):
    """Context passed to scheduler error handlers when a job raises an exception.

    Attributes:
        exception: The exception that was raised by the job.
        traceback: Formatted traceback string.
        job_name: The name of the job function that raised the exception.
        job_group: The group the job belongs to, or None if ungrouped.
        args: Positional arguments the job was scheduled with.
        kwargs: Keyword arguments the job was scheduled with.
    """

    job_name: str
    job_group: str | None
    args: tuple[Any, ...]
    kwargs: dict[str, Any]

    @property
    def log_label(self) -> str:
        return f"job={self.job_name}"
