"""Unit tests for db_degrades_to context manager in web/dependencies.py.

After #1108b, db_degrades_to catches TelemetryUnavailableError only.
Raw storage exceptions (sqlite3.Error, OSError, ValueError, TimeoutError)
are translated at the TelemetryQueryService boundary and never reach this CM.
"""

import sqlite3

import pytest
from starlette.responses import Response

from hassette.exceptions import TelemetryUnavailableError
from hassette.web.dependencies import db_degrades_to


class FakeResponse:
    """Minimal stand-in for starlette.responses.Response."""

    status_code: int = 200


class TestDbDegradesTo:
    def test_sets_503_on_telemetry_unavailable_error(self) -> None:
        """TelemetryUnavailableError is caught and status_code is set to 503."""
        resp = FakeResponse()
        with db_degrades_to(resp):
            raise TelemetryUnavailableError("db down")
        assert resp.status_code == 503

    def test_success_path_leaves_status_untouched(self) -> None:
        """When no exception is raised, status_code is not modified."""
        resp = FakeResponse()
        with db_degrades_to(resp):
            pass  # no exception
        assert resp.status_code == 200

    def test_does_not_suppress_unrelated_exception(self) -> None:
        """Exceptions that are not TelemetryUnavailableError propagate unchanged."""
        resp = FakeResponse()
        with pytest.raises(KeyError), db_degrades_to(resp):
            raise KeyError("unexpected")
        assert resp.status_code == 200

    def test_does_not_suppress_runtime_error(self) -> None:
        """RuntimeError propagates — it is not TelemetryUnavailableError."""
        resp = FakeResponse()
        with pytest.raises(RuntimeError), db_degrades_to(resp):
            raise RuntimeError("logic error")
        assert resp.status_code == 200

    def test_does_not_suppress_raw_sqlite_error(self) -> None:
        """Raw sqlite3.Error propagates — translation happens at the service, not here."""
        resp = FakeResponse()
        with pytest.raises(sqlite3.OperationalError), db_degrades_to(resp):
            raise sqlite3.OperationalError("disk I/O error")
        assert resp.status_code == 200

    def test_does_not_suppress_raw_value_error(self) -> None:
        """Raw ValueError propagates — it is application logic, not a translated DB error."""
        resp = FakeResponse()
        with pytest.raises(ValueError, match="bad model_validate input"), db_degrades_to(resp):
            raise ValueError("bad model_validate input")
        assert resp.status_code == 200

    def test_does_not_suppress_raw_oserror(self) -> None:
        """Raw OSError propagates — translation happens at the service boundary."""
        resp = FakeResponse()
        with pytest.raises(OSError, match="no such file"), db_degrades_to(resp):
            raise OSError("no such file")
        assert resp.status_code == 200

    def test_does_not_suppress_raw_timeout_error(self) -> None:
        """Raw TimeoutError propagates — translation happens at the service boundary."""
        resp = FakeResponse()
        with pytest.raises(TimeoutError), db_degrades_to(resp):
            raise TimeoutError("query timed out")
        assert resp.status_code == 200

    def test_real_response_object(self) -> None:
        """Works with a real starlette Response (same interface)."""
        resp = Response()
        with db_degrades_to(resp):
            raise TelemetryUnavailableError("corrupt db")
        assert resp.status_code == 503
