"""The e2e SPA staleness check (tools/frontend/spa_build.py)."""

import os
from pathlib import Path

import pytest
from spa_build import spa_build_steps

T0 = 1_700_000_000.0


def touch(path: Path, mtime: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def frontend(tmp_path: Path) -> Path:
    """An installed frontend whose sources and lockfile predate everything else."""
    root = tmp_path / "frontend"
    for name in ("package.json", "package-lock.json", "index.html", "vite.config.ts", "src/main.tsx"):
        touch(root / name, T0)
    touch(root / "node_modules" / ".package-lock.json", T0 + 10)
    return root


def run_steps(frontend: Path, spa_index: Path) -> list[str]:
    return [step[1] for step in spa_build_steps(frontend, spa_index)]


def test_fresh_build_needs_nothing(frontend: Path, tmp_path: Path) -> None:
    index = touch(tmp_path / "spa" / "index.html", T0 + 20)
    assert run_steps(frontend, index) == []


def test_missing_build(frontend: Path, tmp_path: Path) -> None:
    assert run_steps(frontend, tmp_path / "spa" / "index.html") == ["run"]


@pytest.mark.parametrize("changed", ["src/pages/new.tsx", "public/logo.png", "index.html", "vite.config.ts"])
def test_source_newer_than_build(frontend: Path, tmp_path: Path, changed: str) -> None:
    index = touch(tmp_path / "spa" / "index.html", T0 + 20)
    touch(frontend / changed, T0 + 30)
    assert run_steps(frontend, index) == ["run"]


def test_any_top_level_file_is_a_build_input(frontend: Path, tmp_path: Path) -> None:
    spa_index = touch(tmp_path / "spa" / "index.html", T0 + 20)
    touch(frontend / "hassette-version.ts", T0 + 30)
    assert run_steps(frontend, spa_index) == ["run"]


def test_missing_node_modules_installs_then_builds(frontend: Path, tmp_path: Path) -> None:
    (frontend / "node_modules" / ".package-lock.json").unlink()
    assert run_steps(frontend, tmp_path / "spa" / "index.html") == ["ci", "run"]


def test_lockfile_newer_than_install(frontend: Path, tmp_path: Path) -> None:
    index = touch(tmp_path / "spa" / "index.html", T0 + 40)
    touch(frontend / "package-lock.json", T0 + 30)
    assert run_steps(frontend, index) == ["ci"]
