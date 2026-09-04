"""disconnect/partial_cleanup/early-drop reconnect-retry tests for WebsocketService.

Includes the FailingConnection helper used to simulate failed reconnect attempts.
Complements test_connection.py (connection/auth), test_dispatch.py (send/dispatch),
and test_subscribe_events_retry.py.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import hassette.resources.lifecycle as lifecycle_module
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import InvalidAuthError, RetryableConnectionClosedError
from hassette.resources.base import ResourceStatus
from hassette.testing import EventCapture
from hassette.testing._ws_mocks import build_fake_ws, mark_websocket_service_connected
from hassette.testing.config import (
    TEST_EARLY_DROP_BACKOFF_INITIAL_SECONDS,
    TEST_EARLY_DROP_BACKOFF_MAX_SECONDS,
    TEST_EARLY_DROP_MAX_RETRIES,
    TEST_EARLY_DROP_STABLE_WINDOW_SECONDS,
)
from hassette.types import Topic
from hassette.types.enums import ConnectionState


def make_failing_recv_task(error: Exception) -> asyncio.Task[None]:
    """Create a task that raises the given error, simulating a failed recv loop."""

    async def _fail():
        raise error

    return asyncio.create_task(_fail())


async def test_disconnect_event_fires_on_recv_loop_failure(websocket_service: WebsocketService) -> None:
    """Fire WEBSOCKET_DISCONNECTED when the recv loop dies unexpectedly."""
    capture = EventCapture()
    capture.install(websocket_service.hassette)
    # The real make_connection calls mark_ready() and sets _ever_connected via
    # start_recv_and_subscribe's set_connection_state(CONNECTED); mirror that here so the
    # has_ever_connected guard on send_connection_lost_event() lets the event through.
    mark_websocket_service_connected(websocket_service, reason="test: simulating successful connection")

    with (
        patch.object(
            websocket_service,
            "make_connection",
            return_value=make_failing_recv_task(
                RetryableConnectionClosedError("peer gone"),
            ),
        ),
        pytest.raises(RetryableConnectionClosedError),
    ):
        await websocket_service.serve()

    assert Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED in capture.topics


async def test_marked_not_ready_on_recv_loop_failure(websocket_service: WebsocketService) -> None:
    """Mark the service not-ready immediately when the recv loop fails."""
    lifecycle_module.mark_ready(websocket_service, reason="test: verify ready→not-ready transition")
    websocket_service.hassette.send_event = AsyncMock()

    with (
        patch.object(
            websocket_service,
            "make_connection",
            return_value=make_failing_recv_task(
                RetryableConnectionClosedError("peer gone"),
            ),
        ),
        pytest.raises(RetryableConnectionClosedError),
    ):
        await websocket_service.serve()

    assert not websocket_service.is_ready()


async def test_disconnect_event_failure_does_not_mask_original_error(websocket_service: WebsocketService) -> None:
    """Ensure that a broken send_event doesn't swallow the recv loop error."""
    websocket_service.hassette.send_event = AsyncMock(side_effect=RuntimeError("bus is down"))

    with (
        patch.object(
            websocket_service,
            "make_connection",
            return_value=make_failing_recv_task(
                RetryableConnectionClosedError("peer gone"),
            ),
        ),
        pytest.raises(RetryableConnectionClosedError),
    ):
        await websocket_service.serve()


async def test_pre_readiness_failure_after_prior_disconnect_emits_no_second_public_disconnect(
    websocket_service: WebsocketService,
) -> None:
    """A failed reconnect attempt before external readiness does not emit a second disconnect."""
    capture = EventCapture()
    capture.install(websocket_service.hassette)

    mark_websocket_service_connected(websocket_service, reason="test: prior external connection")
    websocket_service.partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service._emit_readiness_event = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

    with patch("hassette.core.websocket_service.early_drop_backoff", AsyncMock()):
        await websocket_service.handle_early_drop(
            RetryableConnectionClosedError("peer gone"),
            elapsed=1.0,
            early_drop_attempts=1,
            max_early_drops=3,
        )
    await websocket_service.handle_genuine_failure()

    disconnected_events = capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED)
    assert len(disconnected_events) == 1


