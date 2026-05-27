"""Tests for HassettePayload.time_fired timestamp field."""

from pathlib import Path

import whenever

from hassette.events.base import HassettePayload
from hassette.events.hassette import (
    HassetteFileWatcherEvent,
    HassetteServiceEvent,
    HassetteSimpleEvent,
)
from hassette.types import ResourceRole, ResourceStatus, Topic


def test_time_fired_auto_populated_as_zoned_datetime() -> None:
    payload = HassettePayload(event_type="test", data=None)
    assert isinstance(payload.time_fired, whenever.ZonedDateTime)


def test_time_fired_is_utc() -> None:
    payload = HassettePayload(event_type="test", data=None)
    assert payload.time_fired.tz == "UTC"


def test_time_fired_is_recent() -> None:
    before = whenever.Instant.now()
    payload = HassettePayload(event_type="test", data=None)
    after = whenever.Instant.now()

    fired_instant = payload.time_fired.to_instant()
    assert before <= fired_instant <= after


def test_time_fired_can_be_overridden() -> None:
    custom_time = whenever.ZonedDateTime(2024, 6, 15, 12, 0, 0, tz="UTC")
    payload = HassettePayload(event_type="test", data=None, time_fired=custom_time)
    assert payload.time_fired == custom_time


def test_hassette_service_event_has_time_fired() -> None:
    event = HassetteServiceEvent.from_data(
        resource_name="test-service",
        role=ResourceRole.SERVICE,
        status=ResourceStatus.RUNNING,
    )
    assert isinstance(event.payload.time_fired, whenever.ZonedDateTime)


def test_hassette_simple_event_has_time_fired() -> None:
    event = HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED)
    assert isinstance(event.payload.time_fired, whenever.ZonedDateTime)


def test_hassette_file_watcher_event_has_time_fired() -> None:
    event = HassetteFileWatcherEvent.create_event(changed_file_paths={Path("/tmp/foo.py")})
    assert isinstance(event.payload.time_fired, whenever.ZonedDateTime)


def test_hassette_repr_includes_time_fired() -> None:
    payload = HassettePayload(event_type="test", data=None)
    r = repr(payload)
    assert "time_fired=" in r
    assert "event_id=" in r
