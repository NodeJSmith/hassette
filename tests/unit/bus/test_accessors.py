"""Tests for hassette.event_handling.accessors (the A.* API).

Covers accessors not already exercised in test_predicates.py: state/attr object
accessors, multi-attribute accessors, get_all_changes diffing, get_domain/get_entity_id
fallback branches across event types, get_context, and get_service/get_service_data.
"""

from types import SimpleNamespace

from hassette.const import MISSING_VALUE
from hassette.event_handling import accessors as A
from hassette.test_utils import create_call_service_event, create_state_change_event
from hassette.test_utils.helpers import create_component_loaded_event, create_hass_event


# get_state_object_* accessors
def test_get_state_object_old_and_new_return_full_dicts() -> None:
    """get_state_object_old/new return the full state dict, not just the value."""
    event = create_state_change_event(
        entity_id="light.kitchen",
        old_value="off",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    old_obj = A.get_state_object_old(event)
    new_obj = A.get_state_object_new(event)

    assert old_obj is not None
    assert new_obj is not None
    assert old_obj["state"] == "off"
    assert old_obj["attributes"] == {"brightness": 100}
    assert new_obj["state"] == "on"
    assert new_obj["attributes"] == {"brightness": 200}


def test_get_state_object_old_is_none_when_entity_created() -> None:
    """get_state_object_old returns None when the entity has no prior state."""
    event = create_state_change_event(entity_id="light.new", old_value=None, new_value="on")

    assert A.get_state_object_old(event) is None
    assert A.get_state_object_new(event) is not None


def test_get_state_object_new_is_none_when_entity_removed() -> None:
    """get_state_object_new returns None when the entity was removed."""
    event = create_state_change_event(entity_id="light.gone", old_value="on", new_value=None)

    assert A.get_state_object_new(event) is None
    assert A.get_state_object_old(event) is not None


def test_get_state_object_old_new_returns_tuple() -> None:
    """get_state_object_old_new returns a (old, new) tuple of full state dicts."""
    event = create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on")

    old_obj, new_obj = A.get_state_object_old_new(event)

    assert old_obj is not None
    assert old_obj["state"] == "off"
    assert new_obj is not None
    assert new_obj["state"] == "on"


# get_attrs_* (multi-attribute) accessors
def test_get_attrs_new_returns_requested_keys_only() -> None:
    """get_attrs_new extracts only the requested attribute names."""
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        new_attrs={"brightness": 200, "color": "blue", "effect": "none"},
    )

    accessor = A.get_attrs_new(["brightness", "color"])
    result = accessor(event)

    assert result == {"brightness": 200, "color": "blue"}
    assert "effect" not in result


def test_get_attrs_new_missing_key_returns_missing_value() -> None:
    """get_attrs_new fills MISSING_VALUE for attributes not present on the new state."""
    event = create_state_change_event(
        entity_id="light.office", old_value="on", new_value="on", new_attrs={"brightness": 200}
    )

    accessor = A.get_attrs_new(["brightness", "not_there"])
    result = accessor(event)

    assert result == {"brightness": 200, "not_there": MISSING_VALUE}


def test_get_attrs_old_returns_requested_keys_only() -> None:
    """get_attrs_old extracts only the requested attribute names from the old state."""
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="off",
        old_attrs={"brightness": 100, "color": "red"},
    )

    accessor = A.get_attrs_old(["brightness"])
    result = accessor(event)

    assert result == {"brightness": 100}


def test_get_attrs_new_when_new_state_is_none() -> None:
    """get_attrs_new returns MISSING_VALUE for all requested keys when new_state is None."""
    event = create_state_change_event(entity_id="light.gone", old_value="on", new_value=None)

    accessor = A.get_attrs_new(["brightness"])
    result = accessor(event)

    assert result == {"brightness": MISSING_VALUE}


