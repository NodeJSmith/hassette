"""CI: the latest released hassette-client handles every response HEAD's server sends.

Reads the fixtures ``tools/generate_client_compat_fixtures.py`` writes and runs each response through the
release's own response handling, ``hassette_client.transport.interpret_response``, which every client
method's response passes through: the status and ``Content-Type`` decide whether the body is parsed as the
type the release declares for that route, parsed as a probe's status model, or raised as an error. A success
or probe fixture must come back parsed; a problem fixture must raise a ``HassetteHTTPError`` carrying the
fixture's problem code, of the class the release maps that code to when it maps it to one. A fixture that
fails that, or whose type the release's ``hassette_wire`` doesn't export, fails the check, named by its route
and file.

``interpret_response``, ``RawResponse`` and ``CODE_ERRORS`` live in the release's private modules, so a
release that drops one, or changes the parameters or fields this check passes, stops the check with a message
naming the mismatch, before any fixture runs.

It runs in a venv holding only the release named in the fixtures' ``release.json``
(``uv run nox -s client_compat``), so it imports nothing from this repository, and it refuses to run
against the workspace copies, a different version, or a fixture directory that doesn't match the list in
``release.json``. Complements ``tools/check_wire_compat.py``, which compares schemas: this catches
serialization a schema doesn't show, and bugs in the release's lenient parsing and error mapping.

Rationale: the approach, including running ``interpret_response``, is in
``design/research/2026-10-08-released-client-compat-approaches/research.md``, and the release selection in
``design/research/2026-10-08-client-compat-release-baseline/research.md``. The check originates in
``design/research/2026-10-02-hassette-client-transport/research.md``, "Q5. Cross-version CI".
"""

import argparse
import functools
import inspect
import json
import operator
import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import hassette_client
import hassette_wire
from hassette_client import ResponseValidationError

# A release without these private symbols must still import this module, so setup_problem can name what's
# missing; the annotations that use them are quoted so a failed import doesn't break the definitions.
try:
    from hassette_client.errors import CODE_ERRORS, HassetteHTTPError
    from hassette_client.transport import RawResponse, interpret_response, media_kind, parse_media_type
except ImportError as exc:
    missing_release_symbol: str | None = str(exc)
else:
    missing_release_symbol = None

REPO_ROOT = Path(__file__).resolve().parent.parent

# Kept in sync with RELEASE_FILE in tools/generate_client_compat_fixtures.py and the literal in noxfile.py's
# client_compat.
RELEASE_FILE = "release.json"
"""Written by the generator next to the fixtures; names the release their types come from and lists them."""

PROBE_PARAMETER = "status_model_on_503"
"""The ``interpret_response`` keyword :func:`check_fixture` passes a fixture's ``probe`` flag as."""

RAW_RESPONSE_FIELDS = ("status", "media_type", "kind", "payload", "truncated", "location")
"""The ``RawResponse`` keyword fields :func:`raw_response` passes."""


class MissingTypeError(Exception):
    """A response type names a ``hassette_wire`` export the installed release doesn't have."""


@dataclass(frozen=True)
class Failure:
    fixture: Path
    route: str
    reason: str


def resolve_type(spec: Any) -> Any:
    """Rebuild a fixture's response type against the installed ``hassette_wire``.

    The encoding half is ``schema_type_spec`` in ``tools/generate_client_compat_fixtures.py``; the two are kept
    in sync.

    Raises:
        MissingTypeError: The spec names a model this release doesn't export.
        ValueError: The spec isn't one ``generate_client_compat_fixtures.schema_type_spec`` writes.
    """
    if spec == "None":
        return type(None)
    if isinstance(spec, str):
        try:
            return getattr(hassette_wire, spec)
        except AttributeError:
            raise MissingTypeError(spec) from None
    match spec:
        case ["list", item]:
            return list[resolve_type(item)]
        case ["union", *members] if members:
            return functools.reduce(operator.or_, (resolve_type(member) for member in members))
        case _:
            raise ValueError(f"unrecognized response type spec: {spec!r}")


def raw_response(fixture: dict[str, Any]) -> "RawResponse":
    """The fixture's response as the release's transport reads it off the wire."""
    media_type = parse_media_type(fixture["content_type"] or None)
    return RawResponse(
        status=fixture["status"],
        media_type=media_type,
        kind=media_kind(media_type),
        payload=fixture["body"].encode(),
        truncated=False,
        location=None,
    )


def problem_mismatch(error: "HassetteHTTPError", expected_code: str) -> str | None:
    """Why ``error`` isn't what a problem fixture with ``expected_code`` calls for, or ``None`` when it is.

    A code the release doesn't map to its own class resolves by status, which the release decides alone, so
    only the code is checked for it.
    """
    if error.code != expected_code:
        code = None if error.code is None else str(error.code)
        return f"raised {type(error).__name__} with code {code!r}, expected code {expected_code!r}"
    expected_class = {code.value: error_class for code, error_class in CODE_ERRORS.items()}.get(expected_code)
    if expected_class is not None and type(error) is not expected_class:
        return f"raised {type(error).__name__}, but the release maps {expected_code!r} to {expected_class.__name__}"
    return None


