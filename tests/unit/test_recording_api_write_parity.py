"""Parity test: RecordingApi must implement every write method that Api does.

This test is in a separate file from test_recording_sync_facade_drift.py so
that WP04's deletion of the old drift test does not accidentally remove this
parity check as collateral damage.
"""

import inspect

from hassette.api.api import Api
from hassette.test_utils.recording_api import RecordingApi

# Write-method names from ApiProtocol (the source-of-truth for what RecordingApi
# must implement). These are derived from the "# Write methods" section of
# ApiProtocol and must be updated if Api gains new write methods.
#
# Identifying write vs read methods: any method that mutates HA state or fires
# an event is a write method. The authoritative list lives in ApiProtocol, which
# labels them with a "# Write methods" comment.
_KNOWN_READ_METHODS: frozenset[str] = frozenset(
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
        "get_states_iterator",
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
    }
)


def _public_async_methods(cls: type) -> set[str]:
    """Return public async method names defined on cls or its non-Resource ancestors.

    Excludes methods that start with underscore.
    """
    return {
        name
        for name, member in inspect.getmembers(cls, predicate=inspect.iscoroutinefunction)
        if not name.startswith("_")
    }


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
    api_async_methods = _public_async_methods(Api)
    recording_api_async_methods = _public_async_methods(RecordingApi)

    # Derive write methods: Api's public async methods minus the known-read set.
    # This is conservative — if Api has a new method we haven't classified, it
    # will appear here and force an explicit classification decision.
    write_methods_on_api = api_async_methods - _KNOWN_READ_METHODS

    missing = write_methods_on_api - recording_api_async_methods
    assert not missing, (
        f"RecordingApi is missing write methods present in Api: {sorted(missing)}. "
        f"Add them to src/hassette/test_utils/recording_api.py and update "
        f"_KNOWN_READ_METHODS in this file if the new method is actually a read method."
    )
