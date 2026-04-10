"""Unit tests for the drain exception hierarchy.

These tests pin the relationship between ``DrainFailure``, ``DrainError``, and
``DrainTimeout`` so end users can rely on a single ``except DrainFailure:``
clause to catch any drain-related failure surfaced by ``AppTestHarness``.

The tests also document the deliberate clean-break decision: ``DrainTimeout``
does NOT inherit from :class:`TimeoutError`. Callers that previously caught
bare ``TimeoutError`` around drain calls must migrate to ``DrainTimeout`` (or
the broader ``DrainFailure``).
"""

import pytest

from hassette.test_utils import DrainError, DrainFailure, DrainTimeout


def test_drain_error_is_drain_failure() -> None:
    """DrainError can be caught as DrainFailure."""
    err = DrainError([("my_task", ValueError("boom"))])
    assert isinstance(err, DrainFailure)


def test_drain_timeout_is_drain_failure() -> None:
    """DrainTimeout can be caught as DrainFailure."""
    err = DrainTimeout("drain did not reach quiescence within 0.15s")
    assert isinstance(err, DrainFailure)


def test_drain_timeout_is_not_timeout_error() -> None:
    """DrainTimeout is a clean break — it is NOT a TimeoutError.

    This is intentional: the drain mechanism is a test-harness concern and
    raising a generic ``TimeoutError`` leaked that implementation detail to
    callers. If this test fails, someone has reintroduced multiple-inheritance
    with ``TimeoutError`` as a back-compat shim — revisit the hierarchy
    decision before allowing it.
    """
    err = DrainTimeout("unused")
    assert not isinstance(err, TimeoutError)


def test_except_drain_failure_catches_drain_error() -> None:
    """A single ``except DrainFailure:`` catches DrainError."""
    with pytest.raises(DrainFailure):
        raise DrainError([("task_a", RuntimeError("x"))])


def test_except_drain_failure_catches_drain_timeout() -> None:
    """A single ``except DrainFailure:`` catches DrainTimeout."""
    with pytest.raises(DrainFailure):
        raise DrainTimeout("drain deadline exceeded")


def test_drain_error_rejects_empty_task_exceptions() -> None:
    """DrainError refuses to construct from an empty list.

    The drain mechanism must guard raising ``DrainError`` behind
    ``if collected_exceptions:`` so that "no handler crash" cases take the
    ``DrainTimeout`` path instead. This test pins that contract so the guard
    cannot be silently removed during a refactor.
    """
    with pytest.raises(ValueError, match="requires at least one"):
        DrainError([])
