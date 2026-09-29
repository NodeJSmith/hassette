"""Characterization tests for tools/check_wire_compat.py.

Runs the real ``oasdiff`` binary against minimal OpenAPI fixture pairs under
``tests/unit/tools/fixtures/wire_compat/`` — the exact per-check severities and
the reversed/forward argument order are the thing under test, and mocking
``oasdiff``'s output would just re-assert whatever the mock was told to return.
Skipped when ``oasdiff`` isn't on PATH (installed via mise locally; installed via
``go install`` in the frontend CI job — see ``.github/workflows/tests.yml``).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from check_wire_compat import DEFAULT_IGNORE_FILE, LEVELS_FORWARD, main

pytestmark = pytest.mark.skipif(shutil.which("oasdiff") is None, reason="oasdiff not found on PATH")

FIXTURES = Path(__file__).parent / "fixtures" / "wire_compat"


def _run(name: str, ignore_file: Path = DEFAULT_IGNORE_FILE) -> int:
    d = FIXTURES / name
    return main(base_openapi_path=d / "head.json", revision_openapi_path=d / "release.json", ignore_file=ignore_file)


def test_new_required_response_property_fails() -> None:
    """A response property that didn't exist in the release and is required at HEAD is blocked."""
    assert _run("new_required_property") != 0


def test_optional_response_property_became_required_fails() -> None:
    """A response property that was optional in the release and is required at HEAD is blocked."""
    assert _run("optional_became_required") != 0


def test_removed_response_property_fails() -> None:
    """A required response property present in the release and removed at HEAD is blocked."""
    assert _run("removed_response_property") != 0


def test_removed_endpoint_fails() -> None:
    """An endpoint present in the release and removed at HEAD is blocked."""
    assert _run("removed_endpoint") != 0


def test_new_optional_response_property_passes() -> None:
    """A new, non-required response property at HEAD is not blocked."""
    assert _run("new_optional_property") == 0


def test_new_endpoint_passes() -> None:
    """A brand-new endpoint at HEAD is not blocked."""
    assert _run("new_endpoint") == 0


def test_new_enum_value_passes() -> None:
    """A new allowed enum value on an existing response property at HEAD is not blocked.

    Enum/Literal value growth is the old-client/new-server hazard hassette-client's lenient
    parsing owns, not this check — see ``tools/wire_compat_levels_forward.txt``.
    """
    assert _run("new_enum_value") == 0


def test_removed_response_property_passes_when_listed_in_ignore_file(tmp_path: Path) -> None:
    """A deliberate break passes once its exact oasdiff finding is listed in the ignore file.

    The ignore line is generated from oasdiff's own text output (rather than hand-typed) so the
    test proves the documented ``METHOD /path <change description>`` format actually matches what
    ``--err-ignore`` expects, not just what the design doc claims it expects.
    """
    d = FIXTURES / "ignored_removed_property"
    # This same fixture pair fails without an ignore entry — the forward run is where the
    # removed-property finding surfaces (see test_removed_response_property_fails).
    assert main(base_openapi_path=d / "head.json", revision_openapi_path=d / "release.json") != 0

    result = subprocess.run(
        [
            "oasdiff",
            "breaking",
            str(d / "release.json"),
            str(d / "head.json"),
            "--format",
            "text",
            "--fail-on",
            "ERR",
            "--severity-levels",
            str(LEVELS_FORWARD),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    match = re.search(r"in API (\S+ \S+)\n\s*(.+)", result.stdout)
    assert match, f"could not parse an oasdiff finding out of:\n{result.stdout}"
    method_and_path, description = match.group(1), match.group(2).strip()
    ignore_file = tmp_path / "wire_compat_ignore.txt"
    ignore_file.write_text(f"{method_and_path} {description}\n")

    exit_code = main(
        base_openapi_path=d / "head.json", revision_openapi_path=d / "release.json", ignore_file=ignore_file
    )
    assert exit_code == 0


def test_missing_release_tag_fails_with_a_named_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """When no `v*` tag exists, the check fails loudly instead of skipping."""
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "openapi.json").write_text("{}")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)

    exit_code = main(repo_root=tmp_path)

    assert exit_code != 0
    assert "v*" in capsys.readouterr().err