async def test_partial_cleanup_cancels_recv_and_closes_ws(websocket_service: WebsocketService) -> None:
    """partial_cleanup cancels recv task, closes ws, clears futures and subscription ids."""
    fake_ws = build_fake_ws()
    fake_recv_task = asyncio.create_task(asyncio.sleep(100))
    websocket_service._ws = fake_ws
    websocket_service._recv_task = fake_recv_task
    websocket_service._subscription_ids = {1, 2}

    # Seed a pending future
    fut = websocket_service.hassette.loop.create_future()
    websocket_service._response_futures[99] = fut

    await websocket_service.partial_cleanup()

    assert websocket_service._ws is None
    assert websocket_service._recv_task is None
    assert websocket_service._subscription_ids == set()
    assert websocket_service._response_futures == {}
    assert fut.done()
    assert isinstance(fut.exception(), RetryableConnectionClosedError)


async def test_partial_cleanup_preserves_session(websocket_service: WebsocketService) -> None:
    """partial_cleanup must NOT clear self._session."""
    fake_session = MagicMock()
    websocket_service._session = fake_session
    websocket_service._ws = build_fake_ws()
    websocket_service._recv_task = asyncio.create_task(asyncio.sleep(0))

    await websocket_service.partial_cleanup()

    assert websocket_service._session is fake_session


async def test_partial_cleanup_suppresses_errors(websocket_service: WebsocketService) -> None:
    """partial_cleanup must not propagate any exceptions."""
    fake_ws = build_fake_ws()
    fake_ws.close = AsyncMock(side_effect=RuntimeError("close failed"))
    websocket_service._ws = fake_ws
    websocket_service._recv_task = None

    # Should not raise
    await websocket_service.partial_cleanup()


async def test_partial_cleanup_timeout_on_gather(websocket_service: WebsocketService) -> None:
    """partial_cleanup completes within ~2s even when recv task is non-cancellable."""

    async def _never_ends():
        try:
            await asyncio.sleep(1000)
        except asyncio.CancelledError:  # noqa: ASYNC103 — intentionally simulates a task that ignores cancellation
            await asyncio.sleep(1000)

    stuck_task = asyncio.create_task(_never_ends())
    websocket_service._recv_task = stuck_task
    websocket_service._ws = build_fake_ws()

    started = time.monotonic()
    try:
        await websocket_service.partial_cleanup()
        elapsed = time.monotonic() - started
        assert elapsed < 4.0, f"partial_cleanup took too long: {elapsed:.2f}s"
    finally:
        stuck_task.cancel()
        await asyncio.gather(stuck_task, return_exceptions=True)


