"""CI: the latest released hassette-client parses every response HEAD's server sends.

Reads the fixtures ``tools/generate_client_compat_fixtures.py`` writes and parses each body through
``hassette_client.parse_response``, the public entry point every client method parses through, as
the type the release declares for that route. A fixture that doesn't parse, or whose type the
release's ``hassette_wire`` doesn't export, fails the check, named by its route and file.

It runs in a venv holding only the release named in the fixtures' ``release.json``
(``uv run nox -s client_compat``), so it imports nothing from this repository, and it refuses to run
against the workspace copies or a different version. Complements ``tools/check_wire_compat.py``,
which compares schemas: this catches serialization a schema doesn't show, and bugs in the release's
lenient parsing. Rationale: ``design/research/2026-10-02-hassette-client-transport/research.md``,
"Q5. Cross-version CI".
"""

import argparse
import functools
import json
import operator
import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import hassette_client
import hassette_wire
from hassette_client import ResponseValidationError, parse_response

REPO_ROOT = Path(__file__).resolve().parent.parent

RELEASE_FILE = "release.json"
"""Written by the generator next to the fixtures; names the release their types come from."""


class MissingTypeError(Exception):
    """A response type names a ``hassette_wire`` export the installed release doesn't have."""


@dataclass(frozen=True)
class Failure:
    fixture: Path
    route: str
    reason: str


def resolve_type(spec: Any) -> Any:
    """Rebuild a fixture's response type against the installed ``hassette_wire``.

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


def check_fixture(path: Path) -> Failure | None:
    fixture = json.loads(path.read_text())
    try:
        response_type = resolve_type(fixture["response_type"])
        parse_response(response_type, fixture["body"], endpoint=fixture["request"])
    except MissingTypeError as exc:
        return Failure(path, fixture["route"], f"hassette_wire {version('hassette-wire')} has no {exc}")
    except ResponseValidationError as exc:
        return Failure(path, fixture["route"], str(exc))
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
    release_file = fixtures / RELEASE_FILE
    if not release_file.exists():
        return f"No {RELEASE_FILE} in {fixtures}; the generator didn't run there."
    expected = json.loads(release_file.read_text())["version"]
    installed = version("hassette-client")
    if installed != expected:
        return f"The fixtures are typed by hassette-client {expected}, but {installed} is installed."
    return None


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description="Parse HEAD response fixtures with the installed hassette-client.")
    parser.add_argument("fixtures", type=Path, help="Directory the generator wrote the fixtures to.")
    args = parser.parse_args(argv)

    problem = setup_problem(args.fixtures, repo_root)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    paths = sorted(path for path in args.fixtures.glob("*.json") if path.name != RELEASE_FILE)
    if not paths:
        print(f"No fixtures in {args.fixtures}; the generator wrote nothing.", file=sys.stderr)
        return 1

    failures = [failure for path in paths if (failure := check_fixture(path))]
    release = f"hassette-client {version('hassette-client')}"
    if failures:
        print(f"{release} can't parse {len(failures)} of {len(paths)} HEAD responses:", file=sys.stderr)
        for failure in failures:
            print(f"\n{failure.route} ({failure.fixture.name}):\n  {failure.reason}", file=sys.stderr)
        return 1
    print(f"{release} parsed all {len(paths)} HEAD responses.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
