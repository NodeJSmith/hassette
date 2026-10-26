"""Tests for how Service._serve_wrapper records serve()'s end and reports failures (spec 134 D8)."""

import asyncio
from typing import Any, ClassVar

import pytest
from anyio import ClosedResourceError
from hassette_wire import ResourceStatus

from hassette.exceptions import ServeEndedError
from hassette.resources.service import Service
from tests.support.mock_hassette import make_mock_hassette


class ClosedResourceService(Service):
    """Service whose serve() raises ClosedResourceError (simulating stream closure)."""

    required = False

    async def serve(self) -> None:
        raise ClosedResourceError()


class TestServeWrapperClosedResourceErrorDuringShutdown:
    """_serve_wrapper must treat ClosedResourceError as a shutdown condition when shutdown_event is set."""

    async def test_does_not_set_failed_status(self) -> None:
        """ClosedResourceError during shutdown should not produce FAILED status."""
        hassette = make_mock_hassette(sealed=False)
        hassette.shutdown_event.set()

        svc = ClosedResourceService(hassette, parent=hassette)

        await svc._serve_wrapper()

        assert svc.status != ResourceStatus.FAILED

    async def test_does_not_propagate(self) -> None:
        """ClosedResourceError during shutdown must not propagate out of _serve_wrapper."""
        hassette = make_mock_hassette(sealed=False)
        hassette.shutdown_event.set()

        svc = ClosedResourceService(hassette, parent=hassette)

        await svc._serve_wrapper()


class TestServeWrapperClosedResourceErrorOnOwnShutdown:
    async def test_optional_service_own_shutdown_is_a_quiet_stop(self) -> None:
        """An optional service stopped on its own (its app reloading) ends STOPPED when its stream closes."""
        hassette = make_mock_hassette(sealed=False)
        svc = ClosedResourceService(hassette, parent=hassette)
        svc.shutdown_event.set()

        await svc._serve_wrapper()

        assert svc.status == ResourceStatus.STOPPED
        hassette.report_service_failure.assert_not_called()


class TestServeWrapperClosedResourceErrorOutsideShutdown:
    """ClosedResourceError outside shutdown should be treated as a failure."""

    async def test_sets_failed_status(self) -> None:
        """ClosedResourceError without shutdown_event set should produce FAILED status."""
        hassette = make_mock_hassette(sealed=False)

        svc = ClosedResourceService(hassette, parent=hassette)

        await svc._serve_wrapper()

        assert svc.status == ResourceStatus.FAILED

    async def test_reports_the_failure(self) -> None:
        hassette = make_mock_hassette(sealed=False)

        svc = ClosedResourceService(hassette, parent=hassette)

        await svc._serve_wrapper()

        hassette.report_service_failure.assert_called_once()
        assert hassette.report_service_failure.call_args.args[0] is svc


class _ReturningRequired(Service):
    required: ClassVar[bool] = True

    async def serve(self) -> None:
        return


class _ReturningOptional(Service):
    required: ClassVar[bool] = False

    async def serve(self) -> None:
        return


class TestServeReturnsWithoutShutdown:
    async def test_required_service_return_is_a_reported_failure(self) -> None:
        """A required service can't stop silently: an unrequested return is FAILED, not STOPPED."""
        hassette = make_mock_hassette(sealed=False)
        svc = _ReturningRequired(hassette, parent=hassette)

        await svc._serve_wrapper()

        assert svc.status == ResourceStatus.FAILED
        hassette.report_service_failure.assert_called_once()
        reported_service, reported_exc = hassette.report_service_failure.call_args.args
        assert reported_service is svc
        assert isinstance(reported_exc, ServeEndedError)

    async def test_optional_service_return_is_a_quiet_stop(self) -> None:
        """An optional service with nothing to do (no directories to watch) is STOPPED and not reported."""
        hassette = make_mock_hassette(sealed=False)
        svc = _ReturningOptional(hassette, parent=hassette)

        await svc._serve_wrapper()

        assert svc.status == ResourceStatus.STOPPED
        hassette.report_service_failure.assert_not_called()

    async def test_required_service_return_after_shutdown_requested_is_a_stop(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        hassette.shutdown_event.set()
        svc = _ReturningRequired(hassette, parent=hassette)

        await svc._serve_wrapper()

        assert svc.status == ResourceStatus.STOPPED
        hassette.report_service_failure.assert_not_called()

    async def test_required_service_return_on_its_own_shutdown_alone_is_a_reported_failure(self) -> None:
        """Only the process-level shutdown event makes a stop requested; the service's own doesn't (D8)."""
        hassette = make_mock_hassette(sealed=False)
        svc = _ReturningRequired(hassette, parent=hassette)
        svc.shutdown_event.set()

        await svc._serve_wrapper()

        assert svc.status == ResourceStatus.FAILED
        hassette.report_service_failure.assert_called_once()


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


async def assert_cancel_propagates(svc: _BlockingService) -> None:
    """Run ``svc._serve_wrapper()`` until serve() is entered, cancel it, and assert the cancel propagates."""
    task = asyncio.create_task(svc._serve_wrapper())
    await asyncio.wait_for(svc.entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


class TestServeCancelledWithoutShutdown:
    async def test_required_service_cancel_is_a_reported_failure(self) -> None:
        """A required service cancelled with no shutdown requested is FAILED and reported, and the cancel propagates."""
        hassette = make_mock_hassette(sealed=False)
        svc = _BlockingRequired(hassette, parent=hassette)

        await assert_cancel_propagates(svc)

        assert svc.status == ResourceStatus.FAILED
        hassette.report_service_failure.assert_called_once()
        reported_service, reported_exc = hassette.report_service_failure.call_args.args
        assert reported_service is svc
        assert isinstance(reported_exc, ServeEndedError)

    async def test_optional_service_cancel_is_a_quiet_stop(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        svc = _BlockingOptional(hassette, parent=hassette)

        await assert_cancel_propagates(svc)

        assert svc.status == ResourceStatus.STOPPED
        hassette.report_service_failure.assert_not_called()

    async def test_required_service_cancel_after_shutdown_requested_is_a_stop(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        hassette.shutdown_event.set()
        svc = _BlockingRequired(hassette, parent=hassette)

        await assert_cancel_propagates(svc)

        assert svc.status == ResourceStatus.STOPPED
        hassette.report_service_failure.assert_not_called()
