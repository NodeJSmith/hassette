"""Reconnect policy for :class:`~hassette.core.websocket_service.WebsocketService`.

``WebsocketService.serve()`` owns the only retry loop for the Home Assistant connection. This
module holds the parts of that loop that need no service state: how a failure is classified
and paced (``ReconnectPolicy``), and what an outage looks like in the log (``OutageLog``).
The rationale for every constant below is in ``design/specs/131-ha-restart-reconnect/design.md``
(the D-numbers cited here).

Not to be confused with :mod:`hassette.core.retry_policy`, the retry budget for a single
request/reply exchange over an already-open connection.
"""

import asyncio
import logging
import random
import ssl
import traceback
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum, auto
from http import HTTPStatus
from typing import NoReturn, TypeVar

import aiohttp

from hassette.exceptions import (
    HassetteError,
    InvalidAuthError,
    InvalidLifecycleTransitionError,
    RetryableConnectionClosedError,
)

FAST_BACKOFF_INITIAL_SECONDS = 1.0
"""D8: delay before the first retry after a failure."""

FAST_BACKOFF_BASE = 2
"""D8: exponential base of the Fast curve (1, 2, 4, then the cap)."""

FAST_BACKOFF_MAX_EXPONENT = 10
"""Bounds the exponent so a days-long outage never overflows the float conversion. Any value
past the cap is equivalent, so the bound only has to keep ``BASE ** exponent`` well above it."""

FAST_BACKOFF_CAP_SECONDS = 5.0
"""D2: no Fast-disposition delay exceeds this, jitter included."""

FAST_BACKOFF_JITTER = 0.2
"""D8: each Fast delay is scaled by a random factor in ``[1 - JITTER, 1 + JITTER]`` before capping."""

STABLE_CONNECTION_SECONDS = 120.0
"""D8: time in CONNECTED after which a drop restarts the Fast curve, clears the 1009 streak, and
ends the OutageLog episode (see ``is_stable_connection``). A shorter connection is a flap."""

SLOW_RETRY_SECONDS = 300.0
"""D9: the Slow disposition's fixed pace, for failures a retry can't fix."""

RETRY_AFTER_CAP_SECONDS = 1800.0
"""D9: upper bound on a 429's ``Retry-After``."""

SLOW_HANDSHAKE_STATUSES = frozenset({401, 403, 429})
"""D9: handshake HTTP statuses that won't heal without an upstream fix. Other statuses stay Fast:
notably the Supervisor proxy's 502 while Core restarts, and a reverse proxy's 404 while the HA
backend it routes to is stopped."""

OVERSIZE_STREAK_FOR_SLOW = 3
"""D13: consecutive 1009 closes that move the loop to the Slow disposition."""

CLOSE_CODE_MESSAGE_TOO_BIG = int(aiohttp.WSCloseCode.MESSAGE_TOO_BIG)

AUTH_RETRY_SECONDS = 60.0
"""D3: spacing of the auth retries before parking."""

AUTH_RETRIES = 3
"""D3: auth retries before parking. A rejection can be a false one (HA's clock behind the token's
``iat`` after a host reboot), which a fresh process sees too, so every token gets them."""

OUTAGE_SUMMARY_INTERVAL_SECONDS = 300.0
"""D11: interval between "still unreachable" summaries during an outage."""

CORE_RUNNING_RECHECK_SECONDS = 5.0
"""D12: how often the RUNNING gate re-reads ``get_config`` in case ``homeassistant_started`` was missed."""

WS_MAX_MSG_SIZE = 16 * 1024 * 1024
"""D13: largest incoming WebSocket message accepted (aiohttp's default is 4 MiB)."""

CORE_STATE_RUNNING = "RUNNING"
CORE_STATES_SHUTTING_DOWN = frozenset({"STOPPING", "FINAL_WRITE", "STOPPED"})
"""D12: core states that will never reach RUNNING on this connection."""

