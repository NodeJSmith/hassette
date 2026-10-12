"""Unit tests for hassette.core.websocket_reconnect: failure classification, pacing, and outage logging.

The values pinned here are the ratified ones in design/specs/131-ha-restart-reconnect (D2, D3,
D8, D9, D11, D13). The loop that consumes them is exercised end to end in
tests/integration/websocket/test_reconnect_loop.py.
"""

import logging
import ssl

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from hassette.core.websocket_reconnect import (
    AUTH_RETRIES_AFTER_SUCCESS,
    AUTH_RETRY_SECONDS,
    FAST_BACKOFF_CAP_SECONDS,
    OUTAGE_SUMMARY_INTERVAL_SECONDS,
    RETRY_AFTER_CAP_SECONDS,
    SLOW_RETRY_SECONDS,
    STABLE_CONNECTION_SECONDS,
    WS_MAX_MSG_SIZE,
    Disposition,
    OutageLog,
    ReconnectPolicy,
    RetryPlan,
    fast_backoff_delay,
)
from hassette.exceptions import InvalidAuthError, RetryableConnectionClosedError

MESSAGE_TOO_BIG = 1009


def handshake_error(status: int, headers: dict[str, str] | None = None) -> aiohttp.WSServerHandshakeError:
    url = URL("ws://ha.invalid/api/websocket")
    return aiohttp.WSServerHandshakeError(
        request_info=aiohttp.RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), url),
        history=(),
        status=status,
        headers=CIMultiDictProxy(CIMultiDict(headers or {})),
    )


def oversize_close() -> RetryableConnectionClosedError:
    return RetryableConnectionClosedError("message too big", close_code=MESSAGE_TOO_BIG)


def refused() -> ConnectionRefusedError:
    return ConnectionRefusedError("refused")


class TestFastBackoffDelay:
    @pytest.mark.parametrize(("attempt", "nominal"), [(1, 1.0), (2, 2.0), (3, 4.0)])
    def test_early_attempts_stay_within_jitter_band(self, attempt: int, nominal: float) -> None:
        for _ in range(200):
            assert nominal * 0.8 <= fast_backoff_delay(attempt) <= nominal * 1.2

    @pytest.mark.parametrize("attempt", [4, 5, 50, 100_000])
    def test_later_attempts_never_exceed_cap(self, attempt: int) -> None:
        for _ in range(200):
            assert fast_backoff_delay(attempt) <= FAST_BACKOFF_CAP_SECONDS

    def test_cap_is_five_seconds(self) -> None:
        assert FAST_BACKOFF_CAP_SECONDS == 5.0


class TestFastCurveReset:
    def test_stable_connection_restarts_the_curve(self) -> None:
        policy = ReconnectPolicy()
        for _ in range(4):
            policy.on_failure(refused(), has_ever_connected=True)

        policy.on_connection_ended(STABLE_CONNECTION_SECONDS)
        plan = policy.on_failure(refused(), has_ever_connected=True)

        assert plan.delay is not None
        assert plan.delay <= 1.2

    def test_flap_continues_the_curve(self) -> None:
        policy = ReconnectPolicy()
        for _ in range(4):
            policy.on_failure(refused(), has_ever_connected=True)

        policy.on_connection_ended(STABLE_CONNECTION_SECONDS - 1)
        plan = policy.on_failure(refused(), has_ever_connected=True)

        assert plan.delay is not None
        assert plan.delay >= 4.0

    def test_attempt_that_never_connected_continues_the_curve(self) -> None:
        policy = ReconnectPolicy()
        policy.on_failure(refused(), has_ever_connected=False)
        policy.on_connection_ended(None)

        assert policy.fast_attempt == 1


