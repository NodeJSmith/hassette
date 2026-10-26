"""Tests for how Service._serve_wrapper records serve()'s end and reports failures (spec 134 D8)."""

import asyncio
from typing import Any, ClassVar

import pytest
from anyio import ClosedResourceError
from hassette_wire import ResourceStatus

from hassette.exceptions import ServeEndedError
from hassette.resources.service import Service
from tests.support.mock_hassette import make_mock_hassette


class _ClosedStreamOptional(Service):
    """Service whose serve() raises ClosedResourceError (simulating stream closure)."""

    required: ClassVar[bool] = False

    async def serve(self) -> None:
        raise ClosedResourceError()


class _ReturningRequired(Service):
    required: ClassVar[bool] = True

    async def serve(self) -> None:
        return


class _ReturningOptional(Service):
    required: ClassVar[bool] = False

    async def serve(self) -> None:
        return


class _BlockingService(Service):
    """Service whose serve() signals ``entered`` and then waits until cancelled."""

    # __init_subclass__ requires every concrete Service to declare this; the subclasses below set the real value.
    required: ClassVar[bool] = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.entered = asyncio.Event()

    async def serve(self) -> None:
        self.entered.set()
        await asyncio.Event().wait()


class _BlockingRequired(_BlockingService):
    required: ClassVar[bool] = True


class _BlockingOptional(_BlockingService):
    required: ClassVar[bool] = False


async def run_serve_wrapper(svc: Service) -> None:
    """Run ``svc._serve_wrapper()`` to its end; a blocking service is cancelled once serve() is entered.

    A cancelled wrapper must re-raise the cancellation, whatever it records.
    """
    if not isinstance(svc, _BlockingService):
        await svc._serve_wrapper()
        return
    task = asyncio.create_task(svc._serve_wrapper())
    await asyncio.wait_for(svc.entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# (service class, process shutdown set, own shutdown set, expected status, reported exception type or None)
SERVE_END_CASES = [
    pytest.param(_ClosedStreamOptional, True, False, ResourceStatus.STOPPED, None, id="closed-stream-during-shutdown"),
    pytest.param(
        _ClosedStreamOptional, False, True, ResourceStatus.STOPPED, None, id="closed-stream-optional-own-stop"
    ),
    pytest.param(
        _ClosedStreamOptional, False, False, ResourceStatus.FAILED, ClosedResourceError, id="closed-stream-unrequested"
    ),
    pytest.param(_ReturningRequired, False, False, ResourceStatus.FAILED, ServeEndedError, id="required-return"),
    pytest.param(_ReturningOptional, False, False, ResourceStatus.STOPPED, None, id="optional-return"),
    pytest.param(_ReturningRequired, True, False, ResourceStatus.STOPPED, None, id="required-return-during-shutdown"),
    # Only the process-level shutdown event makes a required service's stop requested, not its own (D8).
    pytest.param(
        _ReturningRequired, False, True, ResourceStatus.FAILED, ServeEndedError, id="required-return-own-stop"
    ),
    pytest.param(_BlockingRequired, False, False, ResourceStatus.FAILED, ServeEndedError, id="required-cancel"),
    pytest.param(_BlockingOptional, False, False, ResourceStatus.STOPPED, None, id="optional-cancel"),
    pytest.param(_BlockingRequired, True, False, ResourceStatus.STOPPED, None, id="required-cancel-during-shutdown"),
]


@pytest.mark.parametrize(
    ("service_cls", "process_shutdown", "own_shutdown", "expected_status", "reported_exc_type"), SERVE_END_CASES
)
async def test_serve_end_status_and_report(
    service_cls: type[Service],
    process_shutdown: bool,
    own_shutdown: bool,
    expected_status: ResourceStatus,
    reported_exc_type: type[BaseException] | None,
) -> None:
    """A requested stop ends STOPPED with no report; any other end of a required service is a reported failure."""
    hassette = make_mock_hassette(sealed=False)
    if process_shutdown:
        hassette.shutdown_event.set()
    svc = service_cls(hassette, parent=hassette)
    if own_shutdown:
        svc.shutdown_event.set()

    await run_serve_wrapper(svc)

    assert svc.status == expected_status
    if reported_exc_type is None:
        hassette.report_service_failure.assert_not_called()
        return
    hassette.report_service_failure.assert_called_once()
    reported_service, reported_exc = hassette.report_service_failure.call_args.args
    assert reported_service is svc
    assert isinstance(reported_exc, reported_exc_type)
