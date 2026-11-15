"""WarnPacer passes the first call and at most one per interval after it."""

import pytest

from hassette.utils import warn_pacer
from hassette.utils.warn_pacer import WarnPacer


def test_first_call_passes_then_the_interval_suppresses(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([100.0, 105.0, 110.0, 111.0])
    monkeypatch.setattr(warn_pacer.time, "monotonic", lambda: next(clock))
    pacer = WarnPacer()

    assert [pacer.allow(10.0) for _ in range(4)] == [True, False, True, False]


def test_each_pacer_keeps_its_own_clock() -> None:
    first, second = WarnPacer(), WarnPacer()

    assert first.allow(1000.0)
    assert second.allow(1000.0)
    assert not first.allow(1000.0)
