"""Unit tests for db_degrades_to context manager in web/dependencies.py."""

import sqlite3

import pytest
from starlette.responses import Response

from hassette.web.dependencies import db_degrades_to


class FakeResponse:
    """Minimal stand-in for starlette.responses.Response."""

    status_code: int = 200


class TestDbDegradesTo:
    def test_sets_503_on_sqlite_error(self) -> None:
        """A sqlite3.Error member is caught and status_code is set to 503."""
        resp = FakeResponse()
        with db_degrades_to(resp):
            raise sqlite3.OperationalError("disk I/O error")
        assert resp.status_code == 503

    def test_sets_503_on_oserror(self) -> None:
        """OSError is a DB_ERRORS member — sets 503."""
        resp = FakeResponse()
        with db_degrades_to(resp):
            raise OSError("no such file")
        assert resp.status_code == 503

    def test_sets_503_on_value_error(self) -> None:
        """ValueError (aiosqlite closed-connection case) sets 503."""
        resp = FakeResponse()
        with db_degrades_to(resp):
            raise ValueError("connection closed")
        assert resp.status_code == 503

    def test_sets_503_on_timeout_error(self) -> None:
        """TimeoutError sets 503."""
        resp = FakeResponse()
        with db_degrades_to(resp):
            raise TimeoutError("query timed out")
        assert resp.status_code == 503

    def test_success_path_leaves_status_untouched(self) -> None:
        """When no exception is raised, status_code is not modified."""
        resp = FakeResponse()
        with db_degrades_to(resp):
            pass  # no exception
        assert resp.status_code == 200

    def test_does_not_suppress_unrelated_exception(self) -> None:
        """Exceptions not in DB_ERRORS propagate out of the context manager."""
        resp = FakeResponse()
        with pytest.raises(KeyError), db_degrades_to(resp):
            raise KeyError("unexpected")
        # status_code must not have been touched
        assert resp.status_code == 200

    def test_does_not_suppress_runtime_error(self) -> None:
        """RuntimeError is not in DB_ERRORS and must not be swallowed."""
        resp = FakeResponse()
        with pytest.raises(RuntimeError), db_degrades_to(resp):
            raise RuntimeError("logic error")
        # status_code must not have been touched
        assert resp.status_code == 200

    def test_real_response_object(self) -> None:
        """Works with a real starlette Response (same interface)."""
        resp = Response()
        with db_degrades_to(resp):
            raise sqlite3.DatabaseError("corrupt db")
        assert resp.status_code == 503
