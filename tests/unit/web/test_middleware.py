"""Unit tests for :class:`hassette.web.middleware._FailedAuthTracker`.

Covers the tracker's two load-bearing bounds: it still fires the coalesced WARN-on-threshold
behavior for a single source, and — the property this file exists to pin — it never grows past
:data:`MAX_TRACKED_SOURCES` distinct source keys no matter how many distinct addresses record
attempts. See the CodeRabbit finding on PR review for src/hassette/web/middleware.py: prior to this
fix, `_attempts` was a `defaultdict(list)` that inserted a permanent key on first touch and never
removed it, so an attacker varying its source address (cheap over an IPv6 /64) could grow the dict
without bound.
"""

import logging

import pytest

from hassette.web.middleware import FAILED_AUTH_THRESHOLD, MAX_TRACKED_SOURCES, _FailedAuthTracker


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
