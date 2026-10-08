"""Tests for tools/check_client_floor.py's choice of which ``openapi.json`` is the minimum server's.

Real git plumbing, since tag lookup and ``git show`` are the thing under test.
"""

import json
import subprocess
from pathlib import Path

import pytest
from check_client_floor import FloorSpecError, main, resolve_floor_openapi
from hassette_client import MIN_SERVER_VERSION

from tests.unit.tools.conftest import GitRepo


def write_spec(repo: GitRepo, marker: str) -> None:
    repo.write("frontend/openapi.json", json.dumps({"openapi": "3.1.0", "info": {"title": marker}}))


def spec_title(path: Path) -> str:
    return json.loads(path.read_text())["info"]["title"]


def test_tagged_minimum_reads_the_spec_at_that_tag(git_repo: GitRepo, tmp_path: Path) -> None:
    write_spec(git_repo, "at-1.2.0")
    git_repo.commit("release")
    subprocess.run(["git", "tag", "v1.2.0"], cwd=git_repo.root, check=True, capture_output=True)
    write_spec(git_repo, "head")
    git_repo.commit("later")
    dest = tmp_path / "out"
    dest.mkdir()

    spec = resolve_floor_openapi(git_repo.root, "1.2.0", "1.3.0", dest)

    assert spec_title(spec) == "at-1.2.0"


def test_minimum_equal_to_the_release_being_cut_reads_heads_spec(git_repo: GitRepo, tmp_path: Path) -> None:
    """release-please creates the tag only after its PR merges, so HEAD's spec is that release's API."""
    write_spec(git_repo, "head")
    git_repo.commit("release PR")

    spec = resolve_floor_openapi(git_repo.root, "1.3.0", "1.3.0", tmp_path)

    assert spec == git_repo.root / "frontend" / "openapi.json"


def test_untagged_minimum_that_isnt_the_release_fails(git_repo: GitRepo, tmp_path: Path) -> None:
    write_spec(git_repo, "head")
    git_repo.commit("release PR")

    with pytest.raises(FloorSpecError, match=r"tag v1\.2\.9 doesn't exist"):
        resolve_floor_openapi(git_repo.root, "1.2.9", "1.3.0", tmp_path)


def test_main_fails_without_running_the_tests_when_the_minimum_has_no_spec(
    git_repo: GitRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    write_spec(git_repo, "head")
    git_repo.write("pyproject.toml", '[project]\nname = "hassette"\nversion = "999.0.0"\n')
    git_repo.commit("release PR for a version that isn't the minimum")

    assert main(git_repo.root) == 1
    assert f"tag v{MIN_SERVER_VERSION} doesn't exist" in capsys.readouterr().err
