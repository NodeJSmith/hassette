"""Tests for unified event ID and origin fields across payload types."""

import uuid

import whenever

from hassette.events.base import EventPayload, HassContext, HassettePayload, HassPayload


def test_hassette_payload_event_id_is_uuid_string() -> None:
    """HassettePayload.event_id must be a valid UUID4 string."""
    payload = HassettePayload(data=None)
    assert isinstance(payload.event_id, str)
    parsed = uuid.UUID(payload.event_id, version=4)
    assert str(parsed) == payload.event_id


def test_hassette_payload_event_id_is_unique() -> None:
    """Each HassettePayload instance must get a unique event_id."""
    p1 = HassettePayload(data=None)
    p2 = HassettePayload(data=None)
    assert p1.event_id != p2.event_id


def test_hassette_payload_origin_is_hassette() -> None:
    """HassettePayload.origin must be 'HASSETTE'."""
    payload = HassettePayload(data=None)
    assert payload.origin == "HASSETTE"


def test_hass_payload_event_id_matches_context_id() -> None:
    """HassPayload.event_id must equal context.id."""
    ctx = HassContext(id="abc-123", parent_id=None, user_id=None)
    payload = HassPayload(
        event_type="state_changed",
        data=None,
        origin="LOCAL",
        time_fired=whenever.ZonedDateTime(2024, 1, 1, tz="UTC"),
        context=ctx,
    )
    assert payload.event_id == "abc-123"


def test_hass_payload_origin_is_literal() -> None:
    """HassPayload.origin must reflect the construction value (LOCAL or REMOTE)."""
    ctx = HassContext(id="xyz", parent_id=None, user_id=None)
    local_payload = HassPayload(
        event_type="state_changed",
        data=None,
        origin="LOCAL",
        time_fired=whenever.ZonedDateTime(2024, 1, 1, tz="UTC"),
        context=ctx,
    )
    remote_payload = HassPayload(
        event_type="state_changed",
        data=None,
        origin="REMOTE",
        time_fired=whenever.ZonedDateTime(2024, 1, 1, tz="UTC"),
        context=ctx,
    )
    assert local_payload.origin == "LOCAL"
    assert remote_payload.origin == "REMOTE"


def test_event_payload_base_has_origin_default() -> None:
    """EventPayload base must default origin to 'UNKNOWN'."""
    payload = EventPayload(data=None)
    assert payload.origin == "UNKNOWN"
