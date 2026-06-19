"""Parity test: every ListenerRegistration field must have a source on ListenerIdentity or ListenerOptions.

Without this test, future ListenerRegistration additions can silently skip adding the corresponding
field to the decomposed sub-structs.

Uses dataclass field inspection (``dataclasses.fields()``) which works correctly for dataclasses,
unlike ``__annotations__`` inspection on Protocol classes (which returns an empty dict for pure-method
Protocols). Both ``ListenerRegistration`` (frozen dataclass) and the sub-structs (slots dataclasses)
expose their fields correctly via ``dataclasses.fields()``.
"""

import dataclasses

from hassette.bus.listeners import ListenerIdentity, ListenerOptions
from hassette.core.registration import ListenerRegistration

# Fields on ListenerRegistration that do NOT have a direct field name match on ListenerIdentity or ListenerOptions.
# Each entry must have a comment explaining why it is exempt.
EXEMPTIONS: set[str] = {
    # Routing / structural fields — not identity or behavioral parameters
    "topic",  # the event topic; a routing field set by Bus.on(), not a telemetry identity field
    # Renamed fields — present on a sub-struct under a different name
    "handler_method",  # sourced from ListenerIdentity.handler_name (different name for the DB column)
    # Computed at registration time by BusService, not stored on sub-structs
    "predicate_description",  # repr(listener.predicate), computed from Listener.predicate at registration
    "human_description",  # summarize_top_level(listener.predicate), computed from Listener.predicate at registration
    # Duration fields sourced from DurationConfig, not ListenerIdentity or ListenerOptions
    "immediate",  # DurationConfig.immediate — duration concern, not behavioral option or identity
    "duration",  # DurationConfig.duration — duration concern, not behavioral option or identity
    "entity_id",  # DurationConfig.entity_id — duration concern, not behavioral option or identity
}

# All field names on ListenerIdentity
IDENTITY_FIELDS: set[str] = {f.name for f in dataclasses.fields(ListenerIdentity)}

# All field names on ListenerOptions
OPTIONS_FIELDS: set[str] = {f.name for f in dataclasses.fields(ListenerOptions)}

# Fields covered by either sub-struct
COVERED_FIELDS: set[str] = IDENTITY_FIELDS | OPTIONS_FIELDS


def test_listener_registration_fields_have_sub_struct_source() -> None:
    """Every non-exempted ListenerRegistration field must exist on ListenerIdentity or ListenerOptions.

    When a new field is added to ListenerRegistration, this test forces the developer to either:
    (a) add the field to the appropriate sub-struct (preferred), or
    (b) add it to EXEMPTIONS with a comment explaining why it cannot be on a sub-struct.

    This enforces the parity between the registration DTO and the decomposed sub-structs.
    """
    reg_fields = {f.name for f in dataclasses.fields(ListenerRegistration)}
    non_exempted = reg_fields - EXEMPTIONS

    missing = non_exempted - COVERED_FIELDS
    assert not missing, (
        f"ListenerRegistration fields have no source on ListenerIdentity or ListenerOptions: "
        f"{sorted(missing)}. "
        f"Either add the field to the appropriate sub-struct, or add it to EXEMPTIONS in this test "
        f"with a comment explaining why it cannot be on a sub-struct."
    )


def test_exemptions_are_not_vacuous() -> None:
    """Sanity check: all exempted fields must actually exist on ListenerRegistration.

    Prevents stale entries in EXEMPTIONS from silently masking regressions.
    """
    reg_fields = {f.name for f in dataclasses.fields(ListenerRegistration)}
    stale = EXEMPTIONS - reg_fields
    assert not stale, (
        f"EXEMPTIONS contains fields not present on ListenerRegistration: {sorted(stale)}. Remove them from EXEMPTIONS."
    )


def test_identity_fields_are_non_empty() -> None:
    """Sanity check: ListenerIdentity must expose at least one field.

    Without this guard, the main parity test could pass vacuously if a refactor broke
    field discovery on ListenerIdentity.
    """
    assert len(IDENTITY_FIELDS) > 0, (
        "IDENTITY_FIELDS is empty. The parity test would pass vacuously. Investigate ListenerIdentity field discovery."
    )


def test_options_fields_are_non_empty() -> None:
    """Sanity check: ListenerOptions must expose at least one field.

    Without this guard, the main parity test could pass vacuously if a refactor broke
    field discovery on ListenerOptions.
    """
    assert len(OPTIONS_FIELDS) > 0, (
        "OPTIONS_FIELDS is empty. The parity test would pass vacuously. Investigate ListenerOptions field discovery."
    )
