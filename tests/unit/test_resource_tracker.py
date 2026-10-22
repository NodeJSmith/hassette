"""Tests for the resource tracker pytest plugin's session hooks."""

import json
import types
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from tests.support import resource_tracker

WORKER_ID = "gw-resource-tracker-test"


@pytest.fixture
def stub_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A stub session rooted at tmp_path, with this test's own tracker swapped in for the session's."""
    monkeypatch.delenv("HASSETTE_DISABLE_RESOURCE_TRACKER", raising=False)
    # A non-main worker id keeps pytest_sessionfinish from merging (and deleting) the saved results.
    monkeypatch.setenv("PYTEST_XDIST_WORKER", WORKER_ID)
    # Restores the real session's tracker at teardown.
    monkeypatch.setattr(resource_tracker, "_tracker", None)
    yield types.SimpleNamespace(config=types.SimpleNamespace(rootpath=tmp_path))
    # A test that failed before pytest_sessionfinish leaves its tracker's patches layered over the real
    # session's; remove them before monkeypatch restores the real tracker.
    if resource_tracker._tracker is not None:  # pyright: ignore[reportPrivateUsage]
        resource_tracker._tracker.remove_patches()  # pyright: ignore[reportPrivateUsage]


def read_results(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / ".resource-tracker" / f"{WORKER_ID}.json").read_text())


def test_executor_closed_during_late_fixture_teardown_is_reported_closed(stub_session: Any, tmp_path: Path) -> None:
    resource_tracker.pytest_sessionstart(stub_session)
    executor = ThreadPoolExecutor(max_workers=1)

    # Simulates a session fixture from another plugin tearing down after the tracker's own fixture would have.
    executor.shutdown()

    resource_tracker.pytest_sessionfinish(stub_session, 0)

    results = read_results(tmp_path)
    assert results["total"] == 1
    assert results["unclosed"] == []


def test_executor_never_shut_down_is_reported_unclosed(stub_session: Any, tmp_path: Path) -> None:
    resource_tracker.pytest_sessionstart(stub_session)
    executor = ThreadPoolExecutor(max_workers=1)

    try:
        resource_tracker.pytest_sessionfinish(stub_session, 0)
    finally:
        # Keeps the real session's tracker from reporting this deliberate leak.
        executor.shutdown()

    results = read_results(tmp_path)
    assert results["total"] == 1
    assert [r["kind"] for r in results["unclosed"]] == ["ThreadPoolExecutor"]
