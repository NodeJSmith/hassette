"""Unit tests for Hassette two-phase construction lifecycle guards."""

import pytest

from hassette.core.core import Hassette


class TestRunForeverWithoutWireServices:
    """run_forever() must raise RuntimeError when wire_services() has not been called."""

    async def test_run_forever_without_wire_services_raises(self, test_config) -> None:
        """Bare Hassette(config) without wire_services() must raise RuntimeError."""
        h = Hassette(test_config)
        with pytest.raises(RuntimeError, match="call wire_services\\(\\) before run_forever\\(\\)"):
            await h.run_forever()


class TestEventStreamsClosedBeforeWiring:
    """event_streams_closed returns True when _event_stream_service is None."""

    def test_event_streams_closed_before_wiring(self, test_config) -> None:
        """Bare Hassette(config) without wire_services() must report event streams as closed."""
        h = Hassette(test_config)
        assert h.event_streams_closed is True
