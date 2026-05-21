"""Tests for Service._serve_wrapper handling of ClosedResourceError during shutdown."""

from anyio import ClosedResourceError

from hassette.resources.base import RestartSpec, Service
from hassette.test_utils import make_mock_hassette
from hassette.types.enums import ResourceStatus


class ClosedResourceService(Service):
    """Service whose serve() raises ClosedResourceError (simulating stream closure)."""

    restart_spec = RestartSpec()

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


class TestServeWrapperClosedResourceErrorOutsideShutdown:
    """ClosedResourceError outside shutdown should be treated as a failure."""

    async def test_sets_failed_status(self) -> None:
        """ClosedResourceError without shutdown_event set should produce FAILED status."""
        hassette = make_mock_hassette(sealed=False)

        svc = ClosedResourceService(hassette, parent=hassette)

        await svc._serve_wrapper()

        assert svc.status == ResourceStatus.FAILED
