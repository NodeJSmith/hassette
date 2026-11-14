"""Tests for normalize_history's expansion of minimal-response history entries."""

from whenever import Instant

from hassette.models.history import HistoryEntry, normalize_history

BASE_ENTRY = {
    "entity_id": "light.x",
    "state": "on",
    "attributes": {"friendly_name": "X"},
    "last_changed": "2026-01-01T00:00:00Z",
    "last_updated": "2026-01-01T00:00:00Z",
}


def test_merged_delta_takes_last_updated_from_its_last_changed() -> None:
    """A minimal delta without last_updated gets its own last_changed, not the first entry's."""
    raw = [[BASE_ENTRY, {"state": "off", "last_changed": "2026-01-01T05:00:00Z"}]]

    entry = HistoryEntry.model_validate(normalize_history(raw)[0][1])

    assert entry.state == "off"
    assert entry.last_changed == Instant.parse_iso("2026-01-01T05:00:00Z")
    assert entry.last_updated == entry.last_changed
    assert entry.attributes == BASE_ENTRY["attributes"]


def test_merged_delta_keeps_its_own_last_updated() -> None:
    """A delta that carries last_updated keeps it."""
    delta = {"state": "off", "last_changed": "2026-01-01T05:00:00Z", "last_updated": "2026-01-01T06:00:00Z"}

    merged = normalize_history([[BASE_ENTRY, delta]])[0][1]

    assert merged["last_updated"] == "2026-01-01T06:00:00Z"
