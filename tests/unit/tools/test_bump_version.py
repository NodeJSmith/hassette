import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "tools" / "release" / "bump_version.py"
_spec = importlib.util.spec_from_file_location("bump_version", SCRIPT_PATH)
assert _spec is not None
assert _spec.loader is not None
bump_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump_version)

ROOT_PYPROJECT = """[project]
name = "hassette"
version = "0.58.0"
dependencies = [
    "hassette-wire==0.58.0",  # x-release-please-version
    "hassette-client[cli]==0.58.0",  # x-release-please-version
    "pydantic>=2.0",
]

[tool.uv.sources]
hassette-wire = { workspace = true }
"""
WIRE_PYPROJECT = """[project]
name = "hassette-wire"
version = "0.58.0"  # x-release-please-version
"""
CLIENT_PYPROJECT = """[project]
name = "hassette-client"
version = "0.58.0"  # x-release-please-version
dependencies = [
    "hassette-wire==0.58.0",  # x-release-please-version
]
"""
OLD_LINE_PYPROJECT = """[project]
name = "hassette"
version = "0.40.2"
dependencies = [
    "pydantic>=2.0",
]
"""
MANIFEST = '{\n\t".": "0.58.0"\n}\n'


class LockRecorder:
    def __init__(self) -> None:
        self.roots: list[Path] = []

    def __call__(self, root: Path) -> None:
        self.roots.append(root)


def write(root: Path, rel_path: str, content: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture
def lock() -> LockRecorder:
    return LockRecorder()


@pytest.fixture
def full_tree(tmp_path: Path) -> Path:
    write(tmp_path, "pyproject.toml", ROOT_PYPROJECT)
    write(tmp_path, "wire/pyproject.toml", WIRE_PYPROJECT)
    write(tmp_path, "client/pyproject.toml", CLIENT_PYPROJECT)
    write(tmp_path, ".release-please-manifest.json", MANIFEST)
    return tmp_path


def test_full_tree_bumps_every_location_and_relocks(full_tree: Path, lock: LockRecorder) -> None:
    edited, skipped = bump_version.run("0.58.1", full_tree, lock=lock)

    assert edited == [
        "pyproject.toml",
        "wire/pyproject.toml",
        "client/pyproject.toml",
        ".release-please-manifest.json",
    ]
    assert skipped == []
    assert (full_tree / "pyproject.toml").read_text() == ROOT_PYPROJECT.replace("0.58.0", "0.58.1")
    assert (full_tree / "wire/pyproject.toml").read_text() == WIRE_PYPROJECT.replace("0.58.0", "0.58.1")
    assert (full_tree / "client/pyproject.toml").read_text() == CLIENT_PYPROJECT.replace("0.58.0", "0.58.1")
    assert (full_tree / ".release-please-manifest.json").read_text() == MANIFEST.replace("0.58.0", "0.58.1")
    assert lock.roots == [full_tree]


def test_old_line_without_workspace_members_skips_them(tmp_path: Path, lock: LockRecorder) -> None:
    write(tmp_path, "pyproject.toml", OLD_LINE_PYPROJECT)
    write(tmp_path, ".release-please-manifest.json", MANIFEST.replace("0.58.0", "0.40.2"))

    edited, skipped = bump_version.run("0.40.3", tmp_path, lock=lock)

    assert edited == ["pyproject.toml", ".release-please-manifest.json"]
    assert skipped == ["wire/pyproject.toml", "client/pyproject.toml"]
    assert (tmp_path / "pyproject.toml").read_text() == OLD_LINE_PYPROJECT.replace("0.40.2", "0.40.3")
    assert json.loads((tmp_path / ".release-please-manifest.json").read_text()) == {".": "0.40.3"}
    assert not (tmp_path / "wire").exists()
    assert not (tmp_path / "client").exists()
    assert lock.roots == [tmp_path]


def test_missing_manifest_is_skipped(tmp_path: Path, lock: LockRecorder) -> None:
    write(tmp_path, "pyproject.toml", OLD_LINE_PYPROJECT)

    _, skipped = bump_version.run("0.40.3", tmp_path, lock=lock)

    assert ".release-please-manifest.json" in skipped
    assert not (tmp_path / ".release-please-manifest.json").exists()


@pytest.mark.parametrize("version", ["v0.58.1", "0.58", "0.58.1rc1", "0.58.1.dev0", "", "latest"])
def test_malformed_version_is_rejected_before_any_edit(full_tree: Path, lock: LockRecorder, version: str) -> None:
    with pytest.raises(bump_version.BumpError, match=r"X\.Y\.Z"):
        bump_version.run(version, full_tree, lock=lock)

    assert (full_tree / "pyproject.toml").read_text() == ROOT_PYPROJECT
    assert lock.roots == []


def test_root_without_pyproject_fails(tmp_path: Path, lock: LockRecorder) -> None:
    with pytest.raises(bump_version.BumpError, match=r"no pyproject\.toml"):
        bump_version.run("0.58.1", tmp_path, lock=lock)

    assert lock.roots == []


def test_main_reports_malformed_version(full_tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert bump_version.main(["0.58", "--root", str(full_tree)]) == 1
    assert "X.Y.Z" in capsys.readouterr().err