class TestAuthRejection:
    def test_never_connected_parks_immediately(self) -> None:
        plan = ReconnectPolicy().on_failure(InvalidAuthError("bad"), has_ever_connected=False)

        assert plan.disposition is Disposition.PARK
        assert plan.delay is None

    def test_after_prior_success_retries_three_times_sixty_seconds_apart_then_parks(self) -> None:
        policy = ReconnectPolicy()

        plans = [policy.on_failure(InvalidAuthError("bad"), has_ever_connected=True) for _ in range(4)]

        assert [p.disposition for p in plans] == [Disposition.AUTH_RETRY] * 3 + [Disposition.PARK]
        assert [p.delay for p in plans[:3]] == [AUTH_RETRY_SECONDS] * 3
        assert AUTH_RETRY_SECONDS == 60.0
        assert AUTH_RETRIES_AFTER_SUCCESS == 3

    def test_reaching_connected_restarts_the_count(self) -> None:
        policy = ReconnectPolicy()
        for _ in range(3):
            policy.on_failure(InvalidAuthError("bad"), has_ever_connected=True)

        policy.on_connected()

        assert policy.on_failure(InvalidAuthError("bad"), has_ever_connected=True).disposition is Disposition.AUTH_RETRY


class TestSlowDisposition:
    @pytest.mark.parametrize("status", [401, 403, 404, 429])
    def test_handshake_statuses_that_cannot_heal_retry_every_five_minutes(self, status: int) -> None:
        plan = ReconnectPolicy().on_failure(handshake_error(status), has_ever_connected=True)

        assert plan == RetryPlan(Disposition.SLOW, SLOW_RETRY_SECONDS, plan.cause)
        assert SLOW_RETRY_SECONDS == 300.0

    @pytest.mark.parametrize("status", [500, 502, 503, 400])
    def test_other_handshake_statuses_are_fast(self, status: int) -> None:
        assert (
            ReconnectPolicy().on_failure(handshake_error(status), has_ever_connected=True).disposition
            is Disposition.FAST
        )

    def test_429_waits_its_retry_after(self) -> None:
        plan = ReconnectPolicy().on_failure(handshake_error(429, {"Retry-After": "42"}), has_ever_connected=True)

        assert plan.delay == 42.0

    def test_429_retry_after_is_capped_at_thirty_minutes(self) -> None:
        plan = ReconnectPolicy().on_failure(handshake_error(429, {"Retry-After": "99999"}), has_ever_connected=True)

        assert plan.delay == RETRY_AFTER_CAP_SECONDS == 1800.0

    def test_429_retry_after_is_floored_at_the_fast_cap(self) -> None:
        """A Retry-After of 0 must not turn the Slow tier into a hot loop."""
        plan = ReconnectPolicy().on_failure(handshake_error(429, {"Retry-After": "0"}), has_ever_connected=True)

        assert plan.delay == FAST_BACKOFF_CAP_SECONDS

    def test_429_with_http_date_retry_after_uses_the_slow_pace(self) -> None:
        headers = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
        plan = ReconnectPolicy().on_failure(handshake_error(429, headers), has_ever_connected=True)

        assert plan.delay == SLOW_RETRY_SECONDS

    @pytest.mark.parametrize("exc", [ssl.SSLError("bad record"), ssl.SSLCertVerificationError("self-signed")])
    def test_tls_errors_are_slow(self, exc: Exception) -> None:
        assert ReconnectPolicy().on_failure(exc, has_ever_connected=True).disposition is Disposition.SLOW


