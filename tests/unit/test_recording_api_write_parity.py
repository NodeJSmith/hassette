"""Parity test: RecordingApi must implement every write method that Api does.

This test is in a separate file from test_recording_sync_facade_drift.py so
that WP04's deletion of the old drift test does not accidentally remove this
parity check as collateral damage.
"""

import inspect
import sys
from pathlib import Path

from hassette.api.api import Api
from hassette.test_utils.recording_api import RecordingApi

# Import LIFECYCLE_METHODS from the generator so this test shares the exact same
# set of lifecycle hook names with the generator's filtering logic. Without this,
# an override of a lifecycle hook (e.g. on_initialize) on either Api or RecordingApi
# would be miscategorized by the parity test as a "write method" and pass or fail
# based on whether the other side happens to also override it — a brittle coincidence.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools"))
from generate_sync_facade import LIFECYCLE_METHODS  # noqa: E402

# Read-method names — these are excluded from the write-method derivation below.
# Lifecycle hooks are handled separately via LIFECYCLE_METHODS (imported above) so
# this set only needs to enumerate actual read methods, not hook overrides.
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
    """Return public async method names defined directly on cls (not inherited).

    Uses ``vars(cls)`` (not ``inspect.getmembers``) so that ``Resource``
    lifecycle methods inherited by both ``Api`` and ``RecordingApi`` do NOT
    appear in the comparison. Otherwise, an override of a lifecycle method on
    one side but not the other would surface as a confusing "write method
    missing" failure here.
    """
    return {
        name for name, member in vars(cls).items() if not name.startswith("_") and inspect.iscoroutinefunction(member)
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

    # Derive write methods: Api's public async methods minus read methods and
    # lifecycle hooks. This is conservative — if Api has a new method we haven't
    # classified, it will appear here and force an explicit classification decision.
    write_methods_on_api = api_async_methods - _KNOWN_READ_METHODS - LIFECYCLE_METHODS

    missing = write_methods_on_api - recording_api_async_methods
    assert not missing, (
        f"RecordingApi is missing write methods present in Api: {sorted(missing)}. "
        f"Add them to src/hassette/test_utils/recording_api.py and update "
        f"_KNOWN_READ_METHODS in this file if the new method is actually a read method."
    )
