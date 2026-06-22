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

    @pytest.mark.parametrize(
        "exc",
        [
            KeyError("unexpected"),
            RuntimeError("logic error"),
            sqlite3.OperationalError("disk I/O error"),
            ValueError("bad model_validate input"),
            OSError("no such file"),
            TimeoutError("query timed out"),
        ],
    )
    def test_does_not_suppress_non_domain_exception(self, exc: Exception) -> None:
        """Only TelemetryUnavailableError is caught; everything else (including raw storage
        errors, which are translated at the service boundary) propagates unchanged."""
        resp = FakeResponse()
        with pytest.raises(type(exc)), db_degrades_to(resp):
            raise exc
        assert resp.status_code == 200

    def test_real_response_object(self) -> None:
        """Works with a real starlette Response (same interface)."""
        resp = Response()
        with db_degrades_to(resp):
            raise TelemetryUnavailableError("corrupt db")
        assert resp.status_code == 503
