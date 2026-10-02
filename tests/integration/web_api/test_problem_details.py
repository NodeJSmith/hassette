"""Every error response under `/api` is an RFC 9457 problem body with a stable `code`.

One case per (coverage row, code) pair in the error-coverage table of
`design/specs/118-api-problem-details/design.md` (D1). Each case pins status, content type, and
the full body. For an operation-specific code it also pins that the operation's OpenAPI response
for that status lists the code in `x-problem-codes`. Global codes (routing, middleware, request
validation, unhandled errors) are documented once in the error catalog instead, so they are not
looked up per operation.
"""

import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import KW_ONLY, dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from hassette_wire import MAX_SESSION_TOKEN_LENGTH
from httpx2 import ASGITransport, AsyncClient, Response

from hassette.exceptions import AppBlockedError, AppBootstrapNotReleasedError, JobRemovedError
from hassette.web.app import create_fastapi_app
from hassette.web.dependencies import get_runtime
from hassette.web.errors import GLOBAL_CODES, PROBLEM_CODES_KEY
from tests.integration.conftest import make_manifest_mock
from tests.support.web_manifest_helpers import make_app_instance_info

from .conftest import telemetry_error

PROBLEM_CONTENT_TYPE = "application/problem+json"

TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Content Too Large",
    422: "Unprocessable Content",
    500: "Internal Server Error",
    503: "Service Unavailable",
}
"""Expected `title` per status, spelled out so the pinned RFC 9110 phrases are checked, not copied."""

LOG_LEVELS = "CRITICAL, DEBUG, ERROR, INFO, WARNING"

TOKEN_SENTINEL = "SENTINEL-TOKEN-VALUE"
"""Planted in a rejected field to prove a validation `detail` never echoes the input."""

BLOCKED = AppBlockedError("App 'my_app' is blocked by the --app filter")
NOT_RELEASED = AppBootstrapNotReleasedError("not released")

Arrange = Callable[[MagicMock, Path], None]


@dataclass(frozen=True)
class ProblemCase:
    method: str
    path: str
    status: int
    code: str
    detail: str
    _: KW_ONLY
    operation: str | None = None
    """OpenAPI path template whose `x-problem-codes` must list `code`; None for global codes."""
    arrange: Arrange | None = None
    request: dict[str, Any] = field(default_factory=dict)


def assert_problem(response: Response, *, status: int, code: str, detail: str) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == PROBLEM_CONTENT_TYPE
    assert response.json() == {
        "type": "about:blank",
        "title": TITLES[status],
        "status": status,
        "detail": detail,
        "code": code,
    }


def declared_codes(app: FastAPI, operation: str, method: str, status: int) -> list[str]:
    return app.openapi()["paths"][operation][method.lower()]["responses"][str(status)][PROBLEM_CODES_KEY]


def unknown_app(mock_hassette: MagicMock, _: Path) -> None:
    mock_hassette._app_handler.registry.get_manifest.return_value = None
    mock_hassette._app_handler.registry.get_instances.return_value = {}


def single_instance_app(mock_hassette: MagicMock, _: Path) -> None:
    mock_hassette._app_handler.registry.get_manifest.return_value = make_manifest_mock()
    mock_hassette._app_handler.registry.get_instances.return_value = {}


def raising(handler_method: str, exc: Exception) -> Arrange:
    def arrange(mock_hassette: MagicMock, tmp_path: Path) -> None:
        single_instance_app(mock_hassette, tmp_path)
        setattr(mock_hassette.app_handler, handler_method, AsyncMock(side_effect=exc))

    return arrange


def instance_ends_failed(mock_hassette: MagicMock, tmp_path: Path) -> None:
    single_instance_app(mock_hassette, tmp_path)
    mock_hassette._app_handler.registry.get_failed_instance_infos.return_value = {
        0: make_app_instance_info(app_key="my_app", error_message="on_initialize blew up")
    }


