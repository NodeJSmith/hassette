"""RFC 9457 problem details for every error response under ``/api``.

Every error body is ``application/problem+json`` carrying a :class:`~hassette_wire.ProblemCode`
in its ``code`` member. Routes raise :class:`WebApiError`; FastAPI's own and Starlette's routing
``HTTPException``s, request validation errors, and unhandled exceptions are converted by the
handlers here; the two middleware responses call :func:`problem_response` directly. Nothing else
in ``hassette.web`` builds an error body, and ``tests/unit/web/test_error_mechanism_guard.py``
enforces that.

Degraded-payload 503s (``db_degrades_to``, ``/api/health/ready``, ``/api/telemetry/status``) are
success models with an error status, not problem bodies, and nothing here touches them.

This module must not import ``hassette.core`` (the ``web-no-core`` boundary).
"""

from collections.abc import Callable, Mapping, Sequence
from logging import getLogger
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.utils import is_body_allowed_for_status_code
from hassette_wire import ProblemCode, ProblemDetail
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

LOGGER = getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"

CODE_STATUS: Mapping[ProblemCode, int] = {
    ProblemCode.INVALID_APP_KEY: 400,
    ProblemCode.APP_NOT_FOUND: 404,
    ProblemCode.INSTANCE_NOT_FOUND: 404,
    ProblemCode.BOOTSTRAP_NOT_RELEASED: 409,
    ProblemCode.APP_BLOCKED: 409,
    ProblemCode.ACTION_FAILED: 500,
    ProblemCode.TELEMETRY_UNAVAILABLE: 503,
    ProblemCode.SOURCE_NOT_FOUND: 404,
    ProblemCode.PATH_TRAVERSAL: 403,
    ProblemCode.SOURCE_UNAVAILABLE: 500,
    ProblemCode.INVALID_TOKEN: 401,
    ProblemCode.NOT_AUTHENTICATED: 401,
    ProblemCode.JOB_NOT_REGISTERED: 409,
    ProblemCode.VALIDATION_FAILED: 422,
    ProblemCode.BODY_TOO_LARGE: 413,
    ProblemCode.NOT_FOUND: 404,
    ProblemCode.METHOD_NOT_ALLOWED: 405,
    ProblemCode.INTERNAL_ERROR: 500,
}
"""The one HTTP status each code is sent with. ``http_error`` is absent: it carries the status of
whatever unmapped ``HTTPException`` produced it.

Only ``invalid_token`` and ``not_authenticated`` may map to 401. ``DefaultDenyMiddleware`` counts
every outgoing 401 as a failed authentication attempt, so any other 401 code would inflate that
count.
"""

GLOBAL_CODES: frozenset[ProblemCode] = frozenset(
    {
        ProblemCode.NOT_FOUND,
        ProblemCode.METHOD_NOT_ALLOWED,
        ProblemCode.HTTP_ERROR,
        ProblemCode.INTERNAL_ERROR,
        ProblemCode.NOT_AUTHENTICATED,
        ProblemCode.BODY_TOO_LARGE,
        ProblemCode.VALIDATION_FAILED,
    }
)
"""Codes any route can produce (routing, middleware, request validation, unhandled errors).

They are documented once in the error catalog and never listed in a route's ``x-problem-codes``.
"""

CODE_DESCRIPTIONS: Mapping[ProblemCode, str] = {
    ProblemCode.INVALID_APP_KEY: "the app key is not a valid app key",
    ProblemCode.APP_NOT_FOUND: "no app with this key is configured",
    ProblemCode.INSTANCE_NOT_FOUND: "the instance index is out of range for the app's current config",
    ProblemCode.BOOTSTRAP_NOT_RELEASED: "app bootstrap prerequisites are not ready yet (retry later)",
    ProblemCode.APP_BLOCKED: "the app is blocked by the --app filter (not retryable)",
    ProblemCode.ACTION_FAILED: "the action ran but failed, or left a targeted instance failed",
    ProblemCode.TELEMETRY_UNAVAILABLE: "the telemetry store could not be read",
    ProblemCode.SOURCE_NOT_FOUND: "the app's source file does not exist",
    ProblemCode.PATH_TRAVERSAL: "the app's source path resolves outside its app directory",
    ProblemCode.SOURCE_UNAVAILABLE: "the app's source file could not be read",
    ProblemCode.INVALID_TOKEN: "the token is wrong",
    ProblemCode.JOB_NOT_REGISTERED: "the job has no live registration",
}
"""OpenAPI response-description clause for each operation-specific code."""

