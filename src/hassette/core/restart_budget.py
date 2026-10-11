import time


class RestartBudget:
    """Sliding-window restart budget tracker.

    Tracks restart timestamps within a rolling time window. Once the number of
    recorded restarts within the window reaches ``intensity``, the budget is
    considered exhausted.

    Uses :func:`time.monotonic` for clock-independence and resistance to
    system clock changes.
    """

    def __init__(self, intensity: int, period_seconds: float) -> None:
        """Initialize the budget tracker.

        Args:
            intensity: Maximum number of restarts allowed within the window.
            period_seconds: Sliding window size in seconds.
        """
        self._timestamps: list[float] = []
        self._intensity = intensity
        self._period = period_seconds

    def record_restart(self) -> None:
        """Record a restart at the current monotonic time."""
        self._timestamps.append(time.monotonic())

    def is_exhausted(self) -> bool:
        """Return True if the number of restarts within the window meets or exceeds intensity."""
        self.evict_expired()
        return len(self._timestamps) >= self._intensity

    def current_attempts(self) -> int:
        """Return the number of restarts within the current window."""
        self.evict_expired()
        return len(self._timestamps)

    def reset(self) -> None:
        """Clear all recorded restart timestamps."""
        self._timestamps.clear()

    def evict_expired(self) -> None:
        """Remove timestamps that have fallen outside the sliding window."""
        cutoff = time.monotonic() - self._period
        self._timestamps = [t for t in self._timestamps if t > cutoff]
