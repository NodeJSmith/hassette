"""Error context dataclass for scheduler job failures."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SchedulerErrorContext:
    """Context passed to scheduler error handlers when a job raises an exception.

    Attributes:
        exception: The exception that was raised by the job.
        traceback: Formatted traceback string, or None if suppressed (e.g. for known errors).
        job_name: The name of the job function that raised the exception.
        job_group: The group the job belongs to, or None if ungrouped.
        args: Positional arguments the job was scheduled with.
        kwargs: Keyword arguments the job was scheduled with.
    """

    exception: BaseException
    traceback: str | None
    job_name: str
    job_group: str | None
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
