"""Rate-limited logging for `wait_for` futures cancelled by a non-shutdown listener removal."""

import logging
import threading
import time
import typing

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette.bus.listeners import Listener

WAIT_FOR_CANCEL_WARN_INTERVAL_SECONDS = 60.0
"""Minimum gap between non-shutdown wait_for cancellation WARNINGs on one Bus; cancellations in between log at DEBUG."""


_CANCEL_MSG = (
    "Cancelling pending wait_for future for listener '%s' on topic '%s' (app_key=%s, instance=%s, db_id=%s; listener "
    "removed before a matching event arrived; %d wait_for future(s) still pending)"
)
_CANCEL_MSG_WITH_DEMOTED = _CANCEL_MSG + " — %d earlier cancellation(s) were logged at DEBUG since the last warning"


class WaitForCancellationLog:
    """Logs wait_for cancellations so routine cancel patterns don't bury the pending-count leak WARNING.

    At most one cancellation per `WAIT_FOR_CANCEL_WARN_INTERVAL_SECONDS` logs at WARNING; the rest of that window
    logs at DEBUG, and the next WARNING reports how many were demoted. Shutdown cancellations bypass this entirely:
    `Bus.on_shutdown` batches them into one summary line.
    """

    def __init__(self, logger: logging.Logger, clock: "Callable[[], float]" = time.monotonic) -> None:
        self.logger = logger
        self.clock = clock
        # Sync-facade removals call record() from worker threads, so the window state is only touched under the lock.
        self._lock = threading.Lock()
        self._last_warn_ts: float | None = None
        self._demoted = 0

    def record(self, listener: "Listener", still_pending: int) -> None:
        """Log one cancellation of `listener`'s pending future; `still_pending` is the Bus's remaining count."""
        args = (
            listener.identity.name,
            listener.topic,
            listener.identity.app_key,
            listener.identity.instance_index,
            listener.db_id,
            still_pending,
        )
        demoted_before = self.claim_warning(self.clock())
        if demoted_before is None:
            self.logger.debug(_CANCEL_MSG, *args)
        elif demoted_before:
            self.logger.warning(_CANCEL_MSG_WITH_DEMOTED, *args, demoted_before)
        else:
            self.logger.warning(_CANCEL_MSG, *args)

    def claim_warning(self, now: float) -> int | None:
        """Decide whether a cancellation at `now` may log at WARNING.

        Returns None if it falls inside the current window (it is counted as demoted). Otherwise starts a new window
        at `now` and returns how many cancellations were demoted to DEBUG during the previous one.
        """
        with self._lock:
            if self._last_warn_ts is not None and now - self._last_warn_ts < WAIT_FOR_CANCEL_WARN_INTERVAL_SECONDS:
                self._demoted += 1
                return None
            demoted_before = self._demoted
            self._demoted = 0
            self._last_warn_ts = now
            return demoted_before