class TestOversizeStreak:
    def test_third_consecutive_1009_is_slow(self) -> None:
        policy = ReconnectPolicy()

        plans = [policy.on_failure(oversize_close(), has_ever_connected=True) for _ in range(4)]

        assert [p.disposition for p in plans] == [
            Disposition.FAST,
            Disposition.FAST,
            Disposition.SLOW,
            Disposition.SLOW,
        ]

    def test_streak_survives_a_short_connected_period(self) -> None:
        """The oversized get_states is sent after CONNECTED, so reaching CONNECTED alone must not clear it."""
        policy = ReconnectPolicy()
        for _ in range(2):
            policy.on_connected()
            policy.on_connection_ended(1.0)
            policy.on_failure(oversize_close(), has_ever_connected=True)

        policy.on_connected()
        policy.on_connection_ended(1.0)

        assert policy.on_failure(oversize_close(), has_ever_connected=True).disposition is Disposition.SLOW

    def test_stable_connection_clears_the_streak(self) -> None:
        policy = ReconnectPolicy()
        for _ in range(2):
            policy.on_failure(oversize_close(), has_ever_connected=True)

        policy.on_connection_ended(STABLE_CONNECTION_SECONDS)

        assert policy.on_failure(oversize_close(), has_ever_connected=True).disposition is Disposition.FAST

    def test_a_different_failure_clears_the_streak(self) -> None:
        policy = ReconnectPolicy()
        for _ in range(2):
            policy.on_failure(oversize_close(), has_ever_connected=True)

        policy.on_failure(refused(), has_ever_connected=True)

        assert policy.on_failure(oversize_close(), has_ever_connected=True).disposition is Disposition.FAST

    def test_an_auth_rejection_clears_the_streak(self) -> None:
        policy = ReconnectPolicy()
        for _ in range(2):
            policy.on_failure(oversize_close(), has_ever_connected=True)

        policy.on_failure(InvalidAuthError("bad"), has_ever_connected=True)

        assert policy.on_failure(oversize_close(), has_ever_connected=True).disposition is Disposition.FAST

    def test_size_limit_is_sixteen_mebibytes(self) -> None:
        assert WS_MAX_MSG_SIZE == 16 * 1024 * 1024


class TestOutageLog:
    @staticmethod
    def make_log() -> OutageLog:
        return OutageLog(logging.getLogger("test.outage"), "ws://ha.invalid/api/websocket")

    def test_summary_is_due_every_five_minutes_of_an_episode(self) -> None:
        log = self.make_log()
        plan = RetryPlan(Disposition.FAST, 1.0, "refused")
        log.record_failure(refused(), plan, now=0.0, connected_for=None, has_ever_connected=True)

        assert not log.summary_due(OUTAGE_SUMMARY_INTERVAL_SECONDS - 1)
        assert log.summary_due(OUTAGE_SUMMARY_INTERVAL_SECONDS)

        log.maybe_summarize(OUTAGE_SUMMARY_INTERVAL_SECONDS, has_ever_connected=True)

        assert not log.summary_due(OUTAGE_SUMMARY_INTERVAL_SECONDS + 1)

    def test_no_summary_without_an_episode(self) -> None:
        assert not self.make_log().summary_due(10_000.0)

    def test_short_connection_counts_as_a_flap_within_the_episode(self) -> None:
        log = self.make_log()
        plan = RetryPlan(Disposition.FAST, 1.0, "closed")
        log.record_failure(refused(), plan, now=0.0, connected_for=None, has_ever_connected=True)
        log.record_failure(refused(), plan, now=10.0, connected_for=5.0, has_ever_connected=True)

        assert log.flaps == 1
        assert log.episode_started_at == 0.0

    def test_stable_connection_starts_a_new_episode(self) -> None:
        log = self.make_log()
        plan = RetryPlan(Disposition.FAST, 1.0, "closed")
        log.record_failure(refused(), plan, now=0.0, connected_for=None, has_ever_connected=True)
        log.record_failure(refused(), plan, now=500.0, connected_for=STABLE_CONNECTION_SECONDS, has_ever_connected=True)

        assert log.episode_started_at == 500.0
        assert log.flaps == 0

    def test_traceback_logged_once_per_type_and_innermost_frame(self) -> None:
        log = self.make_log()

        def raise_at_one_place() -> None:
            raise RuntimeError("proxy oddity")

        def raise_at_another_place() -> None:
            raise RuntimeError("proxy oddity")

        errors: list[RuntimeError] = []
        for raiser in (raise_at_one_place, raise_at_one_place, raise_at_another_place):
            try:
                raiser()
            except RuntimeError as exc:
                errors.append(exc)

        assert [log.should_log_traceback(exc) for exc in errors] == [True, False, True]
