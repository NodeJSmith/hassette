import asyncio
from unittest.mock import patch

import pytest
from whenever import ZonedDateTime

import hassette.scheduler.classes as classes_module
from hassette import Hassette
from hassette.scheduler import After, Cron, Daily, Every, Once, TriggerProtocol

TZ = "America/Chicago"


def _t(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> ZonedDateTime:
    """Shorthand for creating a ZonedDateTime in America/Chicago."""
    return ZonedDateTime(year, month, day, hour, minute, second, tz=TZ)


@pytest.mark.integration
async def test_run_cron_rejects_invalid(hassette_with_scheduler: Hassette) -> None:
    """run_cron raises ValueError when the cron expression is invalid."""
    with pytest.raises(ValueError, match="Invalid cron expression"):
        hassette_with_scheduler._scheduler.run_cron(lambda: None, "not a cron expression at all")


@pytest.mark.integration
async def test_run_cron_accepts_valid(hassette_with_scheduler: Hassette) -> None:
    """Valid cron expressions schedule jobs successfully."""
    scheduled_job = hassette_with_scheduler._scheduler.run_cron(lambda: None, "* * * * *")
    await asyncio.sleep(0)
    scheduled_job.cancel()


# ---------------------------------------------------------------------------
# Trigger types: After, Once, Every, Daily, Cron
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
    """Once(at='07:00').trigger_id() includes the resolved ISO timestamp, not just the time string."""
    fake_now = _t(2025, 8, 18, 6, 0, 0)
    monkeypatch.setattr("hassette.utils.date_utils.now", lambda: fake_now)

    trigger = Once(at="07:00")
    tid = trigger.trigger_id()
    # Must include the fire date so two Once jobs on different days don't collide (Finding 14)
    assert tid.startswith("once:")
    assert "07:00" in tid
    assert "2025-08-18" in tid


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


# --- DST disambiguation ---


def test_cron_trigger_dst_spring_forward_no_raise() -> None:
    """CronTrigger for Daily(02:30) resolves to a valid ZonedDateTime on spring-forward day.

    America/Chicago springs forward on 2025-03-09 02:00 -> 03:00 (CST -> CDT).
    02:30 is in the gap. croniter advances past the gap to 03:30 CDT on the same day.
    """
    # Anchor is just before DST transition
    anchor = _t(2025, 3, 9, 1, 0, 0)
    current_time = anchor
    trigger = Daily(at="02:30")

    # Must not raise SkippedTime or any other exception
    result = trigger.first_run_time(current_time)
    assert result is not None
    # Result must resolve to a valid, post-gap wall-clock time on the same day.
    assert result.year == 2025
    assert result.month == 3
    assert result.day == 9, f"Expected same day (2025-03-09) but got {result.format_iso()}"
    assert result.hour >= 3, f"Expected post-gap hour >= 3 but got {result.format_iso()}"
    # CDT is UTC-5. Asserting the offset guarantees we are on the post-DST side.
    assert result.format_iso().endswith("-05:00[America/Chicago]"), (
        f"Expected CDT (-05:00) but got {result.format_iso()}"
    )
    assert result >= current_time


def test_cron_trigger_dst_fall_back_prefers_post_transition() -> None:
    """CronTrigger for Daily(01:30) on fall-back day returns post-transition occurrence.

    America/Chicago falls back on 2025-11-02 02:00 -> 01:00.
    01:30 occurs twice; the trigger must prefer the post-transition occurrence.
    """
    anchor = _t(2025, 11, 2, 0, 30, 0)
    current_time = anchor
    trigger = Daily(at="01:30")

    result = trigger.first_run_time(current_time)
    assert result is not None
    # Same-day resolution, not e.g. 2025-11-03 01:30.
    assert result.day == 2, f"Expected same day (2025-11-02) but got {result.format_iso()}"
    assert (result.hour, result.minute) == (1, 30), f"Expected 01:30 wall-clock time but got {result.format_iso()}"
    # Post-transition offset for CST is UTC-6 = -06:00
    assert result.format_iso().endswith("-06:00[America/Chicago]"), (
        f"Expected post-transition (CST -06:00) but got {result.format_iso()}"
    )


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


# --- Once trigger_id day-specificity ---


# --- Once ZonedDateTime if_past asymmetry ---


def test_once_zoned_datetime_past_ignores_if_past(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once(at=past_zdt, if_past='tomorrow') fires immediately; 'tomorrow' has no effect.

    For ZonedDateTime inputs, if_past does NOT defer by a day — the absolute
    instant is used as-is, and the job fires immediately if it's in the past.
    """
    now_t = ZonedDateTime(2025, 8, 18, 12, 0, 0, tz=TZ)
    monkeypatch.setattr("hassette.utils.date_utils.now", lambda: now_t)

    past_zdt = ZonedDateTime(2025, 8, 18, 6, 0, 0, tz=TZ)  # 6 AM, 6 hours in the past
    trigger = Once(at=past_zdt, if_past="tomorrow")

    # if_past="tomorrow" has no effect for ZonedDateTime inputs — the job fires immediately,
    # NOT deferred to tomorrow.
    assert trigger.first_run_time(now_t) == past_zdt, (
        "ZonedDateTime past trigger should fire immediately, not defer to tomorrow"
    )


def test_once_string_trigger_id_day_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once(at='07:00') trigger_id includes the resolved ISO timestamp, not just the time string.

    Two Once jobs constructed on different days must have different trigger_ids.
    """
    day1 = ZonedDateTime(2025, 8, 18, 6, 0, 0, tz=TZ)
    monkeypatch.setattr("hassette.utils.date_utils.now", lambda: day1)
    once_day1 = Once(at="07:00")
    trigger_id_day1 = once_day1.trigger_id()

    # Advance to the next day — 07:00 resolves to a different date
    day2 = ZonedDateTime(2025, 8, 19, 6, 0, 0, tz=TZ)
    monkeypatch.setattr("hassette.utils.date_utils.now", lambda: day2)
    once_day2 = Once(at="07:00")
    trigger_id_day2 = once_day2.trigger_id()

    assert trigger_id_day1 != trigger_id_day2, (
        f"trigger_id should differ across days but both returned {trigger_id_day1!r}"
    )


# --- F1: DST fall-back INFO log ---


def test_cron_trigger_dst_fall_back_logs_info() -> None:
    """CronTrigger._next_after logs a single INFO summary when traversing ambiguous fall-back ticks.

    America/Chicago falls back on 2025-11-02 02:00 -> 01:00 (CDT -> CST).
    01:30 is ambiguous (occurs twice). The code uses fold=1 (post-transition) and
    emits a single INFO summary after the loop — not per-tick — to avoid log storms.
    """
    anchor = _t(2025, 11, 2, 0, 30, 0)
    trigger = Daily(at="01:30")

    with patch.object(classes_module.LOGGER, "info") as mock_info:
        trigger.first_run_time(anchor)

    mock_info.assert_called_once()
    assert "DST fall-back" in mock_info.call_args.args[0]


# --- F4: Once ZonedDateTime if_past="error" ---


def test_once_zoned_datetime_past_if_past_error_raises() -> None:
    """Once(at=past_zdt, if_past='error') raises ValueError when the ZonedDateTime is in the past."""
    past = ZonedDateTime(2020, 1, 1, 0, 0, tz="UTC")
    with pytest.raises(ValueError, match="in the past"):
        Once(at=past, if_past="error")
