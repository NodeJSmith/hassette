"""The e2e SPA staleness check (tools/frontend/spa_build.py)."""

import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import spa_build
from filelock import FileLock
from spa_build import build_spa_if_stale, spa_build_steps

T0 = 1_700_000_000.0


def touch(path: Path, mtime: float) -> Path:
    """Create ``path`` at ``mtime``; its directory is stamped too, as adding a file does."""
    created = [p for p in path.parents if not p.exists()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    for entry in (path, path.parent, *created):
        os.utime(entry, (mtime, mtime))
    return path


@pytest.fixture
def frontend(tmp_path: Path) -> Path:
    """An installed frontend whose sources and lockfile predate everything else."""
    root = tmp_path / "frontend"
    for name in ("package.json", "package-lock.json", "index.html", "vite.config.ts", "src/main.tsx"):
        touch(root / name, T0)
    touch(root / "node_modules" / ".package-lock.json", T0 + 10)
    return root


def built_spa(tmp_path: Path, mtime: float) -> Path:
    """A servable build: ``index.html`` with its ``assets/`` directory beside it."""
    (tmp_path / "spa" / "assets").mkdir(parents=True, exist_ok=True)
    return touch(tmp_path / "spa" / "index.html", mtime)


def run_steps(frontend: Path, spa_index: Path) -> list[str]:
    return [step[1] for step in spa_build_steps(frontend, spa_index)]


def test_fresh_build_needs_nothing(frontend: Path, tmp_path: Path) -> None:
    index = built_spa(tmp_path, T0 + 20)
    assert run_steps(frontend, index) == []


def test_build_without_assets_is_stale(frontend: Path, tmp_path: Path) -> None:
    index = touch(tmp_path / "spa" / "index.html", T0 + 20)
    assert run_steps(frontend, index) == ["run"]


def test_missing_build(frontend: Path, tmp_path: Path) -> None:
    assert run_steps(frontend, tmp_path / "spa" / "index.html") == ["run"]


@pytest.mark.parametrize("changed", ["src/pages/new.tsx", "public/logo.png", "index.html", "vite.config.ts"])
def test_source_newer_than_build(frontend: Path, tmp_path: Path, changed: str) -> None:
    index = built_spa(tmp_path, T0 + 20)
    touch(frontend / changed, T0 + 30)
    assert run_steps(frontend, index) == ["run"]


def test_any_top_level_file_is_a_build_input(frontend: Path, tmp_path: Path) -> None:
    spa_index = built_spa(tmp_path, T0 + 20)
    touch(frontend / "hassette-version.ts", T0 + 30)
    assert run_steps(frontend, spa_index) == ["run"]


def test_deleted_source_makes_build_stale(frontend: Path, tmp_path: Path) -> None:
    gone = touch(frontend / "public" / "old.svg", T0)
    index = built_spa(tmp_path, T0 + 20)
    assert run_steps(frontend, index) == []
    gone.unlink()
    os.utime(frontend / "public", (T0 + 30, T0 + 30))  # removing a file stamps its directory
    assert run_steps(frontend, index) == ["run"]


def test_root_pyproject_is_a_build_input(frontend: Path, tmp_path: Path) -> None:
    spa_index = built_spa(tmp_path, T0 + 20)
    touch(tmp_path / "pyproject.toml", T0 + 30)
    assert run_steps(frontend, spa_index) == ["run"]


def test_missing_node_modules_installs_then_builds(frontend: Path, tmp_path: Path) -> None:
    (frontend / "node_modules" / ".package-lock.json").unlink()
    assert run_steps(frontend, tmp_path / "spa" / "index.html") == ["ci", "run"]


def test_lockfile_newer_than_install(frontend: Path, tmp_path: Path) -> None:
    index = built_spa(tmp_path, T0 + 40)
    touch(frontend / "package-lock.json", T0 + 30)
    assert run_steps(frontend, index) == ["ci"]


def fake_subprocess(ran: list[list[str]]) -> SimpleNamespace:
    """A stand-in for the ``subprocess`` module as seen by spa_build; records each step instead of running it."""

    def run(step: list[str], check: bool = False) -> None:
        assert check, "build steps must fail loudly"
        ran.append(step)

    return SimpleNamespace(run=run)


def test_build_runs_stale_steps(frontend: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr(spa_build, "subprocess", fake_subprocess(ran))
    steps = build_spa_if_stale(frontend, tmp_path / "spa" / "index.html", tmp_path / "build.lock", lock_timeout=5)
    assert ran == steps == [["npm", "run", "build", "--prefix", str(frontend)]]


def test_waiter_recomputes_steps_after_another_build_finishes(
    frontend: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller blocked on the lock finds the SPA fresh once it gets the lock, and runs nothing."""
    index = tmp_path / "spa" / "index.html"
    lock_path = tmp_path / "build.lock"
    ran: list[list[str]] = []
    monkeypatch.setattr(spa_build, "subprocess", fake_subprocess(ran))
    results: list[list[list[str]]] = []
    about_to_build = threading.Event()
    finished = threading.Event()

    def waiter_body() -> None:
        about_to_build.set()
        results.append(build_spa_if_stale(frontend, index, lock_path, lock_timeout=10))
        finished.set()

    holder = FileLock(lock_path)
    holder.acquire()
    waiter = threading.Thread(target=waiter_body)
    waiter.start()
    assert about_to_build.wait(timeout=5)
    assert not finished.wait(timeout=0.2), "waiter should be blocked on the held lock"

    built_spa(tmp_path, T0 + 20)  # the holder's build finishes
    holder.release()
    waiter.join(timeout=10)

    assert finished.is_set()
    assert results == [[]]
    assert ran == []