STATUS_TITLES: Mapping[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    407: "Proxy Authentication Required",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    411: "Length Required",
    412: "Precondition Failed",
    413: "Content Too Large",
    414: "URI Too Long",
    415: "Unsupported Media Type",
    416: "Range Not Satisfiable",
    417: "Expectation Failed",
    418: "I'm a Teapot",
    421: "Misdirected Request",
    422: "Unprocessable Content",
    423: "Locked",
    424: "Failed Dependency",
    425: "Too Early",
    426: "Upgrade Required",
    428: "Precondition Required",
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    451: "Unavailable For Legal Reasons",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
    505: "HTTP Version Not Supported",
    506: "Variant Also Negotiates",
    507: "Insufficient Storage",
    508: "Loop Detected",
    510: "Not Extended",
    511: "Network Authentication Required",
}
"""``title`` for each 4xx/5xx status: the RFC 9110 reason phrase, or the IANA registry phrase where
RFC 9110 defines none.

A literal table rather than ``http.HTTPStatus`` because Python renamed several phrases in 3.13
(413, 422), and both the response body and ``openapi.json`` must be identical on every supported
Python. ``418`` uses its RFC 2324 phrase, since RFC 9110 only marks it unused.
"""

FALLBACK_TITLE = "Error"
"""``title`` for a status outside :data:`STATUS_TITLES`."""

FALLBACK_CODES: Mapping[int, ProblemCode] = {404: ProblemCode.NOT_FOUND, 405: ProblemCode.METHOD_NOT_ALLOWED}
"""Code for an ``HTTPException`` that isn't a :class:`WebApiError`. Any other status gets ``http_error``."""

INTERNAL_ERROR_DETAIL = "Internal Server Error"
"""Constant ``detail`` for unhandled exceptions; exception text never reaches the client."""

PROBLEM_CODES_KEY = "x-problem-codes"
"""OpenAPI response extension listing the operation-specific codes a route can send with that status."""

_SCHEMA_REF_PREFIX = "#/components/schemas/"
_PROBLEM_DETAIL_REF = f"{_SCHEMA_REF_PREFIX}{ProblemDetail.__name__}"
_VALIDATION_ERROR_REF = f"{_SCHEMA_REF_PREFIX}HTTPValidationError"
_FASTAPI_VALIDATION_SCHEMAS = ("HTTPValidationError", "ValidationError")


class WebApiError(HTTPException):
    """An error a route raises; becomes a problem body with ``code`` and the code's fixed status.

    Subclasses Starlette's ``HTTPException`` so one handler serves this and the framework's own
    ``HTTPException``s.
    """

    def __init__(self, code: ProblemCode, detail: str, headers: Mapping[str, str] | None = None) -> None:
        if code not in CODE_STATUS:
            raise ValueError(f"{code!r} has no fixed status and can't be raised by a route")
        super().__init__(status_code=CODE_STATUS[code], detail=detail, headers=headers)
        self.code = code