HA_STARTED_EVENT_TYPE = "homeassistant_started"

_T = TypeVar("_T")

AUTH_REJECTED_REASON = "Home Assistant rejected the access token"
"""The parked service's ready reason, and the cause a PARK plan carries."""

NOT_CONNECTED_REASON = "Not connected to Home Assistant"
"""The ready reason while the loop retries a lost or failed connection."""

CONNECTED_REASON = "WebSocket connected, authenticated, and subscribed"
"""The ready reason while the connection is CONNECTED."""

CORE_NOT_RUNNING_REASON = "Home Assistant core state is {}, waiting for RUNNING"
"""The ready reason while the RUNNING gate waits (D12); format with the reported core state."""

FIRST_CONNECT_HINT = "Check that base_url points at your Home Assistant instance and that it is running."
"""D11: appended to outage logs until a connection has ever succeeded."""

PROPAGATED_EXCEPTIONS: tuple[type[BaseException], ...] = (InvalidLifecycleTransitionError, MemoryError)
"""D9 Propagate: exceptions the loop never catches. Cancellation is a ``BaseException`` and
passes through on its own."""

EXPECTED_FAILURES: tuple[type[BaseException], ...] = (aiohttp.ClientError, OSError, TimeoutError, HassetteError)
"""Failures that are part of normal connection churn. Anything else is unexpected: its first
occurrence is logged with a traceback (D11)."""


class CoreShuttingDownError(HassetteError):
    """Home Assistant reported a shutting-down core state while the RUNNING gate waited."""

    def __init__(self, core_state: str) -> None:
        super().__init__(f"Home Assistant core state is {core_state}")
        self.core_state = core_state


class Disposition(StrEnum):
    """How the loop reacts to a failed connection (D9)."""

    FAST = auto()
    """Retry on the D8 curve."""

    SLOW = auto()
    """Retry at the fixed Slow pace (or a 429's ``Retry-After``)."""

    AUTH_RETRY = auto()
    """D3's spaced retries after a rejected token, before parking."""

    PARK = auto()
    """Stop retrying until the process restarts."""


@dataclass(frozen=True, slots=True)
class RetryPlan:
    """What the loop does after one failure."""

    disposition: Disposition
    delay: float | None
    """Seconds to wait before the next attempt; None when parking."""

    cause: str
    """Human-readable cause, for the log."""