def source_at(make_path: Callable[[Path], Any], *, write: bytes | None = None) -> Arrange:
    def arrange(mock_hassette: MagicMock, tmp_path: Path) -> None:
        app_dir = tmp_path / "apps"
        app_dir.mkdir()
        path = make_path(app_dir)
        if write is not None:
            path.write_bytes(write)
        mock_hassette._app_handler.registry.get_manifest.return_value = make_manifest_mock(
            app_dir=app_dir, full_path=path
        )

    return arrange


def unresolvable_path(_: Path) -> MagicMock:
    path = MagicMock()
    path.resolve.side_effect = OSError("resolve failed")
    return path


def manifest_lookup(get_app_manifest: AsyncMock) -> Arrange:
    def arrange(mock_hassette: MagicMock, _: Path) -> None:
        mock_hassette.telemetry_query_service.get_app_manifest = get_app_manifest

    return arrange


def job_lookup_fails(mock_hassette: MagicMock, _: Path) -> None:
    mock_hassette.scheduler_service.trigger_job = AsyncMock(side_effect=ValueError("Job 7 is not registered"))


def job_removed_before_submit(mock_hassette: MagicMock, _: Path) -> None:
    job = MagicMock()
    job.name = "nightly"
    mock_hassette.scheduler_service.trigger_job = AsyncMock(return_value=job)
    mock_hassette.scheduler_service.submit_job = MagicMock(side_effect=JobRemovedError("nightly", 7))


