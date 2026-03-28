import asyncio
from zoneinfo import ZoneInfo

import pytest
from whenever import TimeDelta, ZonedDateTime

from hassette import Hassette
from hassette.scheduler import CronTrigger, IntervalTrigger

TZ = ZoneInfo("America/Chicago")


def _t(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> ZonedDateTime:
    """Shorthand for creating a ZonedDateTime in America/Chicago."""
    return ZonedDateTime.from_system_tz(year, month, day, hour, minute, second)


# --- IntervalTrigger ---


async def test_interval_trigger_catchup() -> None:
    """Interval trigger advances through missed runs before scheduling the next."""
    start = _t(2025, 8, 18, 0, 1, 0)
    current_time = _t(2025, 8, 18, 0, 1, 30)
    trigger = IntervalTrigger(TimeDelta(seconds=10), start=start)

    next_run = trigger.first_run_time(current_time)
    assert next_run.format_iso() == "2025-08-18T00:01:40-05:00[America/Chicago]", f"Got {next_run.format_iso()}"


async def test_interval_trigger_zero_interval() -> None:
    """IntervalTrigger rejects zero-second intervals."""
    with pytest.raises(ValueError, match="IntervalTrigger interval must be positive"):
        IntervalTrigger(TimeDelta(seconds=0))


async def test_interval_trigger_negative_interval() -> None:
    """IntervalTrigger rejects negative intervals."""
    with pytest.raises(ValueError, match="IntervalTrigger interval must be positive"):
        IntervalTrigger(TimeDelta(seconds=-5))


async def test_interval_trigger_floating_point_boundary() -> None:
    """Interval trigger handles floating-point edge cases at exact boundaries."""
    start = _t(2025, 8, 18, 0, 0, 0)
    # current_time is exactly 3 intervals ahead — boundary-exact should be treated as past
    current_time = _t(2025, 8, 18, 0, 0, 30)
    trigger = IntervalTrigger(TimeDelta(seconds=10), start=start)

    next_run = trigger.first_run_time(current_time)
    # Must be strictly after current_time
    assert next_run > current_time, f"Got {next_run.format_iso()}"
    assert next_run.format_iso() == "2025-08-18T00:00:40-05:00[America/Chicago]", f"Got {next_run.format_iso()}"


async def test_interval_trigger_stateless() -> None:
    """Calling first_run_time and next_run_time with the same inputs always returns the same output."""
    start = _t(2025, 8, 18, 0, 0, 0)
    current_time = _t(2025, 8, 18, 0, 0, 25)
    trigger = IntervalTrigger(TimeDelta(seconds=10), start=start)

    first_call = trigger.first_run_time(current_time)
    second_call = trigger.first_run_time(current_time)
    assert first_call == second_call

    # next_run_time is also stateless
    prev = _t(2025, 8, 18, 0, 0, 30)
    nr1 = trigger.next_run_time(prev, current_time)
    nr2 = trigger.next_run_time(prev, current_time)
    assert nr1 == nr2


async def test_interval_first_run_with_past_start() -> None:
    """first_run_time catches up from a past start time to produce a future result."""
    start = _t(2025, 8, 18, 0, 0, 0)
    current_time = _t(2025, 8, 18, 0, 5, 0)  # 5 minutes later
    trigger = IntervalTrigger(TimeDelta(seconds=60), start=start)

    next_run = trigger.first_run_time(current_time)
    assert next_run > current_time, f"Got {next_run.format_iso()}"
    assert next_run.format_iso() == "2025-08-18T00:06:00-05:00[America/Chicago]", f"Got {next_run.format_iso()}"


async def test_interval_first_run_with_future_start() -> None:
    """first_run_time returns start directly if start is in the future."""
    start = _t(2025, 8, 18, 0, 10, 0)
    current_time = _t(2025, 8, 18, 0, 5, 0)
    trigger = IntervalTrigger(TimeDelta(seconds=60), start=start)

    next_run = trigger.first_run_time(current_time)
    assert next_run == start.round(unit="second")


# --- CronTrigger ---


async def test_cron_trigger_catchup() -> None:
    """Cron trigger catches up to the next valid schedule after a delay."""
    start = _t(2025, 8, 18, 0, 1, 0)
    current_time = _t(2025, 8, 18, 0, 1, 30)
    trigger = CronTrigger.from_arguments(second="*/10", minute="*", hour="*", start=start)

    next_run = trigger.first_run_time(current_time)
    assert next_run.format_iso() == "2025-08-18T00:01:40-05:00[America/Chicago]", f"Got {next_run.format_iso()}"


async def test_run_cron_rejects_invalid(hassette_with_scheduler: Hassette) -> None:
    """run_cron raises ValueError when the cron expression is invalid."""
    with pytest.raises(ValueError, match="Invalid cron expression"):
        hassette_with_scheduler._scheduler.run_cron(lambda: None, second="nope")


async def test_run_cron_accepts_valid(hassette_with_scheduler: Hassette) -> None:
    """Valid cron expressions schedule jobs successfully."""
    scheduled_job = hassette_with_scheduler._scheduler.run_cron(
        lambda: None, second="1", start=_t(2025, 8, 18, 0, 0, 0)
    )
    await asyncio.sleep(0)
    scheduled_job.cancel()


async def test_cron_trigger_seconds() -> None:
    """Cron expressions constrained to seconds advance by one second."""
    start = _t(2025, 8, 18, 0, 0, 0)
    trigger = CronTrigger.from_arguments(second="*/1", start=start)
    assert trigger.cron_expression == "0 0 * * * */1", f"Got {trigger.cron_expression}"

    next_run = trigger.first_run_time(start)
    delta = next_run - start
    assert delta.in_seconds() == 1.0, f"Delta was {delta.in_seconds()} seconds"


async def test_cron_trigger_minutes() -> None:
    """Cron expressions constrained to minutes advance by sixty seconds."""
    start = _t(2025, 8, 18, 0, 0, 0)
    trigger = CronTrigger.from_arguments(second="0", minute="*/1", start=start)
    assert trigger.cron_expression == "*/1 0 * * * 0", f"Got {trigger.cron_expression}"

    next_run = trigger.first_run_time(start)
    delta = next_run - start
    assert delta.in_seconds() == 60, f"Delta was {delta.in_seconds()} seconds"


async def test_cron_trigger_stateless() -> None:
    """Calling first_run_time and next_run_time with the same inputs always returns the same output."""
    start = _t(2025, 8, 18, 0, 0, 0)
    current_time = _t(2025, 8, 18, 0, 0, 25)
    trigger = CronTrigger.from_arguments(second="*/10", minute="*", hour="*", start=start)

    first_call = trigger.first_run_time(current_time)
    second_call = trigger.first_run_time(current_time)
    assert first_call == second_call

    prev = _t(2025, 8, 18, 0, 0, 30)
    nr1 = trigger.next_run_time(prev, current_time)
    nr2 = trigger.next_run_time(prev, current_time)
    assert nr1 == nr2


async def test_cron_trigger_large_gap_catchup() -> None:
    """Cron trigger catches up correctly even with a large gap between anchor and current_time."""
    start = _t(2025, 8, 18, 0, 0, 0)
    current_time = _t(2025, 8, 18, 0, 5, 0)  # 5 minutes later
    trigger = CronTrigger.from_arguments(second="*/10", minute="*", hour="*", start=start)

    next_run = trigger.first_run_time(current_time)
    assert next_run > current_time, f"Got {next_run.format_iso()}"
    # croniter iterates from start through to first tick after current_time
    assert next_run.format_iso() == "2025-08-18T00:05:10-05:00[America/Chicago]", f"Got {next_run.format_iso()}"


async def test_interval_trigger_rounding_edge() -> None:
    """When rounding collapses next_run to the same second as previous_run, the guard advances by one interval."""
    start = _t(2025, 8, 18, 0, 0, 0)
    # previous_run and current_time are the same second — trigger must still produce a future time
    previous_run = _t(2025, 8, 18, 0, 0, 10)
    current_time = _t(2025, 8, 18, 0, 0, 10)
    trigger = IntervalTrigger(TimeDelta(seconds=10), start=start)

    next_run = trigger.next_run_time(previous_run, current_time)
    assert next_run > current_time, f"Expected future time, got {next_run.format_iso()}"
    assert next_run.format_iso() == "2025-08-18T00:00:20-05:00[America/Chicago]", f"Got {next_run.format_iso()}"
