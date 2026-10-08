"""Tests for tools/client_compat_requests.py: request paths and which requests a seeded database gets."""

import pytest
from client_compat_live_state import SeedIds
from client_compat_requests import UNKNOWN_EXECUTION_UUID, FixtureRequest, success_requests
from hassette_wire import ProblemCode

NO_IDS = SeedIds(app_key=None, listener_id=None, job_id=None, execution_id=None)

ALL_IDS = SeedIds(
    app_key="app",
    listener_id=1,
    job_id=2,
    execution_id="exec",
    failed_execution_id="failed",
    logged_execution_id="019bc280-ce60-7000-8000-000000000001",
    multi_app_listed=True,
)


def test_path_quotes_params() -> None:
    request = FixtureRequest("x", "GET", "/api/apps/{app_key}", {"app_key": "not a/key"})
    assert request.path == "/api/apps/not%20a%2Fkey"


def test_a_request_cannot_be_both_a_problem_and_a_probe() -> None:
    with pytest.raises(ValueError, match="not both"):
        FixtureRequest("x", "GET", "/api/x", problem_code=ProblemCode.NOT_FOUND, probe=True)


def test_success_requests_skip_requests_missing_their_seed_id() -> None:
    with_ids = {r.name for r in success_requests(ALL_IDS)}
    without_ids = {r.name for r in success_requests(NO_IDS)}

    assert with_ids - without_ids == {
        "app",
        "app-health",
        "app-listeners",
        "app-activity",
        "app-jobs",
        "app-blocking",
        "app-live",
        "listener-executions",
        "job-executions",
        "execution",
        "execution-failed",
    }
    assert "health" in without_ids


def test_execution_logs_falls_back_to_an_unknown_uuid() -> None:
    [without] = [r for r in success_requests(NO_IDS) if r.name == "execution-logs"]
    [with_logs] = [r for r in success_requests(ALL_IDS) if r.name == "execution-logs"]

    assert without.params["execution_id"] == UNKNOWN_EXECUTION_UUID
    assert with_logs.params["execution_id"] == ALL_IDS.logged_execution_id
