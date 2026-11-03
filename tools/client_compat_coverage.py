"""What ``tools/generate_client_compat_fixtures.py``'s fixtures must cover, and what they leave out on purpose.

Three kinds of gap fail generation:

- ``route``: a JSON route HEAD or the release serves that no success request reaches. Problem and probe
  requests don't count: they exercise a route's failure, not the body the released client parses.
- ``empty``: a part of a route's body that is empty in every success response across all scenarios (see
  :func:`body_parts`), so the released client never parses a populated one: the whole body when it's ``null``
  or a list, otherwise each top-level list field on its own.
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
"""Gaps left open on purpose, keyed by (kind, target), each with the reason. A ``route`` target is
``"METHOD /path/template"``; an ``empty`` target is that or, for a list field, ``"METHOD /path/template field"``
(see :func:`body_parts`); a ``problem`` target is the ``ProblemCode`` value."""

Answered = tuple[FixtureRequest, Any]
"""A request paired with its parsed JSON response body."""

GAP_DESCRIPTIONS: Mapping[CoverageKind, str] = {
    "route": "no success request reaches it; add one to success_requests()",
    "empty": "null or [] in every success response; seed data that populates it",
    "problem": "no problem request answers with it; add one to PROBLEM_REQUESTS",
}

SUMMARY_LABELS: Mapping[CoverageKind, str] = {
    "route": "routes reached by a success request",
    "empty": "body parts and list fields populated",
    "problem": "problem codes answered",
}


@dataclass(frozen=True)
class CoverageReport:
    gaps: list[str]
    """Every gap the exclusions don't name, then every exclusion that matches no gap, one readable line each.
    Generation fails unless this is empty."""
    summary: list[str]
    """One line per kind, counting what's covered and what's excluded, for the generator to print."""


def body_parts(route_key: str, body: Any) -> dict[str, bool]:
    """The parts of a success body coverage tracks, each mapped to whether this body populates it.

    An object's parts are its top-level list fields, named ``"<route_key> <field>"``, so one populated list
    can't hide another that's always empty; an object with no list fields is one populated part named
    ``route_key``. Any other body is one part named ``route_key``, empty when it is ``null`` or ``[]``. Nested
    lists aren't inspected.
    """
    if not isinstance(body, dict):
        return {route_key: body is not None and body != []}
    lists = {f"{route_key} {field}": bool(value) for field, value in body.items() if isinstance(value, list)}
    if not lists:
        return {route_key: True}
    return lists


def coverage_report(
    routes: Iterable[tuple[str, str]],
    answered: Iterable[Answered],
    excluded: Mapping[tuple[CoverageKind, str], str] = EXCLUDED,
) -> CoverageReport:
    """The gaps ``answered`` leaves across ``routes`` and every ``ProblemCode``, with ``excluded`` applied."""
    answered = list(answered)
    successes = [(request, body) for request, body in answered if request.is_success]
    reached = {request.route_key for request, _ in successes}
    parts: set[str] = set()
    populated: set[str] = set()
    for request, body in successes:
        for part, is_populated in body_parts(request.route_key, body).items():
            parts.add(part)
            if is_populated:
                populated.add(part)
    codes = {request.problem_code.value for request, _ in answered if request.problem_code is not None}
    targets: dict[CoverageKind, set[str]] = {
        "route": {f"{method} {path}" for method, path in routes},
        "empty": parts,
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
