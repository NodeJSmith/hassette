"""Test-time check that a route only raises problem codes its OpenAPI declaration lists.

Each route declares its operation-specific codes with ``problem_responses(...)``, which become the
``x-problem-codes`` list on each error status in ``/api/openapi.json``. Nothing at runtime ties
those lists to what the route actually raises, so this check runs against every
``WebApiError`` the web API integration tests provoke and fails the test on a mismatch. It never
runs in production.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from hassette.web.errors import GLOBAL_CODES, PROBLEM_CODES_KEY, WebApiError

ExceptionHandler = Callable[[Request, HTTPException], Awaitable[Response]]


def undeclared_problem_code(route: Any, exc: HTTPException) -> str | None:
    """Describe ``exc`` if ``route`` raised an operation-specific code it doesn't declare, else None.

    Global codes are exempt (any route can produce them), as is any error raised outside a route,
    such as a routing 404.
    """
    if not isinstance(exc, WebApiError) or exc.code in GLOBAL_CODES or route is None:
        return None
    responses: Mapping[Any, Any] = getattr(route, "responses", {})
    declared = (responses.get(exc.status_code) or responses.get(str(exc.status_code)) or {}).get(PROBLEM_CODES_KEY, ())
    if str(exc.code) in declared:
        return None
    methods = ",".join(sorted(getattr(route, "methods", ())))
    return f"{methods} {route.path} raised {exc.code!s} ({exc.status_code}) without declaring it in problem_responses()"


def checking_handler(handler: ExceptionHandler, violations: list[str]) -> ExceptionHandler:
    """Wrap ``handler`` so every undeclared code it sees is appended to ``violations``."""

    async def check_then_handle(request: Request, exc: HTTPException) -> Response:
        violation = undeclared_problem_code(request.scope.get("route"), exc)
        if violation is not None:
            violations.append(violation)
        return await handler(request, exc)

    return check_then_handle