def check_fixture(path: Path) -> Failure | None:
    fixture = json.loads(path.read_text())
    route = fixture.get("route", path.name)
    expected_code = fixture.get("problem_code")
    try:
        response_type = resolve_type(fixture["response_type"])
        response = raw_response(fixture)
        interpret_response(response, response_type, fixture["request"], status_model_on_503=fixture["probe"])
    except MissingTypeError as exc:
        return Failure(path, route, f"hassette_wire {version('hassette-wire')} has no {exc}")
    except HassetteHTTPError as exc:
        if expected_code is None:
            return Failure(path, route, f"{type(exc).__name__}: {exc}")
        mismatch = problem_mismatch(exc, expected_code)
        return Failure(path, route, mismatch) if mismatch else None
    except ResponseValidationError as exc:
        return Failure(path, route, str(exc))
    except Exception as exc:
        # Reported per fixture rather than raised, so one bad fixture doesn't hide the rest.
        return Failure(path, route, f"{type(exc).__name__}: {exc}")
    if expected_code is not None:
        return Failure(path, route, f"parsed a {fixture['status']} {expected_code!r} problem instead of raising")
    return None


def setup_problem(fixtures: Path, repo_root: Path) -> str | None:
    """Why the fixtures can't be checked in this environment, or ``None`` when they can."""
    local = [
        module.__name__
        for module in (hassette_client, hassette_wire)
        if module.__file__ is not None and repo_root in Path(module.__file__).resolve().parents
    ]
    if local:
        return (
            f"{', '.join(local)} imported from this checkout, not a release. Run in a venv holding only the "
            "released hassette-client (uv run nox -s client_compat)."
        )
    installed = version("hassette-client")
    if missing_release_symbol is not None:
        return (
            f"hassette-client {installed} lacks a private symbol this check imports ({missing_release_symbol}); "
            "update tools/check_client_compat.py."
        )
    if mismatch := release_api_mismatch():
        return f"hassette-client {installed}'s private API changed: {mismatch}; update tools/check_client_compat.py."
    release_file = fixtures / RELEASE_FILE
    if not release_file.exists():
        return f"No {RELEASE_FILE} in {fixtures}; the generator didn't run there."
    release = json.loads(release_file.read_text())
    if installed != release["version"]:
        return f"The fixtures are typed by hassette-client {release['version']}, but {installed} is installed."
    listed = set(release["fixtures"])
    on_disk = {path.name for path in fixture_paths(fixtures)}
    if listed != on_disk:
        return (
            f"The fixtures in {fixtures} don't match {RELEASE_FILE}: missing {sorted(listed - on_disk)}, "
            f"unlisted {sorted(on_disk - listed)}."
        )
    return None


def release_api_mismatch() -> str | None:
    """How the release's ``interpret_response`` or ``RawResponse`` differs from what this check calls them with."""
    if PROBE_PARAMETER not in inspect.signature(interpret_response).parameters:
        return f"interpret_response has no {PROBE_PARAMETER} parameter"
    missing = [name for name in RAW_RESPONSE_FIELDS if name not in inspect.signature(RawResponse).parameters]
    if missing:
        return f"RawResponse has no {', '.join(missing)} field"
    return None


def fixture_paths(fixtures: Path) -> list[Path]:
    return sorted(path for path in fixtures.glob("*.json") if path.name != RELEASE_FILE)


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description="Check HEAD response fixtures with the installed hassette-client.")
    parser.add_argument("fixtures", type=Path, help="Directory the generator wrote the fixtures to.")
    args = parser.parse_args(argv)

    problem = setup_problem(args.fixtures, repo_root)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    paths = fixture_paths(args.fixtures)
    if not paths:
        print(f"No fixtures in {args.fixtures}; the generator wrote nothing.", file=sys.stderr)
        return 1

    release = f"hassette-client {version('hassette-client')}"
    for route in json.loads((args.fixtures / RELEASE_FILE).read_text())["newer_than_release"]:
        print(f"not checked: {release} doesn't call {route}, which is newer")
    failures = [failure for path in paths if (failure := check_fixture(path))]
    if failures:
        print(f"{release} mishandles {len(failures)} of {len(paths)} HEAD responses:", file=sys.stderr)
        for failure in failures:
            print(f"\n{failure.route} ({failure.fixture.name}):\n  {failure.reason}", file=sys.stderr)
        return 1
    print(f"{release} handled all {len(paths)} HEAD responses.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
