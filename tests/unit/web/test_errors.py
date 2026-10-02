"""Unit tests for `hassette.web.errors`: the code tables, body builders, and OpenAPI rewrite."""

import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest
from hassette_wire import ProblemCode
from starlette.exceptions import HTTPException

from hassette.web.errors import (
    CODE_DESCRIPTIONS,
    CODE_STATUS,
    GLOBAL_CODES,
    STATUS_TITLES,
    WebApiError,
    problem_response,
    problem_responses,
    rewrite_problem_openapi,
    validation_detail,
)
from tests.support.problem_codes import undeclared_problem_code

PROBLEM_REF = {"$ref": "#/components/schemas/ProblemDetail"}


class TestCodeTables:
    def test_every_code_but_http_error_has_one_status(self) -> None:
        assert set(CODE_STATUS) == set(ProblemCode) - {ProblemCode.HTTP_ERROR}

    def test_only_auth_codes_map_to_401(self) -> None:
        """`DefaultDenyMiddleware` counts every 401 as a failed login; no other code may send one."""
        codes_401 = {code for code, status in CODE_STATUS.items() if status == 401}

        assert codes_401 == {ProblemCode.INVALID_TOKEN, ProblemCode.NOT_AUTHENTICATED}

    def test_every_operation_specific_code_has_a_description(self) -> None:
        assert set(CODE_DESCRIPTIONS) == set(ProblemCode) - GLOBAL_CODES

    def test_titles_cover_every_error_status(self) -> None:
        assert set(STATUS_TITLES) == {status.value for status in HTTPStatus if 400 <= status.value < 600}

    @pytest.mark.parametrize(
        ("status", "title"),
        [(413, "Content Too Large"), (416, "Range Not Satisfiable"), (422, "Unprocessable Content")],
    )
    def test_titles_use_rfc_9110_phrases_on_every_python(self, status: int, title: str) -> None:
        """Python 3.11-3.12 phrase these differently; the table must not follow the interpreter."""
        assert STATUS_TITLES[status] == title


class TestWebApiError:
    def test_status_comes_from_the_code(self) -> None:
        exc = WebApiError(ProblemCode.APP_BLOCKED, "blocked", headers={"x-a": "1"})

        assert (exc.status_code, exc.detail, exc.code, exc.headers) == (
            409,
            "blocked",
            ProblemCode.APP_BLOCKED,
            {"x-a": "1"},
        )
        assert isinstance(exc, HTTPException)

    def test_rejects_the_statusless_fallback_code(self) -> None:
        with pytest.raises(ValueError, match="http_error"):
            WebApiError(ProblemCode.HTTP_ERROR, "nope")


class TestProblemResponse:
    def test_builds_the_rfc_9457_body(self) -> None:
        response = problem_response(ProblemCode.APP_NOT_FOUND, "App 'x' not found", headers={"x-a": "1"})

        assert response.status_code == 404
        assert response.media_type == "application/problem+json"
        assert response.headers["x-a"] == "1"
        assert json.loads(response.body) == {
            "type": "about:blank",
            "title": "Not Found",
            "status": 404,
            "detail": "App 'x' not found",
            "code": "app_not_found",
        }

    def test_status_outside_the_title_table_gets_a_generic_title(self) -> None:
        response = problem_response(ProblemCode.HTTP_ERROR, "odd", status=499)

        assert json.loads(response.body)["title"] == "Error"


class TestProblemResponses:
    def test_groups_codes_by_status_with_one_clause_each(self) -> None:
        declared = problem_responses(
            ProblemCode.INVALID_APP_KEY, ProblemCode.APP_NOT_FOUND, ProblemCode.INSTANCE_NOT_FOUND
        )

        assert sorted(declared) == [400, 404]
        assert declared[404]["x-problem-codes"] == ["app_not_found", "instance_not_found"]
        assert declared[404]["description"] == (
            f"`app_not_found`: {CODE_DESCRIPTIONS[ProblemCode.APP_NOT_FOUND]}; "
            f"`instance_not_found`: {CODE_DESCRIPTIONS[ProblemCode.INSTANCE_NOT_FOUND]}"
        )

    def test_repeated_codes_are_listed_once(self) -> None:
        declared = problem_responses(ProblemCode.APP_NOT_FOUND, ProblemCode.APP_NOT_FOUND)

        assert declared[404]["x-problem-codes"] == ["app_not_found"]

    @pytest.mark.parametrize("code", sorted(GLOBAL_CODES))
    def test_rejects_global_codes(self, code: ProblemCode) -> None:
        with pytest.raises(ValueError, match="global code"):
            problem_responses(code)


