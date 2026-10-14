"""Bus debug-event logging re-reads its config flags on every event, so config hot-reload is honored."""

from hassette.core.bus_service import BusService
from hassette.resources.base import Resource
from tests.support.factories import make_hass_event, make_hassette_event
from tests.support.mock_hassette import make_mock_hassette


def stub_bus_service() -> BusService:
    hassette = make_mock_hassette(
        sealed=False,
        logging={"bus_service": "WARNING"},
        lifecycle={"resource_shutdown_timeout_seconds": 5, "task_cancellation_timeout_seconds": 5},
    )
    obj = BusService.__new__(BusService)
    Resource.__init__(obj, hassette, parent=hassette)
    return obj


def test_should_log_event_reflects_hot_reload() -> None:
    """Each flag gates its own topic family and is read live, not frozen on first read."""
    bus = stub_bus_service()
    hass_event = make_hass_event()
    hassette_event = make_hassette_event()

    assert bus.should_log_event(hass_event) is False
    assert bus.should_log_event(hassette_event) is False

    # Simulate a config hot-reload after the values have been read once.
    bus.hassette.config.logging.all_hass_events = True
    assert bus.should_log_event(hass_event) is True
    assert bus.should_log_event(hassette_event) is False

    bus.hassette.config.logging.all_hassette_events = True
    assert bus.should_log_event(hassette_event) is True
