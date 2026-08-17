"""Shared fixtures for unit/scheduler tests."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from whenever import ZonedDateTime

from hassette.scheduler.scheduler import Scheduler
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.test_utils.factories import make_scheduler as make_scheduler

TZ = "America/Chicago"
PATCH_TARGET = "hassette.scheduler.scheduler.capture_registration_source"


def zdt(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> ZonedDateTime:
    return ZonedDateTime(year, month, day, hour, minute, second, tz=TZ)


@pytest.fixture
def patched_scheduler() -> Iterator[Scheduler]:
    """A Scheduler with capture_registration_source patched for the duration of the test.

    Matches the ``with patch(PATCH_TARGET, ...): scheduler = make_scheduler()`` shape used
    across this directory's test files wherever a real scheduler.schedule()/convenience-method
    call needs the registration-source patch active. The mocked return value's label is always
    ``"schedule(...)"`` regardless of which convenience method the test actually calls — no test
    in this directory asserts on ``registration_source``/``source_location`` content, so this is
    a shared placeholder, not a per-method label. A test that starts asserting on that value needs
    its own ``patch(PATCH_TARGET, ...)`` instead of this fixture.
    """
    with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
        yield make_scheduler()
