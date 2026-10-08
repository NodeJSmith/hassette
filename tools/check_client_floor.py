#!/usr/bin/env -S uv run
"""Release-PR check: every request hassette-client sends exists on its ``MIN_SERVER_VERSION`` server.

Runs ``client/tests/test_openapi_coverage.py`` with ``HASSETTE_CLIENT_OPENAPI`` pointing at
``frontend/openapi.json`` as it was at tag ``v{MIN_SERVER_VERSION}``, so only the request checks run
(route, method, query parameter). A release whose client calls newer server API fails here until
``MIN_SERVER_VERSION`` in ``client/src/hassette_client/version.py`` is raised.

It runs only on release-please PRs (``.github/workflows/tests.yml``), the one place the version being
released is known. When ``MIN_SERVER_VERSION`` is that version, its tag doesn't exist yet
(release-please creates it after the PR merges), so HEAD's ``openapi.json``, that release's API, stands
in. Any other missing tag fails, so a typo in the minimum is caught.

See ``design/specs/127-hassette-client-transport/design.md`` D20.
"""

import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest
from check_wire_compat import GIT_TIMEOUT_SECONDS, OPENAPI_RELATIVE_PATH, REPO_ROOT, extract_tagged_openapi
from hassette_client import MIN_SERVER_VERSION

OPENAPI_ENV_VAR = "HASSETTE_CLIENT_OPENAPI"
"""Read by ``client/tests/test_openapi_coverage.py``."""

COVERAGE_TEST = "tests/test_openapi_coverage.py"
"""Relative to ``client/``, where the client's pytest configuration lives."""


class FloorSpecError(Exception):
    """The minimum version's ``openapi.json`` can't be found."""


def resolve_floor_openapi(repo_root: Path, min_version: str, releasing_version: str, dest_dir: Path) -> Path:
    """Return the ``openapi.json`` of the server at ``min_version``.

    Raises:
        FloorSpecError: Tag ``v{min_version}`` doesn't exist and ``min_version`` isn't the version
            being released.
    """
    tag = f"v{min_version}"
    if tag_exists(repo_root, tag):
        return extract_tagged_openapi(repo_root, tag, dest_dir)
    if min_version == releasing_version:
        return repo_root / OPENAPI_RELATIVE_PATH
    raise FloorSpecError(
        f"MIN_SERVER_VERSION is {min_version}, but tag {tag} doesn't exist and {min_version} isn't the version "
        f"being released ({releasing_version}). Set it to an existing release, or to {releasing_version}."
    )


def tag_exists(repo_root: Path, tag: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--quiet", "--verify", f"refs/tags/{tag}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    return result.returncode == 0


def release_version(repo_root: Path) -> str:
    """The root package's version: on a release-please PR, the version being released."""
    return tomllib.loads((repo_root / "pyproject.toml").read_text())["project"]["version"]


def main(repo_root: Path = REPO_ROOT) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            spec = resolve_floor_openapi(repo_root, MIN_SERVER_VERSION, release_version(repo_root), Path(tmp))
        except (FloorSpecError, RuntimeError) as exc:
            # RuntimeError: extract_tagged_openapi's git show failed.
            print(exc, file=sys.stderr)
            return 1
        print(
            f"Checking hassette-client's requests against {spec} (MIN_SERVER_VERSION {MIN_SERVER_VERSION})", flush=True
        )
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", COVERAGE_TEST],
            cwd=repo_root / "client",
            env={**os.environ, OPENAPI_ENV_VAR: str(spec)},
            check=False,
        )
    if result.returncode == pytest.ExitCode.TESTS_FAILED:
        print(
            f"hassette-client sends requests a {MIN_SERVER_VERSION} server doesn't serve. Raise MIN_SERVER_VERSION "
            "in client/src/hassette_client/version.py to the oldest release that has them, usually the one this "
            "PR releases.",
            file=sys.stderr,
        )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
