"""Regression test for the config_log_all_events hot-reload freeze.

config_log_all_events was a @cached_property, so the first dispatch froze the
value and later config hot-reloads were ignored. Its sibling config_log_level
is a live @property; this pins config_log_all_events to the same behavior.
"""

from hassette.core.bus_service import BusService
from hassette.resources.base import Resource
from hassette.test_utils import make_mock_hassette


def stub_bus_service() -> BusService:
    hassette = make_mock_hassette(
        sealed=False,
        logging={"bus_service": "WARNING"},
        lifecycle={"resource_shutdown_timeout_seconds": 5, "task_cancellation_timeout_seconds": 5},
    )
    obj = BusService.__new__(BusService)
    Resource.__init__(obj, hassette, parent=hassette)
    return obj


def test_config_log_all_events_reflects_hot_reload() -> None:
    """config_log_all_events must re-read config on each access, not freeze on first read."""
    bus = stub_bus_service()

    bus.hassette.config.logging.all_events = False
    assert bus.config_log_all_events is False

    # Simulate a config hot-reload after the value has been read once.
    bus.hassette.config.logging.all_events = True
    assert bus.config_log_all_events is True