def problem_response(
    code: ProblemCode, detail: str, *, status: int | None = None, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    """Build the ``application/problem+json`` response for ``code``. The only error-body builder.

    ``status`` defaults to the code's status in :data:`CODE_STATUS`; only the ``http_error``
    fallback passes one.
    """
    resolved_status = CODE_STATUS[code] if status is None else status
    body = ProblemDetail(
        title=STATUS_TITLES.get(resolved_status, FALLBACK_TITLE),
        status=resolved_status,
        detail=detail,
        code=code,
    )
    return JSONResponse(
        body.model_dump(mode="json"), status_code=resolved_status, headers=headers, media_type=PROBLEM_MEDIA_TYPE
    )


def problem_responses(*codes: ProblemCode) -> dict[int | str, dict[str, Any]]:
    """Declare a route's operation-specific error codes for OpenAPI, grouped by status.

    Each status gets ``ProblemDetail`` as its model, a description with one clause per code, and
    the codes themselves under ``x-problem-codes``. Global codes (:data:`GLOBAL_CODES`) are
    rejected: the error catalog documents them once for every route.
    """
    by_status: dict[int, list[ProblemCode]] = {}
    for code in codes:
        if code in GLOBAL_CODES:
            raise ValueError(f"{code!r} is a global code; don't declare it per route")
        status_codes = by_status.setdefault(CODE_STATUS[code], [])
        if code not in status_codes:
            status_codes.append(code)

    return {
        status: {
            "model": ProblemDetail,
            "description": "; ".join(f"`{code}`: {CODE_DESCRIPTIONS[code]}" for code in status_codes),
            PROBLEM_CODES_KEY: [str(code) for code in status_codes],
        }
        for status, status_codes in sorted(by_status.items())
    }


def validation_detail(errors: Sequence[Any]) -> str:
    """Summarize validation errors from their ``loc`` and ``msg`` only, never the rejected input."""
    parts = [f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in errors]
    return f"Validation failed: {'; '.join(parts)}"


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:  # noqa: ARG001
    """Convert any ``HTTPException`` (a route's :class:`WebApiError` or the framework's) to a problem body."""
    headers = exc.headers
    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=headers)
    if isinstance(exc, WebApiError):
        return problem_response(exc.code, exc.detail, headers=headers)
    code = FALLBACK_CODES.get(exc.status_code, ProblemCode.HTTP_ERROR)
    return problem_response(code, exc.detail, status=exc.status_code, headers=headers)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:  # noqa: ARG001
    """Convert FastAPI's request validation 422 to a ``validation_failed`` problem body."""
    return problem_response(ProblemCode.VALIDATION_FAILED, validation_detail(exc.errors()))


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """Log an unhandled exception with its request, then answer with a constant ``internal_error``.

    Runs in Starlette's ``ServerErrorMiddleware``, outside CORS, so the 500 carries no CORS
    headers. Starlette re-raises after this returns, and uvicorn logs it again to its own stderr
    handler; this record is the one that reaches hassette's log and the web UI.
    """
    LOGGER.exception("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return problem_response(ProblemCode.INTERNAL_ERROR, INTERNAL_ERROR_DETAIL)


def install_problem_handlers(app: FastAPI) -> None:
    """Register the three handlers that turn every error into a problem body.

    Uses the ``exception_handler`` decorator rather than ``add_exception_handler``: the latter's
    signature types every handler's exception parameter as plain ``Exception``.
    """
    app.exception_handler(HTTPException)(http_exception_handler)
    app.exception_handler(RequestValidationError)(validation_exception_handler)
    app.exception_handler(Exception)(unhandled_exception_handler)


def install_problem_openapi(app: FastAPI) -> None:
    """Make ``app.openapi()`` describe every error response as ``application/problem+json``.

    FastAPI's documented extension point for post-processing the generated document: the bound
    ``openapi`` is replaced with one that rewrites the generated schema once and caches it.
    """
    generate: Callable[[], dict[str, Any]] = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = rewrite_problem_openapi(generate())
        return app.openapi_schema

    app.openapi = openapi  # pyright: ignore[reportAttributeAccessIssue]


def rewrite_problem_openapi(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``document`` with problem responses under ``application/problem+json``.

    - A response whose schema references ``ProblemDetail`` moves to ``application/problem+json``.
    - FastAPI's automatic ``HTTPValidationError`` 422 becomes a ``ProblemDetail`` problem response.
    - The ``HTTPValidationError`` and ``ValidationError`` components are removed.

    Matching is on schema references, never on status: the readiness and telemetry-status 503s
    are success models and must stay ``application/json``.
    """
    paths = {
        path: {method: _rewrite_operation(operation) for method, operation in operations.items()}
        for path, operations in document.get("paths", {}).items()
    }
    components = dict(document.get("components", {}))
    schemas = {
        name: schema
        for name, schema in components.get("schemas", {}).items()
        if name not in _FASTAPI_VALIDATION_SCHEMAS
    }
    components["schemas"] = schemas
    return {**document, "paths": paths, "components": components}


def _rewrite_operation(operation: Any) -> Any:
    if not isinstance(operation, Mapping) or "responses" not in operation:
        return operation
    responses = {status: _rewrite_response(response) for status, response in operation["responses"].items()}
    return {**operation, "responses": responses}


def _rewrite_response(response: Mapping[str, Any]) -> dict[str, Any]:
    content: Mapping[str, Any] = response.get("content", {})
    refs = {_schema_ref(media) for media in content.values()}
    if _VALIDATION_ERROR_REF in refs:
        problem_content = {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": _PROBLEM_DETAIL_REF}}}
        return {**response, "content": problem_content}
    if _PROBLEM_DETAIL_REF in refs:
        problem_content = {PROBLEM_MEDIA_TYPE: content["application/json"]}
        return {**response, "content": problem_content}
    return dict(response)


def _schema_ref(media: Mapping[str, Any]) -> str | None:
    return media.get("schema", {}).get("$ref")