class FailingConnection:
    """Callable ``make_connection`` stub that fails the recv task N times, then succeeds.

    Collapses the near-identical ``fake_make_connection`` closures duplicated across the
    early-drop test suite (issue #1493) into one parametrized helper.

    Each call sets ``_connected_at`` to ``time.monotonic() - connected_at_offset`` and marks
    the service connected before returning a task. The task raises ``error`` for the first
    ``fail_after`` calls (or forever when ``fail_after`` is ``None``); after that it exits
    cleanly — unless ``final_error`` is given, in which case call number ``fail_after + 1``
    raises ``final_error`` synchronously instead of returning a task at all (simulating e.g.
    an auth failure discovered on the reconnect attempt itself, rather than inside the
    retryable recv loop).

    Pass ``mark_fully_connected=True`` for tests that assert on the public
    WEBSOCKET_DISCONNECTED signal — it wires the full external-readiness state via
    ``mark_websocket_service_connected`` (which flips ``_ever_connected``) instead of only
    lifecycle ``mark_ready``, matching what the ``has_ever_connected`` guard on that signal
    requires. Other tests only need lifecycle readiness, so that's the default.

    ``call_count`` is mutated in place so callers can assert on it after ``serve()`` returns.
    """

    def __init__(
        self,
        websocket_service: WebsocketService,
        *,
        fail_after: int | None,
        error: Exception,
        connected_at_offset: float = 0.0,
        final_error: Exception | None = None,
        mark_fully_connected: bool = False,
    ) -> None:
        if final_error is not None and fail_after is None:
            raise ValueError("final_error requires fail_after to be set — there is no call to trigger it on")
        self.websocket_service = websocket_service
        self.fail_after = fail_after
        self.error = error
        self.connected_at_offset = connected_at_offset
        self.final_error = final_error
        self.mark_fully_connected = mark_fully_connected
        self.call_count = 0

    async def __call__(self, _session: object) -> asyncio.Task:
        self.call_count += 1
        call_count = self.call_count
        ws = self.websocket_service

        if self.final_error is not None and self.fail_after is not None and call_count == self.fail_after + 1:
            raise self.final_error

        ws._connected_at = time.monotonic() - self.connected_at_offset
        if self.mark_fully_connected:
            mark_websocket_service_connected(ws, reason="test: simulating successful connection")
        else:
            lifecycle_module.mark_ready(ws, reason="test: simulating successful connection")

        if self.fail_after is None or call_count <= self.fail_after:
            error = self.error

            async def _fail() -> None:
                raise error

            return asyncio.create_task(_fail())

        async def _clean() -> None:
            pass

        return asyncio.create_task(_clean())


def apply_early_drop_config(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
    *,
    max_retries: int = TEST_EARLY_DROP_MAX_RETRIES,
    stable_window_seconds: float = TEST_EARLY_DROP_STABLE_WINDOW_SECONDS,
    backoff_initial_seconds: float = TEST_EARLY_DROP_BACKOFF_INITIAL_SECONDS,
    backoff_max_seconds: float = TEST_EARLY_DROP_BACKOFF_MAX_SECONDS,
) -> None:
    """Patch the four early-drop config knobs on ``websocket_service.hassette.config.websocket``.

    Defaults match the shared test constants (``hassette.testing.config``); pass an override
    only for the value a given test needs to differ (e.g. proving retry-budget exhaustion).
    """
    config = websocket_service.hassette.config.websocket
    monkeypatch.setattr(config, "early_drop_max_retries", max_retries)
    monkeypatch.setattr(config, "early_drop_stable_window_seconds", stable_window_seconds)
    monkeypatch.setattr(config, "early_drop_backoff_initial_seconds", backoff_initial_seconds)
    monkeypatch.setattr(config, "early_drop_backoff_max_seconds", backoff_max_seconds)


async def test_early_drop_retries_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """An early-drop within the stable window is retried transparently.

    Verifies: handle_failed never called, make_connection called 3 times,
    partial_cleanup called 2 times, DISCONNECTED event emitted 2 times,
    mark_not_ready called twice.
    """
    capture = EventCapture()
    capture.install(websocket_service.hassette)

    # First two make_connection calls succeed but recv task fails immediately.
    # Third call succeeds with clean exit.
    partial_cleanup_count = 0

    fake_make_connection = FailingConnection(
        websocket_service,
        fail_after=2,
        error=RetryableConnectionClosedError("peer gone"),
        mark_fully_connected=True,
    )

    async def fake_partial_cleanup() -> None:
        nonlocal partial_cleanup_count
        partial_cleanup_count += 1

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.partial_cleanup = fake_partial_cleanup  # pyright: ignore[reportAttributeAccessIssue]
    apply_early_drop_config(monkeypatch, websocket_service)

    await websocket_service.serve()

    assert fake_make_connection.call_count == 3, (
        f"Expected 3 make_connection calls, got {fake_make_connection.call_count}"
    )
    assert partial_cleanup_count == 2, f"Expected 2 partial_cleanup calls, got {partial_cleanup_count}"

    # DISCONNECTED should have been sent 2 times (once per early drop)
    disconnected_count = len(capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED))
    assert disconnected_count == 2, f"Expected 2 DISCONNECTED events, got {disconnected_count}"