ROUTE_CASES = {
    # POST /api/apps/{app_key}/start, /stop, /reload
    "app-invalid-key": ProblemCase(
        "POST",
        "/api/apps/1bad/stop",
        400,
        "invalid_app_key",
        "Invalid app_key: '1bad'",
        operation="/api/apps/{app_key}/stop",
    ),
    "app-not-found": ProblemCase(
        "POST",
        "/api/apps/my_app/reload",
        404,
        "app_not_found",
        "App 'my_app' not found",
        operation="/api/apps/{app_key}/reload",
        arrange=unknown_app,
    ),
    "app-bootstrap-not-released": ProblemCase(
        "POST",
        "/api/apps/my_app/start",
        409,
        "bootstrap_not_released",
        "App bootstrap prerequisites are not ready yet; retry later",
        operation="/api/apps/{app_key}/start",
        arrange=raising("start_app", NOT_RELEASED),
    ),
    "app-blocked": ProblemCase(
        "POST",
        "/api/apps/my_app/reload",
        409,
        "app_blocked",
        "App 'my_app' is blocked by the --app filter",
        operation="/api/apps/{app_key}/reload",
        arrange=raising("reload_app", BLOCKED),
    ),
    "app-action-raises": ProblemCase(
        "POST",
        "/api/apps/my_app/stop",
        500,
        "action_failed",
        "Failed to stop app 'my_app'",
        operation="/api/apps/{app_key}/stop",
        arrange=raising("stop_app", RuntimeError("boom")),
    ),
    "app-action-instance-failed": ProblemCase(
        "POST",
        "/api/apps/my_app/start",
        500,
        "action_failed",
        "on_initialize blew up",
        operation="/api/apps/{app_key}/start",
        arrange=instance_ends_failed,
    ),
    # POST /api/apps/{app_key}/instances/{index}/start, /stop, /reload
    "instance-invalid-key": ProblemCase(
        "POST",
        "/api/apps/1bad/instances/0/start",
        400,
        "invalid_app_key",
        "Invalid app_key: '1bad'",
        operation="/api/apps/{app_key}/instances/{index}/start",
    ),
    "instance-app-not-found": ProblemCase(
        "POST",
        "/api/apps/my_app/instances/0/reload",
        404,
        "app_not_found",
        "App 'my_app' not found",
        operation="/api/apps/{app_key}/instances/{index}/reload",
        arrange=unknown_app,
    ),
    "instance-out-of-range": ProblemCase(
        "POST",
        "/api/apps/my_app/instances/5/stop",
        404,
        "instance_not_found",
        "Instance 5 not found for app 'my_app'",
        operation="/api/apps/{app_key}/instances/{index}/stop",
        arrange=single_instance_app,
    ),
    "instance-bootstrap-not-released": ProblemCase(
        "POST",
        "/api/apps/my_app/instances/0/reload",
        409,
        "bootstrap_not_released",
        "App bootstrap prerequisites are not ready yet; retry later",
        operation="/api/apps/{app_key}/instances/{index}/reload",
        arrange=raising("reload_instance", NOT_RELEASED),
    ),
    "instance-blocked": ProblemCase(
        "POST",
        "/api/apps/my_app/instances/0/start",
        409,
        "app_blocked",
        "App 'my_app' is blocked by the --app filter",
        operation="/api/apps/{app_key}/instances/{index}/start",
        arrange=raising("start_instance", BLOCKED),
    ),
    "instance-action-failed": ProblemCase(
        "POST",
        "/api/apps/my_app/instances/0/stop",
        500,
        "action_failed",
        "Failed to stop app 'my_app'",
        operation="/api/apps/{app_key}/instances/{index}/stop",
        arrange=raising("stop_instance", ValueError("boom")),
    ),
    # GET /api/apps/{app_key}/manifest
    "manifest-invalid-key": ProblemCase(
        "GET",
        "/api/apps/1bad/manifest",
        400,
        "invalid_app_key",
        "Invalid app_key: '1bad'",
        operation="/api/apps/{app_key}/manifest",
    ),
    "manifest-telemetry-unavailable": ProblemCase(
        "GET",
        "/api/apps/my_app/manifest",
        503,
        "telemetry_unavailable",
        "Telemetry store unavailable",
        operation="/api/apps/{app_key}/manifest",
        arrange=manifest_lookup(telemetry_error()),
    ),
    "manifest-app-not-found": ProblemCase(
        "GET",
        "/api/apps/my_app/manifest",
        404,
        "app_not_found",
        "App 'my_app' not found",
        operation="/api/apps/{app_key}/manifest",
        arrange=manifest_lookup(AsyncMock(return_value=None)),
    ),
    # GET /api/apps/{app_key}/config
    "config-invalid-key": ProblemCase(
        "GET",
        "/api/apps/1bad/config",
        400,
        "invalid_app_key",
        "Invalid app_key: '1bad'",
        operation="/api/apps/{app_key}/config",
    ),
    "config-app-not-found": ProblemCase(
        "GET",
        "/api/apps/my_app/config",
        404,
        "app_not_found",
        "App 'my_app' not found",
        operation="/api/apps/{app_key}/config",
        arrange=unknown_app,
    ),
    # GET /api/apps/{app_key}/source
    "source-invalid-key": ProblemCase(
        "GET",
        "/api/apps/1bad/source",
        400,
        "invalid_app_key",
        "Invalid app_key: '1bad'",
        operation="/api/apps/{app_key}/source",
    ),
    "source-app-not-found": ProblemCase(
        "GET",
        "/api/apps/my_app/source",
        404,
        "app_not_found",
        "App 'my_app' not found",
        operation="/api/apps/{app_key}/source",
        arrange=unknown_app,
    ),
    "source-path-unresolvable": ProblemCase(
        "GET",
        "/api/apps/my_app/source",
        500,
        "source_unavailable",
        "Failed to resolve app path",
        operation="/api/apps/{app_key}/source",
        arrange=source_at(unresolvable_path),
    ),
    "source-path-traversal": ProblemCase(
        "GET",
        "/api/apps/my_app/source",
        403,
        "path_traversal",
        "Path traversal not allowed",
        operation="/api/apps/{app_key}/source",
        arrange=source_at(lambda app_dir: app_dir.parent / "outside.py", write=b""),
    ),
    "source-file-missing": ProblemCase(
        "GET",
        "/api/apps/my_app/source",
        404,
        "source_not_found",
        "Source file not found for app 'my_app'",
        operation="/api/apps/{app_key}/source",
        arrange=source_at(lambda app_dir: app_dir / "my_app.py"),
    ),
    "source-unreadable": ProblemCase(
        "GET",
        "/api/apps/my_app/source",
        500,
        "source_unavailable",
        "Failed to read app source",
        operation="/api/apps/{app_key}/source",
        arrange=source_at(lambda app_dir: app_dir / "my_app.py", write=b"\xff\xfe\xfa"),
    ),
    # POST /api/auth/session
    "session-invalid-token": ProblemCase(
        "POST",
        "/api/auth/session",
        401,
        "invalid_token",
        "Invalid token",
        operation="/api/auth/session",
        request={"json": {"token": "wrong"}},
    ),
    # POST /api/scheduler/jobs/{job_id}/trigger, both raise sites
    "trigger-not-registered": ProblemCase(
        "POST",
        "/api/scheduler/jobs/7/trigger",
        409,
        "job_not_registered",
        "Job 7 is not registered",
        operation="/api/scheduler/jobs/{job_id}/trigger",
        arrange=job_lookup_fails,
    ),
    "trigger-removed-before-submit": ProblemCase(
        "POST",
        "/api/scheduler/jobs/7/trigger",
        409,
        "job_not_registered",
        str(JobRemovedError("nightly", 7)),
        operation="/api/scheduler/jobs/{job_id}/trigger",
        arrange=job_removed_before_submit,
    ),
    # Hand-raised 422s share the global validation_failed code (D4)
    "execution-id-not-uuid": ProblemCase(
        "GET",
        "/api/executions/not-a-uuid",
        422,
        "validation_failed",
        "Invalid execution_id: 'not-a-uuid' is not a valid UUID",
    ),
    "logs-bad-level": ProblemCase(
        "GET",
        "/api/logs/recent?level=bogus",
        422,
        "validation_failed",
        f"Invalid level 'BOGUS'. Must be one of: {LOG_LEVELS}",
    ),
    "logs-bad-source-tier": ProblemCase(
        "GET",
        "/api/logs/recent?source_tier=nope",
        422,
        "validation_failed",
        "Invalid source_tier 'nope'. Must be one of: app, framework",
    ),
    "log-level-empty-logger": ProblemCase(
        "PUT",
        "/api/logs/level",
        422,
        "validation_failed",
        "logger name must not be empty",
        request={"json": {"logger": "", "level": "INFO"}},
    ),
    "log-level-unknown": ProblemCase(
        "PUT",
        "/api/logs/level",
        422,
        "validation_failed",
        f"Invalid log level 'loud'. Must be one of: {LOG_LEVELS}",
        request={"json": {"logger": "hassette", "level": "loud"}},
    ),
    # FastAPI's own request validation and body parsing
    "fastapi-query-out-of-range": ProblemCase(
        "GET",
        "/api/logs/recent?limit=0",
        422,
        "validation_failed",
        "Validation failed: query.limit: Input should be greater than or equal to 1",
    ),
    # The body must stay under MAX_REQUEST_BODY_BYTES (web/body_limit.py), or the body-limit
    # middleware answers 413 before field validation runs.
    "fastapi-oversized-field": ProblemCase(
        "POST",
        "/api/auth/session",
        422,
        "validation_failed",
        f"Validation failed: body.token: String should have at most {MAX_SESSION_TOKEN_LENGTH} characters",
        request={"json": {"token": TOKEN_SENTINEL * (MAX_SESSION_TOKEN_LENGTH // len(TOKEN_SENTINEL) + 1)}},
    ),
    "fastapi-malformed-json": ProblemCase(
        "PUT",
        "/api/logs/level",
        422,
        "validation_failed",
        "Validation failed: body.21: JSON decode error",
        request={"content": b'{"logger": "hassette"', "headers": {"content-type": "application/json"}},
    ),
    "fastapi-undecodable-body": ProblemCase(
        "PUT",
        "/api/logs/level",
        400,
        "http_error",
        "There was an error parsing the body",
        request={"content": b'{"logger": "\xff"}', "headers": {"content-type": "application/json"}},
    ),
}


@pytest.mark.parametrize("case", list(ROUTE_CASES.values()), ids=list(ROUTE_CASES))
async def test_error_is_problem_body(
    case: ProblemCase, app: FastAPI, client: AsyncClient, mock_hassette: MagicMock, tmp_path: Path
) -> None:
    if case.arrange is not None:
        case.arrange(mock_hassette, tmp_path)

    response = await client.request(case.method, case.path, **case.request)

    assert_problem(response, status=case.status, code=case.code, detail=case.detail)
    assert TOKEN_SENTINEL not in response.text
    if case.operation is not None:
        assert case.code not in GLOBAL_CODES
        assert case.code in declared_codes(app, case.operation, case.method, case.status)


class TestMiddlewareErrors:
    async def test_missing_credential_is_not_authenticated(self, auth_client: AsyncClient) -> None:
        response = await auth_client.get("/api/apps")

        assert_problem(response, status=401, code="not_authenticated", detail="Not authenticated")

    async def test_oversized_body_is_body_too_large(self, auth_client: AsyncClient) -> None:
        response = await auth_client.post("/api/auth/session", content=b"x" * (128 * 1024))

        assert_problem(response, status=413, code="body_too_large", detail="Request body too large")
        assert "x-max-body-bytes" in response.headers


@pytest.fixture(params=[False, True], ids=["run_ui-off", "run_ui-on"])
async def routing_client(
    request: pytest.FixtureRequest, mock_hassette: MagicMock, stub_spa: Path
) -> AsyncIterator[AsyncClient]:
    """A client for an app with the SPA catch-all registered (run_ui on) or absent (run_ui off)."""
    del stub_spa  # only needed for its side effect: a served SPA when run_ui is on
    mock_hassette.config.web_api.run_ui = request.param
    transport = ASGITransport(app=create_fastapi_app(mock_hassette))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestRoutingErrors:
    @pytest.mark.parametrize("method", ["GET", "POST"])
    async def test_unknown_api_path_is_not_found(self, routing_client: AsyncClient, method: str) -> None:
        """The SPA catch-all never claims an /api path, so run_ui doesn't change the answer."""
        response = await routing_client.request(method, "/api/nonexistent")

        assert_problem(response, status=404, code="not_found", detail="Not Found")

    async def test_wrong_method_is_method_not_allowed(self, routing_client: AsyncClient) -> None:
        response = await routing_client.post("/api/apps")

        assert_problem(response, status=405, code="method_not_allowed", detail="Method Not Allowed")
        assert response.headers["allow"] == "GET"

    async def test_missing_static_file_is_not_found(self, mock_hassette: MagicMock, stub_spa: Path) -> None:
        del stub_spa
        mock_hassette.config.web_api.run_ui = True
        transport = ASGITransport(app=create_fastapi_app(mock_hassette))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/missing.js")

        assert_problem(response, status=404, code="not_found", detail="/missing.js not found")


class TestServerErrors:
    async def test_unhandled_exception_is_internal_error(
        self, app: FastAPI, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The client gets a constant body; the traceback and request go to hassette's own log.

        Asserts on a captured log record on purpose, an exception to the no-caplog rule in
        `tests/TESTING.md`: this log record is the documented behavior (D7, and the API error
        catalog promises it to operators), since uvicorn's own copy never reaches hassette's log.
        """
        # Another test may have turned propagation off; caplog only sees propagated records.
        monkeypatch.setattr(logging.getLogger("hassette"), "propagate", True)

        def broken_dependency() -> None:
            raise RuntimeError("secret internals")

        app.dependency_overrides[get_runtime] = broken_dependency
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        with caplog.at_level(logging.ERROR, logger="hassette.web.errors"):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get("/api/apps")

        assert_problem(response, status=500, code="internal_error", detail="Internal Server Error")
        assert "secret internals" not in response.text
        [record] = [r for r in caplog.records if r.name == "hassette.web.errors"]
        assert record.levelno == logging.ERROR
        assert record.getMessage() == "Unhandled exception on GET /api/apps"
        assert record.exc_info is not None
        assert str(record.exc_info[1]) == "secret internals"

    async def test_degraded_payload_stays_a_success_body(self, client: AsyncClient, mock_hassette: MagicMock) -> None:
        """A `db_degrades_to` 503 is data, not an error: unchanged body and content type (D13)."""
        mock_hassette.telemetry_query_service.get_log_records = telemetry_error()

        response = await client.get("/api/logs/recent")

        assert response.status_code == 503
        assert response.headers["content-type"] == "application/json"
        assert response.json() == []
