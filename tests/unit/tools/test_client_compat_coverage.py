"""Tests for tools/client_compat_coverage.py: each gap kind, exclusions, and stale exclusions."""

from typing import Any

import pytest
from client_compat_coverage import EXCLUDED, Answered, body_parts, coverage_report
from client_compat_requests import FixtureRequest
from hassette_wire import ProblemCode

PROBLEM_BODY = {"code": "x"}


def every_problem_answered() -> list[Answered]:
    """One answered problem request per code, so a test sees only the gaps of the kind it's about."""
    return [(FixtureRequest(f"p-{code}", "GET", "/api/p", problem_code=code), PROBLEM_BODY) for code in ProblemCode]


def success(route: str, body: Any = None, name: str = "s") -> Answered:
    method, path = route.split(" ", 1)
    return FixtureRequest(name, method, path), {"value": 1} if body is None else body


@pytest.mark.parametrize(
    ("body", "parts"),
    [
        (None, {"R": False}),
        ([], {"R": False}),
        ([{}], {"R": True}),
        ({"ok": True}, {"R": True}),
        ({}, {"R": True}),
        (0, {"R": True}),
        ({"records": [], "truncated": False}, {"R records": False}),
        ({"records": [{}], "other": [], "n": 1}, {"R records": True, "R other": False}),
    ],
)
def test_body_parts(body: Any, parts: dict[str, bool]) -> None:
    assert body_parts("R", body) == parts


def test_route_gap_counts_only_success_requests() -> None:
    routes = [("GET", "/api/a"), ("GET", "/api/b"), ("GET", "/api/c")]
    answered = [
        success("GET /api/a"),
        (FixtureRequest("b", "GET", "/api/b", problem_code=ProblemCode.NOT_FOUND), PROBLEM_BODY),
        (FixtureRequest("c", "GET", "/api/c", probe=True), {"ready": False}),
        *every_problem_answered(),
    ]

    assert coverage_report(routes, answered, excluded={}).gaps == [
        "route GET /api/b: no success request reaches it; add one to success_requests()",
        "route GET /api/c: no success request reaches it; add one to success_requests()",
    ]


def test_empty_gap_needs_every_success_body_empty() -> None:
    routes = [("GET", "/api/always"), ("GET", "/api/once")]
    answered = [
        success("GET /api/always", []),
        success("GET /api/always", [], name="again"),
        success("GET /api/once", []),
        success("GET /api/once", [{"id": 1}], name="populated"),
        *every_problem_answered(),
    ]

    [gap] = coverage_report(routes, answered, excluded={}).gaps

    assert gap.startswith("empty GET /api/always: null or [] in every success response")


def test_one_populated_list_field_does_not_hide_an_always_empty_one() -> None:
    answered = [
        success("GET /api/health", {"services": [], "boot_issues": [{}]}),
        success("GET /api/health", {"services": [], "boot_issues": []}, name="again"),
        *every_problem_answered(),
    ]

    [gap] = coverage_report([("GET", "/api/health")], answered, excluded={}).gaps

    assert gap.startswith("empty GET /api/health services:")


def test_empty_gap_ignores_probe_bodies() -> None:
    probe = FixtureRequest("probe", "GET", "/api/status", probe=True)
    answered = [success("GET /api/status"), (probe, []), *every_problem_answered()]

    assert coverage_report([("GET", "/api/status")], answered, excluded={}).gaps == []


def test_problem_gap_names_each_unanswered_code() -> None:
    answered = [entry for entry in every_problem_answered() if entry[0].problem_code is not ProblemCode.APP_BLOCKED]

    assert coverage_report([], answered, excluded={}).gaps == [
        "problem app_blocked: no problem request answers with it; add one to PROBLEM_REQUESTS"
    ]


@pytest.mark.parametrize(
    ("exclusion", "answered"),
    [
        (("route", "GET /api/a"), every_problem_answered()),
        (("empty", "GET /api/a"), [success("GET /api/a", []), *every_problem_answered()]),
        (
            ("problem", "app_blocked"),
            [success("GET /api/a")]
            + [entry for entry in every_problem_answered() if entry[0].problem_code is not ProblemCode.APP_BLOCKED],
        ),
    ],
)
def test_an_exclusion_suppresses_its_gap(exclusion: Any, answered: list[Answered]) -> None:
    assert coverage_report([("GET", "/api/a")], answered, excluded={exclusion: "reason"}).gaps == []


def test_a_stale_exclusion_is_a_gap() -> None:
    answered = [success("GET /api/a"), *every_problem_answered()]
    excluded = {("route", "GET /api/a"): "now covered", ("problem", "no_such_code"): "never existed"}

    assert coverage_report([("GET", "/api/a")], answered, excluded=excluded).gaps == [
        "problem no_such_code: excluded, but there's no such gap; remove it from EXCLUDED",
        "route GET /api/a: excluded, but there's no such gap; remove it from EXCLUDED",
    ]


def test_every_problem_exclusion_names_a_real_code() -> None:
    codes = {code.value for code in ProblemCode}
    assert {target for kind, target in EXCLUDED if kind == "problem"} <= codes


def test_coverage_report_summarizes_covered_and_excluded() -> None:
    excluded = {
        ("route", "GET /api/b"): "reason",
        ("empty", "GET /api/c"): "reason",
        ("problem", "app_blocked"): "reason",
    }
    answered = [success("GET /api/a"), success("GET /api/c", [])] + [
        entry for entry in every_problem_answered() if entry[0].problem_code is not ProblemCode.APP_BLOCKED
    ]

    report = coverage_report([("GET", "/api/a"), ("GET", "/api/b"), ("GET", "/api/c")], answered, excluded=excluded)

    assert report.gaps == []
    assert report.summary == [
        "routes reached by a success request: 2 of 3 covered, 1 excluded",
        "body parts and list fields populated: 1 of 2 covered, 1 excluded",
        f"problem codes answered: {len(ProblemCode) - 1} of {len(ProblemCode)} covered, 1 excluded",
    ]
