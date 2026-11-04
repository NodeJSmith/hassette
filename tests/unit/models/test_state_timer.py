"""TimerState conversion against the attribute shapes Home Assistant's timer entity publishes.

HA sets ``last_transition`` to the suffix of the last timer event (``"timer.finished"`` -> ``"finished"``);
``finishes_at`` is the only datetime attribute.
"""

from typing import TYPE_CHECKING, cast

import pytest
from whenever import ZonedDateTime

from hassette.conversion import STATE_REGISTRY
from hassette.models.states.timer import TimerState
from hassette.testing import make_state_dict

if TYPE_CHECKING:
    from hassette.events import HassStateDict


@pytest.mark.parametrize("transition", ["started", "restarted", "paused", "cancelled", "finished", "changed"])
def test_transitioned_timer_converts_to_timer_state(transition: str) -> None:
    raw = make_state_dict(
        "timer.arrival_grace",
        "idle",
        attributes={"duration": "1:00:00", "editable": False, "last_transition": transition, "restore": True},
    )

    state = STATE_REGISTRY.try_convert_state(cast("HassStateDict", raw))

    assert type(state) is TimerState
    assert state.attributes.last_transition == transition


def test_never_transitioned_timer_has_no_last_transition() -> None:
    raw = make_state_dict("timer.arrival_grace", "idle", attributes={"duration": "1:00:00", "last_transition": None})

    state = STATE_REGISTRY.try_convert_state(cast("HassStateDict", raw))

    assert type(state) is TimerState
    assert state.attributes.last_transition is None


def test_active_timer_parses_finishes_at_as_zoned_datetime() -> None:
    raw = make_state_dict(
        "timer.arrival_grace",
        "active",
        attributes={
            "duration": "1:00:00",
            "remaining": "0:59:58",
            "last_transition": "started",
            "finishes_at": "2026-11-04T18:00:00+00:00",
        },
    )

    state = STATE_REGISTRY.try_convert_state(cast("HassStateDict", raw))

    assert type(state) is TimerState
    assert isinstance(state.attributes.finishes_at, ZonedDateTime)
    assert state.attributes.finishes_at.to_instant() == ZonedDateTime(2026, 11, 4, 18, tz="UTC").to_instant()
