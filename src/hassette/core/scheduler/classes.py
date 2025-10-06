import heapq
import itertools
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast

from whenever import SystemDateTime

if typing.TYPE_CHECKING:
    from hassette.core.types import JobCallable, TriggerProtocol

seq = itertools.count(1)

T = TypeVar("T")


def next_id() -> int:
    return next(seq)


@dataclass(order=True)
class ScheduledJob:
    """A job scheduled to run based on a trigger or at a specific time."""

    sort_index: tuple[int, int] = field(init=False, repr=False)
    """Tuple of (next_run timestamp with nanoseconds, job_id) for ordering in a priority queue."""

    owner: str = field(compare=False)
    """Unique string identifier for the owner of the job, e.g., a component or integration name."""

    next_run: SystemDateTime = field(compare=False)
    """Timestamp of the next scheduled run."""

    job: "JobCallable" = field(compare=False)
    """The callable to execute when the job runs."""

    trigger: "TriggerProtocol | None" = field(compare=False, default=None)
    """The trigger that determines the job's schedule."""

    repeat: bool = field(compare=False, default=False)
    """Whether the job should be rescheduled after running."""

    timeout_seconds: int = field(compare=False, default=30)
    """Maximum allowed execution time for the job in seconds."""

    name: str = field(default="", compare=False)
    """Optional name for the job for easier identification."""

    cancelled: bool = field(default=False, compare=False)
    """Flag indicating whether the job has been cancelled."""

    args: tuple[Any, ...] = field(default_factory=tuple, compare=False)
    """Positional arguments to pass to the job callable."""

    kwargs: dict[str, Any] = field(default_factory=dict, compare=False)
    """Keyword arguments to pass to the job callable."""

    job_id: int = field(default_factory=next_id, init=False, compare=False)
    """Unique identifier for the job instance."""

    def __repr__(self) -> str:
        return f"ScheduledJob(name={self.name!r}, next_run={self.next_run})"

    def __post_init__(self):
        self.set_next_run(self.next_run)

        if not self.name:
            self.name = self.job.__name__ if hasattr(self.job, "__name__") else str(self.job)

        self.args = tuple(self.args)
        self.kwargs = dict(self.kwargs)

    def cancel(self) -> None:
        """Cancel the scheduled job by setting the cancelled flag to True."""
        self.cancelled = True

    def set_next_run(self, next_run: SystemDateTime) -> None:
        """Update the next run timestamp and refresh ordering metadata."""
        rounded_next_run = next_run.round(unit="second")
        self.next_run = rounded_next_run
        self.sort_index = (next_run.timestamp_nanos(), self.job_id)


@dataclass
class HeapQueue(Generic[T]):
    _queue: list[T] = field(default_factory=list)

    def push(self, job: T):
        """Push a job onto the queue."""
        heapq.heappush(self._queue, job)  # pyright: ignore[reportArgumentType]

    def pop(self) -> T:
        """Pop the next job from the queue."""
        return heapq.heappop(self._queue)  # pyright: ignore[reportArgumentType]

    def peek(self) -> T | None:
        """Peek at the next job without removing it.

        Returns:
            T | None: The next job in the queue, or None if the queue is empty"""
        return self._queue[0] if self._queue else None

    def peek_or_raise(self) -> T:
        """Peek at the next job without removing it, raising an error if the queue is empty.

        Method that the type checker knows always return a value - call `is_empty` first to avoid exceptions.

        Returns:
            T: The next job in the queue.

        Raises:
            IndexError: If the queue is empty.

        """
        if not self._queue:
            raise IndexError("Peek from an empty queue")
        return cast("T", self.peek())

    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return not self._queue

    def remove_where(self, predicate: Callable[[T], bool]) -> int:
        """Remove all items matching the predicate, returning the number removed."""

        original_length = len(self._queue)
        if not original_length:
            return 0

        self._queue = [job for job in self._queue if not predicate(job)]
        removed = original_length - len(self._queue)

        if removed:
            heapq.heapify(self._queue)  # pyright: ignore[reportArgumentType]

        return removed

    def remove_item(self, item: T) -> bool:
        """Remove a specific item from the queue if present."""

        if item not in self._queue:
            return False

        self._queue.remove(item)
        heapq.heapify(self._queue)  # pyright: ignore[reportArgumentType]
        return True
