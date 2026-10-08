"""What ``tools/generate_client_compat_fixtures.py``'s fixtures must cover, and what they leave out on purpose.

Three kinds of gap fail generation:

- ``route``: a JSON route HEAD or the release serves that no success request reaches. Problem and probe
  requests don't count: they exercise a route's failure, not the body the released client parses.
- ``empty``: a route whose every success response, across all scenarios, is empty (see
  :func:`is_empty_body`), so the released client never parses a populated body from it.
- ``problem``: a ``ProblemCode`` HEAD defines that no problem request answers with.

:data:`EXCLUDED` suppresses a gap, with the reason. An exclusion that no longer matches a gap is itself
reported, so the table can't outlive what it excludes.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from client_compat_requests import FixtureRequest
from hassette_wire import ProblemCode

CoverageKind = Literal["route", "empty", "problem"]

EXCLUDED: dict[tuple[CoverageKind, str], str] = {
    ("route", "POST /api/auth/session"): "browser-only: hassette-client has no method for it",
    ("problem", ProblemCode.INVALID_TOKEN.value): (
        "only POST /api/auth/session answers it, and that route is excluded; a wrong bearer token gets "
        "not_authenticated"
    ),
    ("problem", ProblemCode.HTTP_ERROR.value): (
        "the fallback for an unmapped HTTPException: it has no fixed status and no route raises it deliberately"
    ),
}
"""Gaps left open on purpose, keyed by (kind, target), each with the reason. A ``route`` or ``empty`` target
is ``"METHOD /path/template"``; a ``problem`` target is the ``ProblemCode`` value."""

Answered = tuple[FixtureRequest, Any]
"""A request paired with its parsed JSON response body."""

GAP_DESCRIPTIONS: Mapping[CoverageKind, str] = {
    "route": "no success request reaches it; add one to success_requests()",
    "empty": "every success response is empty (null, [] or only empty lists); seed data that populates it",
    "problem": "no problem request answers with it; add one to PROBLEM_REQUESTS",
}

SUMMARY_LABELS: Mapping[CoverageKind, str] = {
    "route": "routes reached by a success request",
    "empty": "reached routes with a populated body",
    "problem": "problem codes answered",
}


@dataclass(frozen=True)
class CoverageReport:
    gaps: list[str]
    """Every gap the exclusions don't name, then every exclusion that matches no gap, one readable line each.
    Generation fails unless this is empty."""
    summary: list[str]
    """One line per kind, counting what's covered and what's excluded, for the generator to print."""


def is_empty_body(body: Any) -> bool:
    """Whether a success body carries no data.

    It doesn't when it is ``null``, ``[]``, or an object with at least one list field whose list fields are all
    empty. Only the top level is inspected.
    """
    if body is None or body == []:
        return True
    if not isinstance(body, dict):
        return False
    lists = [value for value in body.values() if isinstance(value, list)]
    return bool(lists) and not any(lists)


def coverage_report(
    routes: Iterable[tuple[str, str]],
    answered: Iterable[Answered],
    excluded: Mapping[tuple[CoverageKind, str], str] = EXCLUDED,
) -> CoverageReport:
    """The gaps ``answered`` leaves across ``routes`` and every ``ProblemCode``, with ``excluded`` applied."""
    answered = list(answered)
    successes = [(request, body) for request, body in answered if request.is_success]
    reached = {request.route_key for request, _ in successes}
    populated = {request.route_key for request, body in successes if not is_empty_body(body)}
    codes = {request.problem_code.value for request, _ in answered if request.problem_code is not None}
    targets: dict[CoverageKind, set[str]] = {
        "route": {f"{method} {path}" for method, path in routes},
        "empty": reached,
        "problem": {code.value for code in ProblemCode},
    }
    covered: dict[CoverageKind, set[str]] = {"route": reached, "empty": populated, "problem": codes}
    found: set[tuple[CoverageKind, str]] = {
        (kind, target) for kind in targets for target in targets[kind] - covered[kind]
    }

    gaps = [f"{kind} {target}: {GAP_DESCRIPTIONS[kind]}" for kind, target in sorted(found - excluded.keys())]
    gaps += [
        f"{kind} {target}: excluded, but there's no such gap; remove it from EXCLUDED"
        for kind, target in sorted(excluded.keys() - found)
    ]
    summary = [
        f"{SUMMARY_LABELS[kind]}: {len(targets[kind] & covered[kind])} of {len(targets[kind])} covered, "
        f"{sum(gap_kind == kind for gap_kind, _ in found & excluded.keys())} excluded"
        for kind in targets
    ]
    return CoverageReport(gaps, summary)
