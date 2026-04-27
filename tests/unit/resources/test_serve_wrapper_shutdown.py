"""Tests for Service._serve_wrapper handling of ClosedResourceError during shutdown."""

from anyio import ClosedResourceError

from hassette.resources.base import Service
from hassette.types.enums import ResourceStatus

from .conftest import _make_hassette_stub


class _ClosedResourceService(Service):
    """Service whose serve() raises ClosedResourceError (simulating stream closure)."""

    async def serve(self) -> None:
        raise ClosedResourceError()


class TestServeWrapperClosedResourceErrorDuringShutdown:
    """_serve_wrapper must treat ClosedResourceError as a shutdown condition when shutdown_event is set."""

    async def test_does_not_set_failed_status(self) -> None:
        """ClosedResourceError during shutdown should not produce FAILED status."""
        hassette = _make_hassette_stub()
        hassette.shutdown_event.set()

        svc = _ClosedResourceService(hassette, parent=hassette)

        await svc._serve_wrapper()

        assert svc.status != ResourceStatus.FAILED

    async def test_does_not_propagate(self) -> None:
        """ClosedResourceError during shutdown must not propagate out of _serve_wrapper."""
        hassette = _make_hassette_stub()
        hassette.shutdown_event.set()

        svc = _ClosedResourceService(hassette, parent=hassette)

        await svc._serve_wrapper()


class TestServeWrapperClosedResourceErrorOutsideShutdown:
    """ClosedResourceError outside shutdown should be treated as a failure."""

    async def test_sets_failed_status(self) -> None:
        """ClosedResourceError without shutdown_event set should produce FAILED status."""
        hassette = _make_hassette_stub()

        svc = _ClosedResourceService(hassette, parent=hassette)

        await svc._serve_wrapper()

        assert svc.status == ResourceStatus.FAILED
