"""Tests for how many ERROR records a failed non-app initialization produces.

A non-app resource whose ``on_initialize()`` raises must surface that exception at ERROR exactly
once (``handle_failed()``'s "<resource> failed" record, with the traceback). The initialization
coordinator's exception observer and ``start()``'s joiner observer see the same exception object
and log it at DEBUG instead (#3501).
"""

import asyncio
import logging

import pytest
from hassette_wire import ResourceStatus

from hassette.resources.lifecycle import start
from hassette.testing import wait_for
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ConcreteResource


class FailingInitResource(ConcreteResource):
    """Resource whose ``on_initialize()`` always raises."""

    async def on_initialize(self) -> None:
        raise RuntimeError("init boom")


def make_failing_resource() -> FailingInitResource:
    resource = FailingInitResource(hassette=make_mock_hassette(sealed=False))
    resource.lifecycle_logger.setLevel(logging.DEBUG)
    return resource


def lifecycle_records(caplog: pytest.LogCaptureFixture, resource: ConcreteResource) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == resource.lifecycle_logger.name]


def assert_single_error_traceback(records: list[logging.LogRecord]) -> None:
    errors = [record for record in records if record.levelno >= logging.ERROR]
    assert len(errors) == 1, f"expected one ERROR record, got {[r.getMessage() for r in errors]}"
    assert "init boom" in errors[0].getMessage()
    assert errors[0].exc_info is not None, "the surviving ERROR record must carry the traceback"

    debug_messages = [record.getMessage() for record in records if record.levelno == logging.DEBUG]
    assert any("unhandled exception" in message for message in debug_messages), (
        "the observer log should be demoted to DEBUG, not removed"
    )


async def test_direct_initialize_failure_logs_one_error(caplog: pytest.LogCaptureFixture) -> None:
    resource = make_failing_resource()

    with caplog.at_level(logging.DEBUG, logger=resource.lifecycle_logger.name):
        with pytest.raises(RuntimeError, match="init boom"):
            await resource.initialize()
        await asyncio.sleep(0)  # let the coordinator's done callbacks run

    assert resource.status == ResourceStatus.FAILED
    assert_single_error_traceback(lifecycle_records(caplog, resource))


async def test_start_failure_logs_one_error(caplog: pytest.LogCaptureFixture) -> None:
    resource = make_failing_resource()

    with caplog.at_level(logging.DEBUG, logger=resource.lifecycle_logger.name):
        start(resource)
        await wait_for(lambda: resource._pending_start_task is None, desc="start joiner settled")
        await asyncio.sleep(0)

    assert resource.status == ResourceStatus.FAILED
    records = lifecycle_records(caplog, resource)
    assert_single_error_traceback(records)
    assert any("start joiner" in r.getMessage() for r in records if r.levelno == logging.DEBUG), (
        "the start joiner's observer should log the re-raised exception at DEBUG"
    )


async def test_observer_keeps_error_when_handle_failed_never_ran(caplog: pytest.LogCaptureFixture) -> None:
    """A body failure outside ``handle_failed()`` still reaches ERROR through the coordinator observer."""
    resource = ConcreteResource(hassette=make_mock_hassette(sealed=False))
    resource.lifecycle_logger.setLevel(logging.DEBUG)
    # handle_starting()'s status event succeeds; handle_running()'s raises -- a body failure
    # that never goes through handle_failed().
    resource.hassette.send_event.side_effect = [None, RuntimeError("init boom")]  # pyright: ignore[reportAttributeAccessIssue]

    with caplog.at_level(logging.DEBUG, logger=resource.lifecycle_logger.name):
        with pytest.raises(RuntimeError, match="init boom"):
            await resource.initialize()
        await asyncio.sleep(0)

    errors = [r for r in caplog.records if r.name == resource.lifecycle_logger.name and r.levelno >= logging.ERROR]
    assert len(errors) == 1, [r.getMessage() for r in errors]
    assert "unhandled exception" in errors[0].getMessage()
    assert errors[0].exc_info is not None


async def test_observer_keeps_error_when_handle_failed_raises_a_different_exception(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``handle_failed()`` logs the dependency failure, then its own status-event send raises.

    The coordinator propagates that second exception, which nothing has logged yet, so the
    observer must keep it at ERROR even though the resource ended the attempt in FAILED.
    """
    resource = ConcreteResource(hassette=make_mock_hassette(sealed=False))
    resource.lifecycle_logger.setLevel(logging.DEBUG)

    async def failing_dependency_wait() -> None:
        raise RuntimeError("dependency boom")

    monkeypatch.setattr(resource, "_auto_wait_dependencies", failing_dependency_wait)
    # handle_starting()'s status event succeeds; handle_failed()'s raises.
    resource.hassette.send_event.side_effect = [None, RuntimeError("event boom")]  # pyright: ignore[reportAttributeAccessIssue]

    with caplog.at_level(logging.DEBUG, logger=resource.lifecycle_logger.name):
        with pytest.raises(RuntimeError, match="event boom"):
            await resource.initialize()
        await asyncio.sleep(0)

    assert resource.status == ResourceStatus.FAILED
    errors = [r for r in caplog.records if r.name == resource.lifecycle_logger.name and r.levelno >= logging.ERROR]
    logged = [r.exc_info[1] for r in errors if r.exc_info is not None]
    assert [str(exc) for exc in logged] == ["dependency boom", "event boom"], [r.getMessage() for r in errors]
