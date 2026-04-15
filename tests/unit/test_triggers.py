import asyncio

import pytest
from whenever import TimeDelta, ZonedDateTime

from hassette import Hassette
from hassette.scheduler import After, Cron, CronTrigger, Daily, Every, IntervalTrigger, Once, TriggerProtocol

TZ = "America/Chicago"


def _t(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> ZonedDateTime:
    """Shorthand for creating a ZonedDateTime in America/Chicago."""
    return ZonedDateTime(year, month, day, hour, minute, second, tz=TZ)


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


async def test_cron_trigger_first_run_with_future_start() -> None:
    """first_run_time with a future start snaps to the cron grid, not the raw start time."""
    # start is at 09:00:03, but cron fires every 10 seconds — should snap to 09:00:10, not 09:00:03
    start = _t(2025, 8, 18, 9, 0, 3)
    current_time = _t(2025, 8, 18, 0, 0, 0)  # well before start
    trigger = CronTrigger.from_arguments(second="*/10", minute="*", hour="*", start=start)

    next_run = trigger.first_run_time(current_time)
    assert next_run > start, f"Expected time after start, got {next_run.format_iso()}"
    assert next_run.format_iso() == "2025-08-18T09:00:10-05:00[America/Chicago]", f"Got {next_run.format_iso()}"


async def test_cron_trigger_first_run_with_future_start_daily() -> None:
    """Daily cron with future start snaps to next midnight, not the raw start time."""
    # start is tomorrow at 9am, cron fires at midnight — should snap to midnight after start
    start = _t(2025, 8, 19, 9, 0, 0)
    current_time = _t(2025, 8, 18, 12, 0, 0)
    trigger = CronTrigger.from_arguments(second="0", minute="0", hour="0", start=start)

    next_run = trigger.first_run_time(current_time)
    assert next_run > start, f"Expected time after start, got {next_run.format_iso()}"
    # Next midnight after Aug 19 9am is Aug 20 midnight
    assert next_run.format_iso() == "2025-08-20T00:00:00-05:00[America/Chicago]", f"Got {next_run.format_iso()}"


@pytest.mark.integration
async def test_run_cron_rejects_invalid(hassette_with_scheduler: Hassette) -> None:
    """run_cron raises ValueError when the cron expression is invalid."""
    with pytest.raises(ValueError, match="Invalid cron expression"):
        hassette_with_scheduler._scheduler.run_cron(lambda: None, second="nope")


@pytest.mark.integration
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


# ---------------------------------------------------------------------------
# New trigger types: After, Once, Every, Daily, Cron
# ---------------------------------------------------------------------------


# --- After ---


def test_after_first_run_time() -> None:
    """After(seconds=30).first_run_time(t) returns t + 30s."""
    t = _t(2025, 8, 18, 7, 0, 0)
    trigger = After(seconds=30)
    result = trigger.first_run_time(t)
    expected = _t(2025, 8, 18, 7, 0, 30)
    assert result == expected, f"Got {result.format_iso()}"


def test_after_next_run_time_returns_none() -> None:
    """After.next_run_time() always returns None (one-shot trigger)."""
    t = _t(2025, 8, 18, 7, 0, 0)
    trigger = After(seconds=30)
    result = trigger.next_run_time(t, t)
    assert result is None


def test_after_trigger_id() -> None:
    """After(seconds=30).trigger_id() == 'after:30'."""
    assert After(seconds=30).trigger_id() == "after:30"


# --- Once ---


def test_once_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once(at='07:00') when current time is 06:00 fires today at 07:00."""
    fake_now = _t(2025, 8, 18, 6, 0, 0)
    monkeypatch.setattr("hassette.utils.date_utils.now", lambda: fake_now)

    trigger = Once(at="07:00")
    fire_time = trigger.first_run_time(fake_now)

    expected = _t(2025, 8, 18, 7, 0, 0)
    assert fire_time == expected, f"Got {fire_time.format_iso()}"


def test_once_tomorrow_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once(at='07:00') when current time is 08:00 fires tomorrow at 07:00."""
    fake_now = _t(2025, 8, 18, 8, 0, 0)
    monkeypatch.setattr("hassette.utils.date_utils.now", lambda: fake_now)

    trigger = Once(at="07:00")
    fire_time = trigger.first_run_time(fake_now)

    expected = _t(2025, 8, 19, 7, 0, 0)
    assert fire_time == expected, f"Got {fire_time.format_iso()}"


def test_once_past_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once(at='07:00', if_past='error') when current time is 08:00 raises ValueError."""
    fake_now = _t(2025, 8, 18, 8, 0, 0)
    monkeypatch.setattr("hassette.utils.date_utils.now", lambda: fake_now)

    with pytest.raises(ValueError, match="constructed after the target time"):
        Once(at="07:00", if_past="error")


def test_once_next_run_time_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once.next_run_time() always returns None (one-shot trigger)."""
    fake_now = _t(2025, 8, 18, 6, 0, 0)
    monkeypatch.setattr("hassette.utils.date_utils.now", lambda: fake_now)

    trigger = Once(at="07:00")
    t = _t(2025, 8, 18, 7, 0, 0)
    result = trigger.next_run_time(t, t)
    assert result is None


def test_once_trigger_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once(at='07:00').trigger_id() == 'once:07:00'."""
    fake_now = _t(2025, 8, 18, 6, 0, 0)
    monkeypatch.setattr("hassette.utils.date_utils.now", lambda: fake_now)

    trigger = Once(at="07:00")
    assert trigger.trigger_id() == "once:07:00"


# --- Every ---


def test_every_first_run_no_start() -> None:
    """Every(seconds=60).first_run_time(t) returns t + 60s when no start set."""
    t = _t(2025, 8, 18, 7, 0, 0)
    trigger = Every(seconds=60)
    result = trigger.first_run_time(t)
    expected = _t(2025, 8, 18, 7, 1, 0)
    assert result == expected, f"Got {result.format_iso()}"


def test_every_first_run_future_start() -> None:
    """Every(hours=1, start=t+10m).first_run_time(t) returns t+10m."""
    t = _t(2025, 8, 18, 7, 0, 0)
    start = _t(2025, 8, 18, 7, 10, 0)
    trigger = Every(hours=1, start=start)
    result = trigger.first_run_time(t)
    assert result == start, f"Got {result.format_iso()}"


def test_every_first_run_past_start() -> None:
    """_advance_past skips missed intervals correctly when start is in the past."""
    start = _t(2025, 8, 18, 0, 0, 0)
    current_time = _t(2025, 8, 18, 0, 5, 0)  # 5 minutes later
    trigger = Every(seconds=60, start=start)

    result = trigger.first_run_time(current_time)
    assert result > current_time, f"Got {result.format_iso()}"
    expected = _t(2025, 8, 18, 0, 6, 0)
    assert result == expected, f"Got {result.format_iso()}"


def test_every_next_run_time() -> None:
    """Every.next_run_time returns next interval aligned to previous_run anchor."""
    previous_run = _t(2025, 8, 18, 7, 0, 0)
    current_time = _t(2025, 8, 18, 7, 0, 30)
    trigger = Every(seconds=60)

    result = trigger.next_run_time(previous_run, current_time)
    expected = _t(2025, 8, 18, 7, 1, 0)
    assert result == expected, f"Got {result.format_iso()}"


def test_every_drift_resistant() -> None:
    """Multiple calls with late current_time do not compound drift."""
    trigger = Every(seconds=60)

    prev = _t(2025, 8, 18, 0, 0, 0)
    current_time = _t(2025, 8, 18, 0, 5, 0)
    r1 = trigger.next_run_time(prev, current_time)

    current_time2 = _t(2025, 8, 18, 0, 10, 0)
    r2 = trigger.next_run_time(r1, current_time2)

    assert (r1 - prev).in_seconds() % 60 == 0, f"r1={r1.format_iso()} not on 60s grid"
    assert (r2 - r1).in_seconds() % 60 == 0, f"r2={r2.format_iso()} not on 60s grid"


def test_every_trigger_id() -> None:
    """Every(hours=1).trigger_id() == 'every:3600'."""
    assert Every(hours=1).trigger_id() == "every:3600"


# --- Daily ---


def test_daily_fires_at_wall_clock_time() -> None:
    """Daily(at='07:00').next_run_time uses cron grid, not 24h elapsed."""
    prev = _t(2025, 8, 18, 7, 0, 0)
    now = _t(2025, 8, 18, 12, 0, 0)
    trigger = Daily(at="07:00")

    result = trigger.next_run_time(prev, now)
    expected = _t(2025, 8, 19, 7, 0, 0)
    assert result == expected, f"Got {result.format_iso()}"


def test_daily_trigger_db_type() -> None:
    """Daily.trigger_db_type() returns 'cron'."""
    assert Daily(at="07:00").trigger_db_type() == "cron"


def test_daily_trigger_id() -> None:
    """Daily(at='07:00').trigger_id() == 'cron:0 7 * * *'."""
    assert Daily(at="07:00").trigger_id() == "cron:0 7 * * *"


# --- Cron ---


def test_cron_5field() -> None:
    """Cron('0 9 * * 1-5') valid construction, correct trigger_id."""
    trigger = Cron("0 9 * * 1-5")
    assert trigger.trigger_id() == "cron:0 9 * * 1-5"


def test_cron_6field() -> None:
    """Cron('0 9 * * 1-5 0') valid construction, correct trigger_id."""
    trigger = Cron("0 9 * * 1-5 0")
    assert trigger.trigger_id() == "cron:0 9 * * 1-5 0"


def test_cron_invalid_raises() -> None:
    """Malformed cron expression raises ValueError at construction."""
    with pytest.raises(ValueError, match="not a cron expression"):
        Cron("not a cron expression at all")


# --- TriggerProtocol conformance ---


def test_trigger_protocol_conformance(monkeypatch: pytest.MonkeyPatch) -> None:
    """All five built-in trigger classes satisfy isinstance(t, TriggerProtocol)."""
    fake_now = _t(2025, 8, 18, 6, 0, 0)
    monkeypatch.setattr("hassette.utils.date_utils.now", lambda: fake_now)

    triggers = [
        After(seconds=30),
        Once(at="07:00"),
        Every(hours=1),
        Daily(at="07:00"),
        Cron("0 9 * * 1-5"),
    ]
    for trigger in triggers:
        assert isinstance(trigger, TriggerProtocol), f"{type(trigger).__name__} does not satisfy TriggerProtocol"
