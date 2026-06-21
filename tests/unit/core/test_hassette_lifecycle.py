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


class TestServiceAccessorGuards:
    """Service accessors raise a RuntimeError naming the missing service before wiring."""

    @pytest.mark.parametrize(
        ("accessor", "service"),
        [
            ("database_service", "DatabaseService"),
            ("scheduler_service", "SchedulerService"),
            ("bus_service", "BusService"),
            ("state_proxy", "StateProxy"),
            ("api", "Api"),
            ("states", "StateManager"),
        ],
    )
    def test_accessor_before_wiring_names_service(self, test_config, accessor: str, service: str) -> None:
        """Reading a service accessor before wire_services() names the service and the startup fix."""
        h = Hassette(test_config)
        with pytest.raises(RuntimeError, match=service) as exc_info:
            getattr(h, accessor)
        assert "wire_services()" in str(exc_info.value)


class TestNonRaisingAccessors:
    """loop_thread_id and try_state_proxy() return None before wiring instead of raising."""

    def test_loop_thread_id_is_none_before_run_forever(self, test_config) -> None:
        """loop_thread_id is None until run_forever() captures the loop thread ident."""
        assert Hassette(test_config).loop_thread_id is None

    def test_try_state_proxy_is_none_before_wiring(self, test_config) -> None:
        """try_state_proxy() returns None before wiring rather than raising."""
        assert Hassette(test_config).try_state_proxy() is None