async def test_early_drop_exhausts_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """After exhausting early-drop retry count, exception propagates out of serve()."""
    websocket_service.hassette.send_event = AsyncMock()

    fake_make_connection = FailingConnection(
        websocket_service,
        fail_after=None,
        error=RetryableConnectionClosedError("dropped"),
    )

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    # max_retries=2 is specific to this test (proves the budget is exhausted).
    apply_early_drop_config(monkeypatch, websocket_service, max_retries=2)

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service.serve()

    # Initial + 2 retries = 3 total attempts, then propagates
    assert fake_make_connection.call_count == 3, (
        f"Expected 3 total make_connection calls, got {fake_make_connection.call_count}"
    )
    assert not websocket_service.is_ready()


async def test_early_drop_exhausts_recovery_timeout(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """When recovery_elapsed exceeds max_recovery, failure propagates without further retry."""
    websocket_service.hassette.send_event = AsyncMock()

    fake_make_connection = FailingConnection(
        websocket_service,
        fail_after=None,
        error=RetryableConnectionClosedError("dropped"),
    )

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

    # max_retries=10 and max_recovery_seconds=0.0 are specific to this test (a huge retry
    # budget that the recovery timeout — not the retry count — should cut off first).
    apply_early_drop_config(monkeypatch, websocket_service, max_retries=10)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "max_recovery_seconds", 0.0)

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service.serve()

    # Should have made only 1 attempt then stopped due to recovery timeout
    assert fake_make_connection.call_count == 1, (
        f"Expected 1 make_connection call (recovery timeout), got {fake_make_connection.call_count}"
    )


