"""Shared fixtures for unit/scheduler tests."""

from whenever import ZonedDateTime

from hassette.test_utils.factories import make_scheduler as make_scheduler

TZ = "America/Chicago"
PATCH_TARGET = "hassette.scheduler.scheduler.capture_registration_source"


def zdt(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> ZonedDateTime:
    return ZonedDateTime(year, month, day, hour, minute, second, tz=TZ)