def test_validation_detail_never_includes_the_input() -> None:
    errors = [
        {"loc": ("query", "limit"), "msg": "Input should be less than or equal to 1000", "input": "5000"},
        {"loc": ("body", "token"), "msg": "String should have at most 4096 characters", "input": "SECRET"},
    ]

    detail = validation_detail(errors)

    assert detail == (
        "Validation failed: query.limit: Input should be less than or equal to 1000; "
        "body.token: String should have at most 4096 characters"
    )


def _response(schema_name: str, media_type: str = "application/json") -> dict[str, Any]:
    return {"description": "x", "content": {media_type: {"schema": {"$ref": f"#/components/schemas/{schema_name}"}}}}


class TestRewriteProblemOpenapi:
    @pytest.fixture
    def rewritten(self) -> dict[str, Any]:
        document = {
            "paths": {
                "/a": {
                    "get": {
                        "responses": {
                            "200": _response("Thing"),
                            "404": _response("ProblemDetail"),
                            "422": {**_response("HTTPValidationError"), "description": "Validation Error"},
                            "503": _response("ReadinessResponse"),
                        }
                    },
                    "parameters": [],
                }
            },
            "components": {
                "schemas": {
                    "Thing": {},
                    "ProblemDetail": {},
                    "HTTPValidationError": {},
                    "ValidationError": {},
                    "ReadinessResponse": {},
                }
            },
        }
        return rewrite_problem_openapi(document)

    def test_problem_responses_move_to_problem_json(self, rewritten: dict[str, Any]) -> None:
        assert rewritten["paths"]["/a"]["get"]["responses"]["404"]["content"] == {
            "application/problem+json": {"schema": PROBLEM_REF}
        }

    def test_validation_422_becomes_a_problem_response(self, rewritten: dict[str, Any]) -> None:
        assert rewritten["paths"]["/a"]["get"]["responses"]["422"] == {
            "description": "Validation Error",
            "content": {"application/problem+json": {"schema": PROBLEM_REF}},
        }

    def test_success_models_keep_their_media_type_even_with_an_error_status(self, rewritten: dict[str, Any]) -> None:
        responses = rewritten["paths"]["/a"]["get"]["responses"]

        assert responses["200"] == _response("Thing")
        assert responses["503"] == _response("ReadinessResponse")

    def test_fastapi_validation_schemas_are_removed(self, rewritten: dict[str, Any]) -> None:
        assert set(rewritten["components"]["schemas"]) == {"Thing", "ProblemDetail", "ReadinessResponse"}

    def test_non_operation_path_items_pass_through(self, rewritten: dict[str, Any]) -> None:
        assert rewritten["paths"]["/a"]["parameters"] == []


class TestUndeclaredProblemCodeCheck:
    """Self-test for the test-time check that keeps each route's `x-problem-codes` accurate."""

    ROUTE = SimpleNamespace(
        path="/api/apps/{app_key}/config", methods={"GET"}, responses=problem_responses(ProblemCode.APP_NOT_FOUND)
    )

    def test_declared_code_passes(self) -> None:
        assert undeclared_problem_code(self.ROUTE, WebApiError(ProblemCode.APP_NOT_FOUND, "x")) is None

    def test_undeclared_code_is_reported(self) -> None:
        violation = undeclared_problem_code(self.ROUTE, WebApiError(ProblemCode.PATH_TRAVERSAL, "x"))

        assert violation == (
            "GET /api/apps/{app_key}/config raised path_traversal (403) without declaring it in problem_responses()"
        )

    def test_code_declared_under_another_status_is_reported(self) -> None:
        route = SimpleNamespace(path="/x", methods={"GET"}, responses={409: {"x-problem-codes": ["app_not_found"]}})

        assert undeclared_problem_code(route, WebApiError(ProblemCode.APP_NOT_FOUND, "x")) is not None

    @pytest.mark.parametrize(
        "exc",
        [WebApiError(ProblemCode.VALIDATION_FAILED, "x"), HTTPException(status_code=404)],
        ids=["global-code", "framework-exception"],
    )
    def test_global_and_framework_errors_are_exempt(self, exc: HTTPException) -> None:
        assert undeclared_problem_code(self.ROUTE, exc) is None