def test_get_attrs_old_new_returns_tuple_of_dicts() -> None:
    """get_attrs_old_new returns (old_attrs_dict, new_attrs_dict) for the requested keys."""
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    accessor = A.get_attrs_old_new(["brightness"])
    old_attrs, new_attrs = accessor(event)

    assert old_attrs == {"brightness": 100}
    assert new_attrs == {"brightness": 200}


# get_all_attrs_* accessors
def test_get_all_attrs_new_returns_full_attribute_dict() -> None:
    """get_all_attrs_new returns every attribute on the new state, not a filtered subset."""
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        new_attrs={"brightness": 200, "color": "blue"},
    )

    result = A.get_all_attrs_new(event)

    assert result == {"brightness": 200, "color": "blue"}


def test_get_all_attrs_old_returns_missing_value_when_old_state_none() -> None:
    """get_all_attrs_old returns MISSING_VALUE (not an empty dict) when old_state is None."""
    event = create_state_change_event(entity_id="light.new", old_value=None, new_value="on")

    assert A.get_all_attrs_old(event) is MISSING_VALUE


def test_get_all_attrs_new_returns_missing_value_when_new_state_none() -> None:
    """get_all_attrs_new returns MISSING_VALUE when new_state is None (entity removed)."""
    event = create_state_change_event(entity_id="light.gone", old_value="on", new_value=None)

    assert A.get_all_attrs_new(event) is MISSING_VALUE


def test_get_all_attrs_old_new_returns_tuple() -> None:
    """get_all_attrs_old_new returns a tuple of the full old and new attribute dicts."""
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200, "color": "blue"},
    )

    old_attrs, new_attrs = A.get_all_attrs_old_new(event)

    assert old_attrs == {"brightness": 100}
    assert new_attrs == {"brightness": 200, "color": "blue"}


# get_domain / get_entity_id across event types
def test_get_domain_from_state_change_event() -> None:
    """get_domain extracts the domain from a RawStateChangeEvent's entity_id."""
    event = create_state_change_event(entity_id="sensor.temperature", old_value="20", new_value="21")

    assert A.get_domain(event) == "sensor"


def test_get_domain_from_call_service_event() -> None:
    """get_domain reads the domain directly off a CallServiceEvent's payload data."""
    event = create_call_service_event(domain="light", service="turn_on")

    assert A.get_domain(event) == "light"


def test_get_domain_returns_missing_value_when_no_domain_or_entity_id() -> None:
    """get_domain falls through to MISSING_VALUE for events with neither a domain nor entity_id."""
    event = create_component_loaded_event(component="mqtt")

    assert A.get_domain(event) is MISSING_VALUE


def test_get_domain_falls_back_to_entity_id_split_when_no_domain_field() -> None:
    """get_domain derives the domain from entity_id for event types with no explicit domain field.

    automation_triggered events carry entity_id but no domain key, and aren't a RawStateChangeEvent
    (whose payload has its own domain property), so get_domain must fall back to splitting entity_id.
    """
    event = create_hass_event("automation_triggered", {"name": "Morning routine", "entity_id": "automation.morning"})

    assert A.get_domain(event) == "automation"