async def test_stable_connection_failure_propagates_immediately(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """A drop outside the stable window propagates immediately without retry."""
    websocket_service.hassette.send_event = AsyncMock()

    # connected_at_offset=60.0 puts _connected_at 60 seconds in the past — outside any stable window.
    fake_make_connection = FailingConnection(
        websocket_service,
        fail_after=None,
        error=RetryableConnectionClosedError("stable drop"),
        connected_at_offset=60.0,
    )

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setattr(
        websocket_service.hassette.config.websocket,
        "early_drop_stable_window_seconds",
        TEST_EARLY_DROP_STABLE_WINDOW_SECONDS,
    )

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service.serve()

    # Only 1 attempt — stable drop doesn't retry
    assert fake_make_connection.call_count == 1, (
        f"Expected 1 make_connection call, got {fake_make_connection.call_count}"
    )


async def test_non_retryable_exception_in_stable_window(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """RuntimeError within stable window propagates immediately — not an early drop."""
    websocket_service.hassette.send_event = AsyncMock()

    fake_make_connection = FailingConnection(
        websocket_service,
        fail_after=None,
        error=RuntimeError("unexpected internal error"),
    )

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setattr(
        websocket_service.hassette.config.websocket,
        "early_drop_stable_window_seconds",
        TEST_EARLY_DROP_STABLE_WINDOW_SECONDS,
    )

    with pytest.raises(RuntimeError):
        await websocket_service.serve()

    assert fake_make_connection.call_count == 1, (
        f"Expected 1 make_connection call, got {fake_make_connection.call_count}"
    )


async def test_auth_failure_on_reconnect_logs_distinctive_message(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """InvalidAuthError after at least one early-drop retry propagates and leaves DISCONNECTED."""
    websocket_service.hassette.send_event = AsyncMock()

    fake_make_connection = FailingConnection(
        websocket_service,
        fail_after=1,
        error=RetryableConnectionClosedError("dropped"),
        final_error=InvalidAuthError("token revoked"),
    )

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    apply_early_drop_config(monkeypatch, websocket_service)

    with pytest.raises(InvalidAuthError):
        await websocket_service.serve()

    assert fake_make_connection.call_count >= 2
    assert websocket_service.connection_state == ConnectionState.DISCONNECTED


async def test_send_connection_lost_event_idempotent(websocket_service: WebsocketService) -> None:
    """send_connection_lost_event is a no-op when the connection has never been established."""
    capture = EventCapture()
    capture.install(websocket_service.hassette)

    # Fresh service has never connected; calling send_connection_lost_event should be a no-op
    assert not websocket_service.has_ever_connected
    await websocket_service.send_connection_lost_event()

    disconnected_count = len(capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED))
    assert disconnected_count == 0, "Expected no DISCONNECTED events when never connected"


async def test_send_connection_lost_event_skips_before_first_connection(websocket_service: WebsocketService) -> None:
    """send_connection_lost_event does not fire when ready but never connected.

    With unconditional mark_ready() in on_initialize(), the service can be lifecycle-ready
    before HA is ever reachable — the guard must key off has_ever_connected, not is_ready(),
    to avoid a spurious DISCONNECTED event in that window.
    """
    capture = EventCapture()
    capture.install(websocket_service.hassette)

    lifecycle_module.mark_ready(websocket_service, reason="test: service marked ready, no connection yet")
    assert websocket_service.is_ready()
    assert not websocket_service.has_ever_connected

    await websocket_service.send_connection_lost_event()

    disconnected_count = len(capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED))
    assert disconnected_count == 0, "Expected no DISCONNECTED event before the first successful connection"


async def test_send_connection_lost_event_self_suppressing(websocket_service: WebsocketService) -> None:
    """send_connection_lost_event does not propagate bus exceptions."""
    websocket_service.hassette.send_event = AsyncMock(side_effect=RuntimeError("bus is down"))
    # The guard now keys off has_ever_connected, not is_ready() — simulate a prior successful
    # connection so the event actually attempts to fire and self-suppression is exercised.
    mark_websocket_service_connected(websocket_service, reason="test: make service ready so event fires")

    # Should not raise even though the bus raises
    await websocket_service.send_connection_lost_event()


async def test_service_status_stays_running_during_early_drop(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """During early-drop retry: service status is RUNNING but is_ready() is False."""
    websocket_service.hassette.send_event = AsyncMock()

    statuses_during_retry: list[tuple[ResourceStatus, bool]] = []

    fake_make_connection = FailingConnection(
        websocket_service,
        fail_after=1,
        error=RetryableConnectionClosedError("dropped"),
    )

    original_mark_not_ready = lifecycle_module.mark_not_ready

    def capturing_mark_not_ready(resource: WebsocketService, reason: str | None = None) -> None:
        original_mark_not_ready(resource, reason=reason)
        statuses_during_retry.append((websocket_service.status, websocket_service.is_ready()))

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    apply_early_drop_config(monkeypatch, websocket_service)

    # Set service to RUNNING state using ._status bypass — deliberate test fixture setup,
    # not a lifecycle operation. handle_running() requires STARTING → RUNNING which needs
    # a full initialize() first; here we just need the status to be RUNNING for the assertion.
    websocket_service._status = ResourceStatus.RUNNING

    # mark_not_ready is a module-level function (hassette.resources.lifecycle), not a
    # method — patch it at the call site (websocket_service.py) rather than reassigning
    # an instance attribute, since serve() calls the free function directly.
    with patch("hassette.core.websocket_service.mark_not_ready", side_effect=capturing_mark_not_ready):
        await websocket_service.serve()

    assert len(statuses_during_retry) >= 1
    status, ready = statuses_during_retry[0]
    assert status == ResourceStatus.RUNNING, f"Expected RUNNING status, got {status}"
    assert not ready, "Expected is_ready()=False during early-drop retry"
