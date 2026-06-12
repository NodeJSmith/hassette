"""Parity test: RecordingApi must implement every write method that Api does.

This test is in a separate file from test_recording_sync_facade_drift.py so
that WP04's deletion of the old drift test does not accidentally remove this
parity check as collateral damage.
"""

from hassette_codegen.sync_facade import LIFECYCLE_METHODS

from hassette.api.api import Api
from hassette.test_utils.recording_api import RecordingApi
from tests.unit.conftest import public_async_methods

# Read-method names — these are excluded from the write-method derivation below.
# Lifecycle hooks are handled separately via LIFECYCLE_METHODS (imported above) so
# this set only needs to enumerate actual read methods, not hook overrides.
#
# Identifying write vs read methods: any method that mutates HA state or fires
# an event is a write method. The authoritative list lives in ApiProtocol, which
# labels them with a "# Write methods" comment.
KNOWN_READ_METHODS: frozenset[str] = frozenset(
    {
        "get_state",
        "get_states",
        "get_entity",
        "get_entity_or_none",
        "entity_exists",
        "get_state_or_none",
        "get_state_raw",
        "get_state_value",
        "get_state_value_typed",
        "get_attribute",
        "get_states_raw",
        "get_config",
        "get_services",
        "get_panels",
        "get_history",
        "get_histories",
        "get_logbook",
        "get_camera_image",
        "get_calendars",
        "get_calendar_events",
        "render_template",
        "ws_send_and_wait",
        "ws_send_json",
        "rest_request",
        "get_rest_request",
        "post_rest_request",
        "delete_rest_request",
        "list_input_booleans",
        "list_input_numbers",
        "list_input_texts",
        "list_input_selects",
        "list_input_datetimes",
        "list_input_buttons",
        "list_counters",
        "list_timers",
    }
)


def test_api_write_methods_covered_by_recording_api() -> None:
    """RecordingApi must implement every write method that Api defines.

    When Api gains a new write method, RecordingApi must be updated to record
    calls to it. This test fails if Api has a write method that RecordingApi
    lacks, preventing silent gaps in the recording contract.

    Write methods are identified by excluding the known-read method set from
    Api's full public async method set. ApiProtocol is used to verify
    RecordingApi's conformance at import time (see the module-level cast in
    recording_api.py), so this test focuses specifically on write-method coverage.
    """
    api_async_methods = public_async_methods(Api)
    recording_api_async_methods = public_async_methods(RecordingApi)

    # Derive write methods: Api's public async methods minus read methods and
    # lifecycle hooks. This is conservative — if Api has a new method we haven't
    # classified, it will appear here and force an explicit classification decision.
    write_methods_on_api = api_async_methods - KNOWN_READ_METHODS - LIFECYCLE_METHODS

    missing = write_methods_on_api - recording_api_async_methods
    assert not missing, (
        f"RecordingApi is missing write methods present in Api: {sorted(missing)}. "
        f"Add them to src/hassette/test_utils/recording_api.py and update "
        f"KNOWN_READ_METHODS in this file if the new method is actually a read method."
    )
