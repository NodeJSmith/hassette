"""Tests for direct status assignments.

Verifies:
- app_lifecycle_service timeout path: STARTING → STOPPED is a valid transition
- harness/_websocket_service uses _status bypass (not validated setter)
"""

from hassette_wire import ResourceStatus

from hassette.resources.mixins import VALID_TRANSITIONS
from tests.support.mock_hassette import make_mock_hassette
from tests.unit.resources.conftest import ConcreteResource


def test_app_lifecycle_timeout_stop_valid():
    """STARTING → STOPPED is in the valid transition table.

    AppLifecycleService.initialize_instances() sets inst.status = STOPPED directly
    (bypassing the validated setter) in its TimeoutError/Exception handlers, when an
    app fails to start. The app is in STARTING state at that point, so the transition
    must be STARTING → STOPPED.
    """
    allowed = VALID_TRANSITIONS[ResourceStatus.STARTING]
    assert ResourceStatus.STOPPED in allowed, (
        "STARTING → STOPPED must be a valid transition (used by app_lifecycle_service on startup timeout/failure)"
    )


def test_harness_status_bypass():
    """harness.py uses _status (not .status) so mock state construction bypasses validation.

    This test verifies the _status bypass pattern works on a Resource built with strict
    lifecycle validation, so any assignment that went through the setter would raise.
    """
    resource = ConcreteResource(make_mock_hassette(strict_lifecycle=True, sealed=False))

    # Direct _status assignment bypasses validation — no exception
    resource._status = ResourceStatus.RUNNING
    assert resource.status == ResourceStatus.RUNNING

    # Contrast: the public setter would raise; RUNNING → NOT_STARTED is invalid
    # but _status bypass skips it
    resource._status = ResourceStatus.NOT_STARTED
    assert resource.status == ResourceStatus.NOT_STARTED