def test_get_entity_id_from_call_service_event_service_data() -> None:
    """get_entity_id falls back to service_data['entity_id'] for CallServiceEvent."""
    event = create_call_service_event(domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"})

    assert A.get_entity_id(event) == "light.kitchen"


def test_get_entity_id_missing_for_call_service_event_without_entity_id() -> None:
    """get_entity_id returns MISSING_VALUE when service_data has no entity_id key."""
    event = create_call_service_event(domain="light", service="turn_on", service_data={"brightness": 255})

    assert A.get_entity_id(event) is MISSING_VALUE


def test_get_entity_id_missing_for_unrelated_event() -> None:
    """get_entity_id returns MISSING_VALUE for events with no entity_id path at all."""
    event = create_component_loaded_event(component="mqtt")

    assert A.get_entity_id(event) is MISSING_VALUE


# get_context
def test_get_context_returns_context_object() -> None:
    """get_context extracts the HassContext object carrying id/parent_id/user_id from an event."""
    event = create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on")

    context = A.get_context(event)

    assert context.id
    assert context.parent_id is None
    assert context.user_id is None


# get_service / get_service_data
def test_get_service_returns_service_name() -> None:
    """get_service extracts the service name from a CallServiceEvent."""
    event = create_call_service_event(domain="light", service="turn_on")

    assert A.get_service(event) == "turn_on"


def test_get_service_data_returns_full_dict() -> None:
    """get_service_data returns the full service_data dict."""
    event = create_call_service_event(
        domain="light", service="turn_on", service_data={"entity_id": "light.kitchen", "brightness": 255}
    )

    assert A.get_service_data(event) == {"entity_id": "light.kitchen", "brightness": 255}


def test_get_service_data_empty_dict_when_no_service_data() -> None:
    """get_service_data returns an empty dict (not MISSING_VALUE) when service_data was omitted."""
    event = create_call_service_event(domain="light", service="turn_on")

    assert A.get_service_data(event) == {}


def test_get_service_data_key_missing_when_service_data_itself_missing() -> None:
    """get_service_data_key short-circuits to MISSING_VALUE when service_data can't be found at all.

    CallServicePayload always defaults service_data to {}, so this exercises the short-circuit
    branch directly against a bare object that has no service_data attribute at all.
    """
    fake_event = SimpleNamespace(payload=SimpleNamespace(data=SimpleNamespace()))

    accessor = A.get_service_data_key("entity_id")

    assert accessor(fake_event) is MISSING_VALUE  # pyright: ignore[reportArgumentType]


# get_all_changes / _recursive_get_differences
def test_get_all_changes_detects_state_and_attribute_changes() -> None:
    """get_all_changes reports both the top-level state change and nested attribute changes."""
    event = create_state_change_event(
        entity_id="light.office",
        old_value="off",
        new_value="on",
        old_attrs={"brightness": 100, "color": "red"},
        new_attrs={"brightness": 200, "color": "red"},
    )

    changes = A.get_all_changes()(event)

    assert changes["state"] == ("off", "on")
    assert changes["attributes"]["brightness"] == (100, 200)
    assert "color" not in changes["attributes"]


def test_get_all_changes_excludes_default_noisy_fields() -> None:
    """get_all_changes excludes last_changed/last_updated/context by default even when they differ."""
    event = create_state_change_event(entity_id="light.office", old_value="on", new_value="on")

    changes = A.get_all_changes()(event)

    # state unchanged, and noisy always-different fields (last_changed, etc.) are excluded
    assert "state" not in changes
    assert changes["attributes"] == {}


def test_get_all_changes_respects_custom_exclude() -> None:
    """get_all_changes with a narrower exclude list surfaces fields the default would hide."""
    event = create_state_change_event(
        entity_id="light.office",
        old_value="off",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    # Exclude nothing this time, but only inspect the attributes key for a clean assertion
    changes = A.get_all_changes(exclude=())(event)

    assert changes["state"] == ("off", "on")
    assert changes["attributes"]["brightness"] == (100, 200)


def test_get_all_changes_handles_added_and_removed_keys() -> None:
    """get_all_changes treats a key only on one side as changed from/to MISSING_VALUE."""
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"removed_attr": "gone"},
        new_attrs={"added_attr": "new"},
    )

    changes = A.get_all_changes()(event)

    assert changes["attributes"]["removed_attr"] == ("gone", MISSING_VALUE)
    assert changes["attributes"]["added_attr"] == (MISSING_VALUE, "new")


def test_recursive_get_differences_direct() -> None:
    """_recursive_get_differences returns a nested diff dict, recursing into nested dicts only."""
    old = {"a": 1, "b": {"x": 1, "y": 2}, "unchanged": "same"}
    new = {"a": 2, "b": {"x": 1, "y": 3}, "unchanged": "same"}

    diff = A._recursive_get_differences(old, new)

    assert diff == {"a": (1, 2), "b": {"y": (2, 3)}}
    assert "unchanged" not in diff
