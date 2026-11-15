"""WarnPacer: lets a recurring WARNING through at most once per interval."""

import time


class WarnPacer:
    """Gates a recurring WARNING to at most one per interval, on the monotonic clock.

    Each site that paces a WARNING holds its own instance, so one site's WARNING never suppresses another's.
    The interval is passed on each call, so a site whose interval is a setting reads it at the call. The first
    call always passes. ``wait_for_cancellations``'s demotion window also counts the calls it holds back, so
    it keeps its own gate.
    """

    def __init__(self) -> None:
        self.last_ts: float | None = None
        """Monotonic time of the last call that passed, or None before the first."""

    def allow(self, interval: float, *, now: float | None = None) -> bool:
        """Return True and start a new interval if the last passing call was ``interval`` or more seconds ago.

        A True return consumes the interval: a second call straight after returns False.

        Args:
            interval: Seconds a passing call holds the gate shut.
            now: The current monotonic time, for a caller with its own clock; read from ``time.monotonic()``
                when omitted.
        """
        now = time.monotonic() if now is None else now
        if self.last_ts is not None and now - self.last_ts < interval:
            return False
        self.last_ts = now
        return True
