import heapq
import itertools
import typing
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

    sort_index: tuple[SystemDateTime, float, int] = field(init=False, repr=False)

    owner: str = field(compare=False)
    next_run: SystemDateTime = field(compare=False)
    job: "JobCallable" = field(compare=False)
    trigger: "TriggerProtocol | None" = field(compare=False, default=None)
    repeat: bool = field(compare=False, default=False)
    name: str = field(default="", compare=False)
    cancelled: bool = field(default=False, compare=False)
    args: tuple[Any, ...] = field(default_factory=tuple, compare=False)
    kwargs: dict[str, Any] = field(default_factory=dict, compare=False)
    job_id: int = field(default_factory=next_id, init=False, compare=False)

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
        self.sort_index = (rounded_next_run, next_run.timestamp_nanos(), self.job_id)


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