@dataclass
class ReconnectPolicy:
    """Classifies connection failures and paces the next attempt (D3, D8, D9, D13)."""

    fast_attempt: int = 0
    """Fast-disposition failures since the last stable connection; drives the D8 curve."""

    oversize_streak: int = 0
    """Consecutive failures that were a 1009 close."""

    auth_rejections: int = 0
    """``auth_invalid`` answers since the last connection reached CONNECTED."""

    def on_connected(self) -> None:
        """A connection reached CONNECTED: a later auth rejection starts a fresh D3 count."""
        self.auth_rejections = 0

    def on_connection_ended(self, connected_for: float | None) -> None:
        """Reset the Fast curve and the 1009 streak if the connection that just ended was stable.

        Args:
            connected_for: Seconds the ending connection spent in CONNECTED, or None if the
                attempt never got there.
        """
        if is_stable_connection(connected_for):
            self.fast_attempt = 0
            self.oversize_streak = 0

    def on_failure(self, exc: Exception) -> RetryPlan:
        """Classify ``exc``, advance the counters it affects, and return the next step.

        Not a pure query: each call counts toward the D3 auth retries, the 1009 streak, and the
        Fast curve, so call it exactly once per failed attempt.
        """
        # Any failure other than a 1009 breaks the streak, auth rejections included.
        oversized = getattr(exc, "close_code", None) == CLOSE_CODE_MESSAGE_TOO_BIG
        self.oversize_streak = self.oversize_streak + 1 if oversized else 0

        if isinstance(exc, InvalidAuthError):
            self.auth_rejections += 1
            if self.auth_rejections > AUTH_RETRIES:
                return RetryPlan(Disposition.PARK, None, AUTH_REJECTED_REASON)
            return RetryPlan(
                Disposition.AUTH_RETRY,
                AUTH_RETRY_SECONDS,
                f"{AUTH_REJECTED_REASON} (retry {self.auth_rejections} of {AUTH_RETRIES})",
            )

        if self.oversize_streak >= OVERSIZE_STREAK_FOR_SLOW:
            return RetryPlan(
                Disposition.SLOW,
                SLOW_RETRY_SECONDS,
                f"Home Assistant sent a message larger than the {WS_MAX_MSG_SIZE // (1024 * 1024)} MiB "
                f"limit (close code {CLOSE_CODE_MESSAGE_TOO_BIG}) on {self.oversize_streak} consecutive connections",
            )

        if isinstance(exc, aiohttp.WSServerHandshakeError) and exc.status in SLOW_HANDSHAKE_STATUSES:
            delay = SLOW_RETRY_SECONDS
            if (
                exc.status == HTTPStatus.TOO_MANY_REQUESTS
                and (retry_after := parse_retry_after(exc.headers)) is not None
            ):
                # Floored at the Fast cap: a Retry-After of 0 must not turn the Slow tier into a hot loop.
                delay = max(min(retry_after, RETRY_AFTER_CAP_SECONDS), FAST_BACKOFF_CAP_SECONDS)
            return RetryPlan(Disposition.SLOW, delay, f"WebSocket handshake rejected with HTTP {exc.status}")

        # Only a certificate the client rejects is Slow: an EOF or reset mid-handshake is a TLS
        # listener restarting, and heals on its own.
        if isinstance(exc, aiohttp.ClientConnectorCertificateError | ssl.SSLCertVerificationError):
            return RetryPlan(Disposition.SLOW, SLOW_RETRY_SECONDS, f"TLS certificate rejected: {exc}")

        self.fast_attempt += 1
        return RetryPlan(Disposition.FAST, fast_backoff_delay(self.fast_attempt), describe_failure(exc))


