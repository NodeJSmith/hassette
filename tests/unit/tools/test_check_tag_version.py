import importlib.util
import subprocess
from pathlib import Path

import pytest
from packaging.version import Version

from tests.unit.tools.conftest import GitRepo

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "tools" / "release" / "check_tag_version.py"
_spec = importlib.util.spec_from_file_location("check_tag_version", SCRIPT_PATH)
assert _spec is not None
assert _spec.loader is not None
check_tag_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_tag_version)

TAGS = ["v0.55.0", "v0.55.1", "v0.56.0", "v0.57.0rc1", "v0.57.0.dev2", "not-a-version"]


def test_older_line_patch_is_not_stable_release() -> None:
    c = check_tag_version.classify("v0.55.2", [*TAGS, "v0.55.2"])
    assert c.version == Version("0.55.2")
    assert c.is_stable_release is False


def test_highest_stable_tag_is_stable_release() -> None:
    c = check_tag_version.classify("v0.56.1", [*TAGS, "v0.56.1"])
    assert c.is_stable_release is True


def test_highest_stable_ignores_higher_prereleases() -> None:
    assert check_tag_version.classify("v0.56.0", TAGS).is_stable_release is True


def test_stable_with_no_existing_tags_is_stable_release() -> None:
    assert check_tag_version.classify("v1.0.0", []).is_stable_release is True


@pytest.mark.parametrize("ref_name", ["v0.58.0rc1", "v0.58.0.dev1", "v0.58.0a2"])
def test_prereleases_are_never_stable(ref_name: str) -> None:
    assert check_tag_version.classify(ref_name, TAGS).is_stable_release is False


def test_list_version_tags_reads_only_v_tags(git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    git_repo.write("a.txt", "a")
    git_repo.commit("init")
    for tag in ("v0.55.0", "v0.56.0", "other"):
        subprocess.run(["git", "tag", tag], cwd=git_repo.root, check=True)
    monkeypatch.chdir(git_repo.root)
    assert sorted(check_tag_version.list_version_tags()) == ["v0.55.0", "v0.56.0"]
