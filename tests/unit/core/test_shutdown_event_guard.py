"""Tests for send_event guard when event streams are closed."""

from types import SimpleNamespace

from hassette.core.core import Hassette
from hassette.test_utils.helpers import cleanup_hassette_streams


class TestSendEventAfterStreamsClosed:
    """send_event() must silently drop events when event streams are closed."""

    async def test_send_event_does_not_raise_when_streams_closed(self, test_config) -> None:
        """Calling send_event() after close_streams() must not raise."""
        config = test_config.model_copy(update={"run_app_precheck": False})
        h = Hassette(config)
        h.wire_services()
        try:
            assert h._event_stream_service is not None
            await h._bus_service.stream.aclose()
            await h._event_stream_service.close_streams()
            assert h.event_streams_closed is True

            await h.send_event(SimpleNamespace(topic="test.guard"))  # pyright: ignore[reportArgumentType]
        finally:
            await cleanup_hassette_streams(h)

    async def test_send_event_works_before_streams_closed(self, test_config) -> None:
        """send_event() must still work normally when streams are open."""
        config = test_config.model_copy(update={"run_app_precheck": False})
        h = Hassette(config)
        h.wire_services()
        try:
            assert h.event_streams_closed is False
            await h.send_event(SimpleNamespace(topic="test.guard"))  # pyright: ignore[reportArgumentType]
        finally:
            await cleanup_hassette_streams(h)