@dataclass
class OutageLog:
    """Keeps a long outage visible at a bounded number of log rows (D11).

    An episode starts at the first failure after a stable connection (or at startup) and lasts
    until a connection survives ``STABLE_CONNECTION_SECONDS``, so a flapping link stays one
    episode. Callers pass ``now`` (a ``time.monotonic()`` reading) so pacing is testable.
    """

    logger: logging.Logger
    url: str
    episode_started_at: float | None = None
    last_summary_at: float = 0.0
    disconnected_at: float | None = None
    """Start of the current gap between connections, for the recovery line's duration."""
    gap_after_flap: bool = False
    """The current gap began with a flap, so its recovery is logged at DEBUG (the summary counts it)."""
    attempts: int = 0
    flaps: int = 0
    repeated_unexpected: int = 0
    seen_tracebacks: set[tuple[str, str]] = field(default_factory=set)

    def record_failure(
        self,
        exc: Exception,
        plan: RetryPlan,
        *,
        now: float,
        connected_for: float | None,
        has_ever_connected: bool,
    ) -> None:
        """Log one failed attempt at the level its position in the episode calls for."""
        flap = connected_for is not None and self.is_flap(connected_for)
        if connected_for is not None:
            if is_stable_connection(connected_for):
                self.episode_started_at = None
            else:
                self.flaps += 1

        first_in_episode = self.episode_started_at is None
        if first_in_episode:
            self.start_episode(now)
        if self.disconnected_at is None:
            self.disconnected_at = now
            self.gap_after_flap = flap
        self.attempts += 1

        if not isinstance(exc, EXPECTED_FAILURES):
            if self.should_log_traceback(exc):
                self.logger.warning("Unexpected error on the Home Assistant connection", exc_info=exc)
            else:
                self.repeated_unexpected += 1

        delay_text = f"{plan.delay:.0f}s" if plan.delay is not None else ""
        match plan.disposition:
            case Disposition.PARK:
                self.logger.critical(
                    "Home Assistant at %s rejected the access token. Hassette will stay up but will not "
                    "reconnect: check the token in your configuration, then restart Hassette.",
                    self.url,
                )
            case Disposition.SLOW | Disposition.AUTH_RETRY:
                self.logger.error(
                    "Cannot connect to Home Assistant at %s: %s; retrying in %s", self.url, plan.cause, delay_text
                )
            case Disposition.FAST if first_in_episode and not has_ever_connected:
                self.logger.error(
                    "Cannot reach Home Assistant at %s: %s; retrying. %s", self.url, plan.cause, FIRST_CONNECT_HINT
                )
            case Disposition.FAST if first_in_episode:
                self.logger.warning("Lost connection to Home Assistant at %s: %s; reconnecting", self.url, plan.cause)
            case Disposition.FAST:
                self.logger.debug(
                    "Connection attempt %d failed: %s; retrying in %s", self.attempts, plan.cause, delay_text
                )

        self.maybe_summarize(now, has_ever_connected=has_ever_connected)

    def record_core_wait(self, core_state: str, *, now: float, has_ever_connected: bool) -> None:
        """Note that the RUNNING gate is waiting on ``core_state`` (D12), summarizing on schedule."""
        if self.episode_started_at is None:
            self.start_episode(now)
        self.logger.debug("Home Assistant core state is %s, waiting for RUNNING", core_state)
        self.maybe_summarize(now, has_ever_connected=has_ever_connected, core_state=core_state)

    def record_connected(self, *, now: float, was_ever_connected: bool) -> None:
        """Log recovery with the gap's duration; the episode stays open until the connection proves stable.

        A recovery from a flap logs at DEBUG: the episode's summaries already count flaps (D11).
        """
        if was_ever_connected and self.disconnected_at is not None:
            level = logging.DEBUG if self.gap_after_flap else logging.INFO
            self.logger.log(
                level,
                "Reconnected to Home Assistant at %s after %s",
                self.url,
                format_duration(now - self.disconnected_at),
            )
        self.disconnected_at = None

    def is_flap(self, connected_for: float) -> bool:
        """True if a connection that lasted ``connected_for`` dropped inside an open episode.

        Its disconnect and recovery log at DEBUG; the episode's summaries count it instead (D11).
        """
        return self.episode_started_at is not None and not is_stable_connection(connected_for)

    def start_episode(self, now: float) -> None:
        self.episode_started_at = now
        self.last_summary_at = now
        self.attempts = 0
        self.flaps = 0
        self.repeated_unexpected = 0

    def summary_due(self, now: float) -> bool:
        return self.episode_started_at is not None and now - self.last_summary_at >= OUTAGE_SUMMARY_INTERVAL_SECONDS

    def maybe_summarize(self, now: float, *, has_ever_connected: bool, core_state: str | None = None) -> None:
        if not self.summary_due(now) or self.episode_started_at is None:
            return
        self.last_summary_at = now
        elapsed = format_duration(now - self.episode_started_at)
        if core_state is not None:
            self.logger.warning(
                "Home Assistant at %s is reachable; core state is %s, waiting for RUNNING (%s)",
                self.url,
                core_state,
                elapsed,
            )
            return
        details = f"{self.attempts} attempts, {self.flaps} connections dropped within {STABLE_CONNECTION_SECONDS:.0f}s"
        if self.repeated_unexpected:
            details += f", {self.repeated_unexpected} repeated unexpected errors"
        hint = "" if has_ever_connected else f". {FIRST_CONNECT_HINT}"
        # A recurring unexpected error can't heal on its own, so it reads as an error, not an outage.
        level = logging.WARNING if has_ever_connected and not self.repeated_unexpected else logging.ERROR
        self.logger.log(
            level, "Home Assistant at %s still unreachable after %s (%s)%s", self.url, elapsed, details, hint
        )

    def should_log_traceback(self, exc: BaseException) -> bool:
        """True the first time this (exception type, innermost frame) pair is seen."""
        key = traceback_key(exc)
        if key in self.seen_tracebacks:
            return False
        self.seen_tracebacks.add(key)
        return True


