from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel
from whenever import Instant


class HistoryEntry(BaseModel):
    """A single history entry for an entity."""

    entity_id: str
    state: Any
    attributes: dict[str, Any] | None
    last_changed: Instant
    last_updated: Instant


def normalize_history(entries: Any) -> list[list[dict[str, Any]]]:
    """Expand Home Assistant history responses into complete per-entity entry lists.

    Minimal responses only carry changed keys after the first entry, so each later entry is
    merged over the entity's first entry, taking ``last_updated`` from the entry's own
    ``last_changed`` when it carries none. A single entity's list is wrapped as one group, and
    empty groups are dropped.

    Args:
        entries: Raw history payload, either a list of per-entity lists or a single list.

    Returns:
        One list of fully populated entry dicts per entity.
    """
    groups = entries if isinstance(entries, Sequence) and all(isinstance(e, list) for e in entries) else [entries]

    normalized_entries: list[list[dict[str, Any]]] = []

    for entity_history in groups:
        if not entity_history:
            continue

        entity_entries: list[dict[str, Any]] = []

        # Use the first entry as the base for later updates
        base_entry = entity_history[0]

        for delta_entry in entity_history:
            # Full (non-minimal) responses already carry every key; minimal ones need the base merged in.
            if set(base_entry) == set(delta_entry):
                entry = delta_entry
            else:
                entry = base_entry | delta_entry
                # Minimal entries are state changes, which set both timestamps; without this the
                # merged entry would keep the first entry's last_updated.
                entry["last_updated"] = delta_entry.get("last_updated", delta_entry["last_changed"])
            entity_entries.append(entry)

        normalized_entries.append(entity_entries)

    return normalized_entries
