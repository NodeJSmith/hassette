"""Unit tests for :class:`hassette.web.middleware._FailedAuthTracker`.

Covers the tracker's WARN-on-threshold coalescing plus both of the bounds an unauthenticated peer
could otherwise push on:

- **Across sources** — it never grows past :data:`MAX_TRACKED_SOURCES` distinct keys no matter how
  many addresses record attempts. From a CodeRabbit finding on the PR review for
  src/hassette/web/middleware.py: `_attempts` was a `defaultdict(list)` that inserted a permanent
  key on first touch and never removed it, so an attacker varying its source address (cheap over an
  IPv6 /64) could grow the dict without bound.
- **Within one source** — retained state per source stays flat instead of growing with the request
  count. From an external security audit at 4a20fb95 (CWE-400): `record` rebuilt that source's
  whole in-window timestamp list on every call, making per-request work proportional to attempts
  already made and a sustained burst quadratic overall.

There is deliberately no wall-clock scaling assertion for the second bound. Bounded retained state
*is* the proof that per-request work is constant, and it holds deterministically — a timing ratio
would add nothing but a race against CI's scheduler (see CLAUDE.md on config-driven real-clock
timeouts for how that failure mode plays out here).
"""

import logging
from collections import deque

import pytest

from hassette.web.middleware import (
    FAILED_AUTH_THRESHOLD,
    FAILED_AUTH_WINDOW_SECONDS,
    MAX_TRACKED_SOURCES,
    _FailedAuthTracker,
)


@pytest.fixture(autouse=True)
def _propagate_hassette_logger() -> None:
    """Ensure the "hassette" logger propagates so caplog can see records.

    Some other test in the session may have left ``propagate`` set to False (e.g. via
    ``enable_basic_logging()``); caplog relies on propagation to the root logger. Same
    workaround as ``tests/unit/web/test_auth.py``.
    """
    logging.getLogger("hassette").propagate = True


class TestFailedAuthTracker:
    def test_record_below_threshold_does_not_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        tracker = _FailedAuthTracker()

        with caplog.at_level(logging.WARNING, logger="hassette.web.middleware"):
            for _ in range(FAILED_AUTH_THRESHOLD - 1):
                tracker.record("203.0.113.1")

        warn_records = [r for r in caplog.records if "failed auth attempts" in r.getMessage()]
        assert len(warn_records) == 0

    def test_record_reaching_threshold_warns_exactly_once(self, caplog: pytest.LogCaptureFixture) -> None:
        tracker = _FailedAuthTracker()

        with caplog.at_level(logging.WARNING, logger="hassette.web.middleware"):
            for _ in range(FAILED_AUTH_THRESHOLD + 5):
                tracker.record("203.0.113.1")

        warn_records = [r for r in caplog.records if "failed auth attempts" in r.getMessage()]
        assert len(warn_records) == 1

    def test_distinct_sources_tracked_independently(self, caplog: pytest.LogCaptureFixture) -> None:
        tracker = _FailedAuthTracker()

        with caplog.at_level(logging.WARNING, logger="hassette.web.middleware"):
            for _ in range(FAILED_AUTH_THRESHOLD):
                tracker.record("203.0.113.1")
            for _ in range(FAILED_AUTH_THRESHOLD):
                tracker.record("203.0.113.2")

        warn_records = [r for r in caplog.records if "failed auth attempts" in r.getMessage()]
        assert len(warn_records) == 2

    def test_tracker_does_not_grow_past_max_tracked_sources(self) -> None:
        """The core security property: an attacker varying the source address per request cannot
        grow the tracker without bound, even across far more distinct sources than the cap.
        """
        tracker = _FailedAuthTracker()

        for i in range(MAX_TRACKED_SOURCES * 10):
            tracker.record(f"203.0.113.{i}")
            assert len(tracker._attempts) <= MAX_TRACKED_SOURCES

        assert len(tracker._attempts) == MAX_TRACKED_SOURCES

    def test_recently_touched_source_survives_eviction_pressure(self) -> None:
        """LRU eviction drops the least-recently-touched source first, not an arbitrary one."""
        tracker = _FailedAuthTracker()

        tracker.record("203.0.113.1")
        for i in range(MAX_TRACKED_SOURCES * 2):
            tracker.record(f"198.51.100.{i}")

        assert "203.0.113.1" not in tracker._attempts

    def test_single_source_state_stays_bounded_far_past_threshold(self) -> None:
        """The within-one-source bound: a sustained burst from one peer retains constant state.

        Before this bound, each ``record`` copied and re-grew that source's full in-window
        timestamp list, so retained entries equaled the request count and cumulative work was
        quadratic — one unauthenticated peer aiming the event loop at itself.
        """
        tracker = _FailedAuthTracker()

        for _ in range(FAILED_AUTH_THRESHOLD * 500):
            tracker.record("203.0.113.1")

        assert len(tracker._attempts["203.0.113.1"].timestamps) == FAILED_AUTH_THRESHOLD

    def test_warning_rearms_after_window_elapses(self, caplog: pytest.LogCaptureFixture) -> None:
        """A source that reaches the threshold, goes quiet past the window, then resumes warns again.

        Pins that the ring buffer's ``warned`` latch is scoped to a run above the threshold rather
        than to the source's lifetime — permanent silence after one burst would be a regression.
        """
        tracker = _FailedAuthTracker()

        with caplog.at_level(logging.WARNING, logger="hassette.web.middleware"):
            for _ in range(FAILED_AUTH_THRESHOLD):
                tracker.record("203.0.113.1")

            # Shift every retained timestamp fully out of the window, simulating a quiet period
            # without waiting FAILED_AUTH_WINDOW_SECONDS in real time.
            state = tracker._attempts["203.0.113.1"]
            state.timestamps = deque(
                (t - FAILED_AUTH_WINDOW_SECONDS - 1 for t in state.timestamps),
                maxlen=FAILED_AUTH_THRESHOLD,
            )

            for _ in range(FAILED_AUTH_THRESHOLD):
                tracker.record("203.0.113.1")

        warn_records = [r for r in caplog.records if "failed auth attempts" in r.getMessage()]
        assert len(warn_records) == 2

    def test_attempts_aged_out_of_window_do_not_count_toward_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        """Stale attempts are evicted rather than counted, so the window stays a real sliding window."""
        tracker = _FailedAuthTracker()

        with caplog.at_level(logging.WARNING, logger="hassette.web.middleware"):
            for _ in range(FAILED_AUTH_THRESHOLD - 1):
                tracker.record("203.0.113.1")

            state = tracker._attempts["203.0.113.1"]
            state.timestamps = deque(
                (t - FAILED_AUTH_WINDOW_SECONDS - 1 for t in state.timestamps),
                maxlen=FAILED_AUTH_THRESHOLD,
            )

            # One more attempt: 10 total recorded, but only this one is inside the window.
            tracker.record("203.0.113.1")

        warn_records = [r for r in caplog.records if "failed auth attempts" in r.getMessage()]
        assert len(warn_records) == 0
        assert len(state.timestamps) == 1