def is_stable_connection(connected_for: float | None) -> bool:
    """True if a connection that spent ``connected_for`` seconds in CONNECTED counts as stable (D8).

    The one stability test: it resets ``ReconnectPolicy``'s curve and ends an ``OutageLog`` episode.
    """
    return connected_for is not None and connected_for >= STABLE_CONNECTION_SECONDS


def fast_backoff_delay(attempt: int) -> float:
    """D8's jittered exponential delay for the ``attempt``-th consecutive failure (1-based).

    Jitter is applied before the cap, so no delay exceeds ``FAST_BACKOFF_CAP_SECONDS``.
    Also the StateProxy sync-retry pace (D14).
    """
    exponent = min(max(attempt - 1, 0), FAST_BACKOFF_MAX_EXPONENT)
    base = FAST_BACKOFF_INITIAL_SECONDS * FAST_BACKOFF_BASE**exponent
    jittered = base * random.uniform(1 - FAST_BACKOFF_JITTER, 1 + FAST_BACKOFF_JITTER)
    return min(jittered, FAST_BACKOFF_CAP_SECONDS)


def parse_retry_after(headers: Mapping[str, str] | None) -> float | None:
    """Return a ``Retry-After`` header's delay in seconds, or None if absent or not delta-seconds.

    The HTTP-date form is not parsed; the caller falls back to the Slow pace.
    """
    value = headers.get("Retry-After") if headers is not None else None
    # isdecimal, not isdigit: isdigit also accepts characters such as "²" that float() rejects.
    if value is None or not value.strip().isdecimal():
        return None
    return float(value.strip())


def describe_failure(exc: BaseException) -> str:
    """Name a failure for the log: its type, close code if any, and message."""
    close_code = getattr(exc, "close_code", None)
    detail = str(exc) or type(exc).__name__
    if close_code is not None:
        return f"{type(exc).__name__} (close code {close_code}): {detail}"
    return f"{type(exc).__name__}: {detail}"


def traceback_key(exc: BaseException) -> tuple[str, str]:
    """Dedupe key for unexpected-exception tracebacks: type plus innermost frame ``file:line``."""
    frames = traceback.extract_tb(exc.__traceback__)
    location = f"{frames[-1].filename}:{frames[-1].lineno}" if frames else ""
    return type(exc).__qualname__, location


def format_duration(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


async def race_recv_task(awaitable: Awaitable[_T], recv_task: asyncio.Task) -> _T:
    """Return ``awaitable``'s result, unless the recv task ends first: then raise what ended it."""
    task = asyncio.ensure_future(awaitable)
    try:
        await asyncio.wait({task, recv_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    if recv_task.done():
        if task.done() and not task.cancelled():
            task.exception()  # retrieved so a losing failure doesn't log as never retrieved
        raise_recv_task_end(recv_task)
    return task.result()


def raise_recv_task_end(recv_task: asyncio.Task) -> NoReturn:
    """Raise whatever ended a finished recv task, as the failure that ended its connection."""
    if recv_task.cancelled():
        raise RetryableConnectionClosedError("WebSocket receive loop was cancelled")
    if (exc := recv_task.exception()) is not None:
        raise exc
    raise RetryableConnectionClosedError("WebSocket receive loop ended")


async def event_set_within(event: asyncio.Event, timeout: float) -> bool:
    """True if ``event`` is set within ``timeout`` seconds."""
    # asyncio.timeout, not wait_for: on 3.11 wait_for can swallow a cancellation that lands as
    # the event is set, which would keep serve() running through shutdown.
    try:
        async with asyncio.timeout(timeout):
            await event.wait()
    except TimeoutError:
        return False
    return True
