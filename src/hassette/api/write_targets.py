"""How a recorded service call's target and data are derived from what the caller passed (spec 149 D3).

Home Assistant merges ``target`` into the service data, so the same call can name its entities either way. A write
record stores the ids Home Assistant acts on in one ``target`` column, whichever way they were passed, and the rest
of the service data as ``data``.
"""

from collections.abc import Mapping
from typing import Any

SERVICE_TARGET_KEYS = ("entity_id", "device_id", "area_id", "floor_id", "label_id")
"""Home Assistant's service-call target keys, lifted into a write's ``target`` wherever the caller passed them."""


def service_call_target(
    target: Mapping[str, Any] | None, service_data: Mapping[str, Any]
) -> dict[str, list[str]] | None:
    """The ids a service call acts on, merged the way Home Assistant merges them.

    Home Assistant copies ``target`` into the service data, so a key in ``target`` replaces the same key passed
    as service data. ``entity_id`` values are split on commas, stripped and lowercased, as Home Assistant's
    entity-id validator does; the other keys only become lists.
    """
    merged: dict[str, list[str]] = {}
    for key in SERVICE_TARGET_KEYS:
        if target is not None and target.get(key) is not None:
            value = target[key]
        elif service_data.get(key) is not None:
            value = service_data[key]
        else:
            continue
        merged[key] = target_ids(key, value)
    return merged or None


def target_ids(key: str, value: Any) -> list[str]:
    """One target key's value as a list of ids."""
    items = [value] if isinstance(value, str) or not isinstance(value, list | tuple) else list(value)
    if key != "entity_id":
        return [str(item) for item in items]
    ids: list[str] = []
    for item in items:
        ids.extend(part.strip().lower() for part in str(item).split(",") if part.strip())
    return ids


def service_call_data(service_data: Mapping[str, Any]) -> dict[str, Any] | None:
    """The service data without the target keys ``service_call_target`` lifted out; None when nothing is left."""
    rest = {key: value for key, value in service_data.items() if key not in SERVICE_TARGET_KEYS}
    return rest or None
