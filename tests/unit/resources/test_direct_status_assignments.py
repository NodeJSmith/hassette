"""Tests for direct status assignments (WP02, Subtask 5).

Verifies:
- app_lifecycle_service timeout path: STARTING → STOPPED is a valid transition
- harness/_websocket_service uses _status bypass (not validated setter)
"""

from hassette.resources.mixins import VALID_TRANSITIONS
from hassette.types.enums import ResourceStatus

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_app_lifecycle_timeout_stop_valid():
    """STARTING → STOPPED is in the valid transition table.

    app_lifecycle_service.py lines 158 and 168 set inst.status = STOPPED when
    an app fails to start (TimeoutError / Exception). The app is in STARTING
    state at that point, so the transition must be STARTING → STOPPED.
    """
    allowed = VALID_TRANSITIONS[ResourceStatus.STARTING]
    assert ResourceStatus.STOPPED in allowed, (
        "STARTING → STOPPED must be a valid transition (used by app_lifecycle_service on startup timeout/failure)"
    )


def test_harness_status_bypass():
    """harness.py uses _status (not .status) so mock state construction bypasses validation.

    This test verifies the _status bypass pattern works on a LifecycleMixin instance.
    It does NOT test behavior of the Mock — just confirms the assignment convention.
    """
    from hassette.resources.mixins import LifecycleMixin

    # Construct a bare LifecycleMixin (no hassette attribute) to test the bypass
    mixin = LifecycleMixin.__new__(LifecycleMixin)
    mixin._status = ResourceStatus.NOT_STARTED
    mixin._previous_status = ResourceStatus.NOT_STARTED

    # Direct _status assignment bypasses validation — no exception
    mixin._status = ResourceStatus.RUNNING
    assert mixin.status == ResourceStatus.RUNNING

    # Contrast: the public setter would validate; RUNNING → NOT_STARTED is invalid
    # but _status bypass skips it
    mixin._status = ResourceStatus.NOT_STARTED
    assert mixin.status == ResourceStatus.NOT_STARTED
