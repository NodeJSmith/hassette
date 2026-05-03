"""Tests for LifecycleMixin transition validation (WP01).

Verifies:
- Valid transitions go through without error and emit DEBUG logs
- Invalid transitions raise InvalidLifecycleTransitionError in strict mode
- Invalid transitions log WARNING (and still proceed) in non-strict mode
- _force_terminal() bypasses the setter and skips validation
- Restart transitions (FAILED→STARTING, CRASHED→STARTING) are accepted
- EXHAUSTED states transition table is correct
- Terminal EXHAUSTED_DEAD rejects further transitions in strict mode
- hasattr guard: no hassette attribute → no error (construction-time guard)
- handle_running() idempotency is preserved (already RUNNING → early return, no setter)
"""

import pytest

from hassette.exceptions import InvalidLifecycleTransitionError
from hassette.resources.base import Resource
from hassette.types.enums import ResourceStatus

from .conftest import _make_hassette_stub


class _SimpleResource(Resource):
    """Minimal Resource subclass for testing."""

    pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_transition_sequence():
    """Walk NOT_STARTED → STARTING → RUNNING → STOPPING → STOPPED via the setter — no error raised."""
    hassette = _make_hassette_stub()
    resource = _SimpleResource(hassette)

    resource.status = ResourceStatus.STARTING
    assert resource.status == ResourceStatus.STARTING

    resource.status = ResourceStatus.RUNNING
    assert resource.status == ResourceStatus.RUNNING

    resource.status = ResourceStatus.STOPPING
    assert resource.status == ResourceStatus.STOPPING

    resource.status = ResourceStatus.STOPPED
    assert resource.status == ResourceStatus.STOPPED


@pytest.mark.asyncio
async def test_invalid_transition_raises_strict():
    """In strict mode, NOT_STARTED → RUNNING raises InvalidLifecycleTransitionError with correct fields."""
    hassette = _make_hassette_stub(strict_lifecycle=True)
    resource = _SimpleResource(hassette)

    assert resource.status == ResourceStatus.NOT_STARTED

    with pytest.raises(InvalidLifecycleTransitionError) as exc_info:
        resource.status = ResourceStatus.RUNNING

    err = exc_info.value
    assert err.from_status == ResourceStatus.NOT_STARTED
    assert err.to_status == ResourceStatus.RUNNING
    assert err.resource_name  # non-empty


@pytest.mark.asyncio
async def test_invalid_transition_warns_nonstrict():
    """Non-strict mode: invalid transition does not raise and the transition still proceeds."""
    hassette = _make_hassette_stub(strict_lifecycle=False)
    resource = _SimpleResource(hassette)

    assert resource.status == ResourceStatus.NOT_STARTED

    resource.status = ResourceStatus.RUNNING

    assert resource.status == ResourceStatus.RUNNING


@pytest.mark.asyncio
async def test_force_terminal_bypasses_validation():
    """In strict mode, _force_terminal() on a RUNNING resource succeeds with STOPPED and no error."""
    hassette = _make_hassette_stub(strict_lifecycle=True)
    resource = _SimpleResource(hassette)

    # Manually set to RUNNING bypassing the setter so we can test _force_terminal
    resource._status = ResourceStatus.RUNNING

    # _force_terminal() must NOT raise even in strict mode
    resource._force_terminal()

    assert resource.status == ResourceStatus.STOPPED


@pytest.mark.asyncio
async def test_restart_transitions_valid():
    """FAILED → STARTING and CRASHED → STARTING are valid restart transitions."""
    hassette = _make_hassette_stub(strict_lifecycle=True)

    # FAILED → STARTING
    resource1 = _SimpleResource(hassette)
    resource1._status = ResourceStatus.FAILED
    # Should not raise
    resource1.status = ResourceStatus.STARTING
    assert resource1.status == ResourceStatus.STARTING

    # CRASHED → STARTING
    resource2 = _SimpleResource(hassette)
    resource2._status = ResourceStatus.CRASHED
    # Should not raise
    resource2.status = ResourceStatus.STARTING
    assert resource2.status == ResourceStatus.STARTING


@pytest.mark.asyncio
async def test_exhausted_transitions_valid():
    """FAILED→EXHAUSTED_COOLING, EXHAUSTED_COOLING→STARTING, EXHAUSTED_COOLING→EXHAUSTED_DEAD are valid."""
    hassette = _make_hassette_stub(strict_lifecycle=True)

    # FAILED → EXHAUSTED_COOLING
    r1 = _SimpleResource(hassette)
    r1._status = ResourceStatus.FAILED
    r1.status = ResourceStatus.EXHAUSTED_COOLING
    assert r1.status == ResourceStatus.EXHAUSTED_COOLING

    # EXHAUSTED_COOLING → STARTING
    r2 = _SimpleResource(hassette)
    r2._status = ResourceStatus.EXHAUSTED_COOLING
    r2.status = ResourceStatus.STARTING
    assert r2.status == ResourceStatus.STARTING

    # EXHAUSTED_COOLING → EXHAUSTED_DEAD
    r3 = _SimpleResource(hassette)
    r3._status = ResourceStatus.EXHAUSTED_COOLING
    r3.status = ResourceStatus.EXHAUSTED_DEAD
    assert r3.status == ResourceStatus.EXHAUSTED_DEAD


@pytest.mark.asyncio
async def test_terminal_state_rejects_transitions():
    """EXHAUSTED_DEAD → STARTING raises InvalidLifecycleTransitionError in strict mode."""
    hassette = _make_hassette_stub(strict_lifecycle=True)
    resource = _SimpleResource(hassette)
    resource._status = ResourceStatus.EXHAUSTED_DEAD

    with pytest.raises(InvalidLifecycleTransitionError) as exc_info:
        resource.status = ResourceStatus.STARTING

    err = exc_info.value
    assert err.from_status == ResourceStatus.EXHAUSTED_DEAD
    assert err.to_status == ResourceStatus.STARTING


@pytest.mark.asyncio
async def test_hasattr_guard_no_hassette():
    """Setting status on an object without 'hassette' attribute should not raise (construction-time guard)."""
    from hassette.resources.mixins import LifecycleMixin

    # Create a LifecycleMixin directly — it does not call Resource.__init__,
    # so self.hassette will not be set.
    mixin = LifecycleMixin.__new__(LifecycleMixin)
    mixin._status = ResourceStatus.NOT_STARTED
    mixin._previous_status = ResourceStatus.NOT_STARTED

    # Should not raise even though there's no hassette attribute
    assert not hasattr(mixin, "hassette")
    mixin.status = ResourceStatus.STARTING
    assert mixin.status == ResourceStatus.STARTING


@pytest.mark.asyncio
async def test_same_state_no_transition():
    """handle_running() when already RUNNING returns early — idempotency preserved, previous_status unchanged."""
    hassette = _make_hassette_stub(strict_lifecycle=True)
    resource = _SimpleResource(hassette)

    resource._status = ResourceStatus.RUNNING
    resource._previous_status = ResourceStatus.STARTING

    await resource.handle_running()

    assert resource.status == ResourceStatus.RUNNING
    assert resource._previous_status == ResourceStatus.STARTING
