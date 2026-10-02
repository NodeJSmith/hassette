"""The served OpenAPI document describes every error response as `application/problem+json`."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from hassette.web.app import create_fastapi_app
from hassette.web.errors import GLOBAL_CODES, PROBLEM_CODES_KEY

PROBLEM_REF = "#/components/schemas/ProblemDetail"


def responses(document: dict[str, Any]) -> Iterator[tuple[str, str, str, dict[str, Any]]]:
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            for status, response in operation.get("responses", {}).items():
                yield path, method, status, response


@pytest.fixture
def document(app: FastAPI) -> dict[str, Any]:
    return app.openapi()


def test_no_fastapi_validation_schemas_remain(document: dict[str, Any]) -> None:
    assert "HTTPValidationError" not in document["components"]["schemas"]
    assert "ValidationError" not in document["components"]["schemas"]
    assert "HTTPValidationError" not in str(document)


def test_every_problem_response_is_problem_json_only(document: dict[str, Any]) -> None:
    problem_responses = [
        (path, method, status, response)
        for path, method, status, response in responses(document)
        if PROBLEM_REF in str(response.get("content", {}))
    ]

    assert problem_responses
    for path, method, status, response in problem_responses:
        assert response["content"] == {"application/problem+json": {"schema": {"$ref": PROBLEM_REF}}}, (
            path,
            method,
            status,
        )


def test_every_validation_422_is_a_problem_response(document: dict[str, Any]) -> None:
    validation_responses = [response for _, _, status, response in responses(document) if status == "422"]

    assert validation_responses
    for response in validation_responses:
        assert response["description"] == "Validation Error"
        assert response["content"] == {"application/problem+json": {"schema": {"$ref": PROBLEM_REF}}}


@pytest.mark.parametrize(
    ("path", "model"),
    [("/api/health/ready", "ReadinessResponse"), ("/api/telemetry/status", "TelemetryStatusResponse")],
)
def test_degraded_503s_keep_their_success_models(document: dict[str, Any], path: str, model: str) -> None:
    content = document["paths"][path]["get"]["responses"]["503"]["content"]

    assert content == {"application/json": {"schema": {"$ref": f"#/components/schemas/{model}"}}}


def test_problem_code_lists_name_only_operation_specific_codes(document: dict[str, Any]) -> None:
    listed = [code for _, _, _, response in responses(document) for code in response.get(PROBLEM_CODES_KEY, ())]

    assert listed
    assert not set(listed) & {str(code) for code in GLOBAL_CODES}


def test_document_does_not_depend_on_run_ui(mock_hassette: MagicMock, stub_spa: Path) -> None:
    """The SPA catch-all is excluded from the schema, so the served document is the same either way."""
    del stub_spa  # only needed for its side effect: the SPA routes register when run_ui is on
    mock_hassette.config.web_api.run_ui = False
    without_ui = create_fastapi_app(mock_hassette).openapi()
    mock_hassette.config.web_api.run_ui = True
    with_ui_app = create_fastapi_app(mock_hassette)

    assert any(getattr(route, "name", None) == "spa_catch_all" for route in with_ui_app.routes)
    assert with_ui_app.openapi() == without_ui
