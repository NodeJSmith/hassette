from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel
from whenever import Instant


class HistoryEntry(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    entity_id: str
    state: Any
    attributes: dict[str, Any] | None
    last_changed: Instant
    last_updated: Instant


def normalize_history(entries: Any) -> list[list[dict[str, Any]]]:
    if not isinstance(entries, Sequence) or not all(isinstance(e, list) for e in entries):
        entries = [entries]  # Wrap in a list if not already a list of lists

    normalized_entries: list[list[dict[str, Any]]] = []

    for entity_history in entries:
        if not entity_history:
            continue

        normalized_list = []

        # Use the first entry as the base for later updates
        base_entry = entity_history[0]

        for delta_entry in entity_history:
            # if we have the same set of keys then we don't need to use the base entries
            # as we already have everything we need
            # this happens when minimal_response is not set
            if set(base_entry.keys()) == set(delta_entry.keys()):
                normalized_list.append(delta_entry)
                continue

            merged = base_entry.copy() | delta_entry
            normalized_list.append(merged)

        if normalized_list:
            normalized_entries.append(normalized_list)

    return normalized_entries
