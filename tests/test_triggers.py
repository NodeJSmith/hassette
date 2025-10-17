import asyncio
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from whenever import TimeDelta, ZonedDateTime

from hassette import Hassette
from hassette.core.resources.scheduler.scheduler import CronTrigger, IntervalTrigger

TZ = ZoneInfo("America/Chicago")


async def test_interval_trigger_catchup() -> None:
    # start 30s in the past, interval 10s, now=00:01:30 → next should be 00:01:40

    fake_now = ZonedDateTime.from_py_datetime(datetime(2025, 8, 18, 0, 1, 30, tzinfo=TZ))  # "2025-08-18T00:01:30")
    with patch("hassette.core.resources.scheduler.classes.now", lambda: fake_now):
        trig = IntervalTrigger(TimeDelta(seconds=10), start=ZonedDateTime.from_system_tz(2025, 8, 18, 0, 1, 0))
        nxt = trig.next_run_time()
        assert nxt.format_iso() == "2025-08-18T00:01:40-05:00[America/Chicago]", f"Got {nxt.format_iso()}"


async def test_cron_trigger_catchup() -> None:
    fake_now = ZonedDateTime.from_py_datetime(datetime(2025, 8, 18, 0, 1, 30, tzinfo=TZ))  # "2025-08-18T00:01:30")
    with patch("hassette.core.resources.scheduler.classes.now", lambda: fake_now):
        trig = CronTrigger.from_arguments(
            second="*/10", minute="*", hour="*", start=ZonedDateTime.from_system_tz(2025, 8, 18, 0, 1, 0)
        )
        nxt = trig.next_run_time()
        assert nxt.format_iso() == "2025-08-18T00:01:40-05:00[America/Chicago]", f"Got {nxt.format_iso()}"


async def test_run_cron_rejects_invalid(hassette_with_scheduler: Hassette) -> None:
    with pytest.raises(ValueError, match="Invalid cron expression"):
        hassette_with_scheduler._scheduler.run_cron(lambda: None, second="nope")


async def test_run_cron_accepts_valid(hassette_with_scheduler: Hassette) -> None:
    # “every 5 seconds” (fields: sec min hour dom mon dow year)
    job = hassette_with_scheduler._scheduler.run_cron(
        lambda: None, second="1", start=ZonedDateTime.from_system_tz(2025, 8, 18, 0, 0, 0)
    )
    await asyncio.sleep(0)  # allow scheduling to complete
    job.cancel()


async def test_cron_trigger_seconds():
    start_time = ZonedDateTime.from_system_tz(2025, 8, 18, 0, 0, 0)

    trig = CronTrigger.from_arguments(second="*/1", start=start_time)
    assert trig.cron_expression == "0 0 * * * */1", f"Got {trig.cron_expression}"

    trig_next_time = trig.cron_iter.get_next()

    delta = ZonedDateTime.from_py_datetime(trig_next_time) - start_time

    assert delta.in_seconds() == 1.0, f"Delta was {delta.in_seconds()} seconds"


async def test_cron_trigger_minutes():
    start_time = ZonedDateTime.from_system_tz(2025, 8, 18, 0, 0, 0)

    trig = CronTrigger.from_arguments(second="0", minute="*/1", start=start_time)
    assert trig.cron_expression == "*/1 0 * * * 0", f"Got {trig.cron_expression}"

    trig_next_time = trig.cron_iter.get_next()

    delta = ZonedDateTime.from_py_datetime(trig_next_time) - start_time

    assert delta.in_seconds() == 60, f"Delta was {delta.in_seconds()} seconds"
