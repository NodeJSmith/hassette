"""Unit tests for WaitForCancellationLog: the rate limit on non-shutdown wait_for cancellation WARNINGs."""

import logging
import types
import typing

import pytest

from hassette.bus.wait_for_cancellations import WAIT_FOR_CANCEL_WARN_INTERVAL_SECONDS, WaitForCancellationLog

if typing.TYPE_CHECKING:
    from hassette.bus.listeners import Listener

LOGGER_NAME = "hassette.test.wait_for_cancellations"


def _listener(name: str) -> "Listener":
    identity = types.SimpleNamespace(name=name, app_key="test_app", instance_index=0)
    return typing.cast("Listener", types.SimpleNamespace(identity=identity, topic="test.topic", db_id=1))


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_warns_again_after_interval_with_suppressed_count(caplog: pytest.LogCaptureFixture) -> None:
    """Cancellations inside the interval log at DEBUG; the next WARNING after it reports how many were demoted."""
    now = [0.0]
    log = WaitForCancellationLog(logging.getLogger(LOGGER_NAME), clock=lambda: now[0])

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        log.record(_listener("first"), still_pending=3)
        now[0] = WAIT_FOR_CANCEL_WARN_INTERVAL_SECONDS / 2
        log.record(_listener("second"), still_pending=2)
        log.record(_listener("third"), still_pending=1)
        now[0] = WAIT_FOR_CANCEL_WARN_INTERVAL_SECONDS + 1
        log.record(_listener("fourth"), still_pending=0)

    warnings = _warnings(caplog)
    assert len(warnings) == 2
    assert "'first'" in warnings[0]
    assert "earlier cancellation(s)" not in warnings[0]
    assert "'fourth'" in warnings[1]
    assert "2 earlier cancellation(s) were logged at DEBUG" in warnings[1]
    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(debug) == 2
    assert "'second'" in debug[0]
    assert "'third'" in debug[1]
