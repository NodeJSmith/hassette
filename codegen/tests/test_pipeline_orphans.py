"""Tests for orphan detection: generator-owned files a full run no longer produces.

Each scenario generates ``fan`` and ``light`` from one synthetic HA checkout, then runs against a
second checkout where ``light`` is no longer discovered. That is the shape of the real failure:
upstream moves a domain's marker constant, discovery stops finding it, and the committed module
keeps shipping a model frozen at the last version that produced it.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from hassette_codegen.manifest import load_manifest, save_manifest
from hassette_codegen.pipeline import run_pipeline

from .test_pipeline_guards import STATES, make_ha_core

ORPHAN = STATES / "light.py"
ORPHAN_MESSAGE = f"Orphaned files (no longer generated): {ORPHAN}"

RunAfter = Callable[..., tuple[int, str]]


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A repo generated from an HA checkout that still has both ``fan`` and ``light``."""
    root = tmp_path / "repo"
    assert run_pipeline(make_ha_core(tmp_path / "before", ["fan", "light"]), root, check_mode=False) == 0
    assert (root / ORPHAN).exists(), "the setup run produced nothing — the orphan tests prove nothing"
    return root


@pytest.fixture
def run_after(tmp_path: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]) -> RunAfter:
    """Run the pipeline against an HA checkout where ``light`` is gone; return (exit code, stderr)."""
    ha_source = make_ha_core(tmp_path / "after", ["fan"])
    capsys.readouterr()  # drop the setup run's output

    def run(*, check_mode: bool, domain_filter: set[str] | None = None) -> tuple[int, str]:
        exit_code = run_pipeline(ha_source, repo_root, check_mode=check_mode, domain_filter=domain_filter)
        return exit_code, capsys.readouterr().err

    return run


class TestOrphansInCheckMode:
    def test_fails_and_names_the_orphan(self, run_after: RunAfter) -> None:
        exit_code, err = run_after(check_mode=True)

        assert exit_code == 1
        assert ORPHAN_MESSAGE in err
        assert "1 orphans" in err

    def test_leaves_the_tree_and_manifest_untouched(self, run_after: RunAfter, repo_root: Path) -> None:
        before = load_manifest(repo_root)

        run_after(check_mode=True)

        assert (repo_root / ORPHAN).exists()
        assert load_manifest(repo_root) == before

    def test_a_domain_filtered_run_does_not_report_orphans_outside_the_filter(self, run_after: RunAfter) -> None:
        exit_code, err = run_after(check_mode=True, domain_filter={"fan"})

        assert exit_code == 0
        assert "orphan" not in err.lower()


class TestOrphansInAFullRun:
    def test_fails_and_names_the_orphan(self, run_after: RunAfter) -> None:
        exit_code, err = run_after(check_mode=False)

        assert exit_code == 1
        assert ORPHAN_MESSAGE in err

    def test_keeps_the_orphan_on_disk_and_in_the_manifest(self, run_after: RunAfter, repo_root: Path) -> None:
        # Keeping ownership is what makes the next run fail again rather than mistaking the stale
        # module for a hand-written one.
        run_after(check_mode=False)

        assert (repo_root / ORPHAN).exists()
        assert ORPHAN in load_manifest(repo_root)
        assert run_after(check_mode=True)[0] == 1

    def test_passes_once_the_orphan_is_deleted(self, run_after: RunAfter, repo_root: Path) -> None:
        (repo_root / ORPHAN).unlink()

        assert run_after(check_mode=False)[0] == 0
        assert ORPHAN not in load_manifest(repo_root)

    def test_a_domain_filtered_run_keeps_its_merge_behavior(self, run_after: RunAfter, repo_root: Path) -> None:
        exit_code, err = run_after(check_mode=False, domain_filter={"fan"})

        assert exit_code == 0
        assert "orphan" not in err.lower()
        assert ORPHAN in load_manifest(repo_root)


def test_a_manifest_entry_whose_file_is_gone_is_not_an_orphan(tmp_path: Path) -> None:
    ha_source = make_ha_core(tmp_path / "core", ["fan"])
    root = tmp_path / "repo"
    root.mkdir()
    save_manifest(root, {ORPHAN})

    assert run_pipeline(ha_source, root, check_mode=False) == 0
    assert ORPHAN not in load_manifest(root)
    assert run_pipeline(ha_source, root, check_mode=True) == 0
