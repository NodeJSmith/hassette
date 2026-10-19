"""Tests for orphan detection: generator-owned files a full run no longer produces.

Each scenario generates ``fan`` and ``light`` from one synthetic HA checkout, then runs against a
second checkout where ``light`` is no longer discovered. That is the shape of the real failure:
upstream moves a domain's marker constant, discovery stops finding it, and the committed module
keeps shipping a model frozen at the last version that produced it.
"""

from pathlib import Path

import pytest

from hassette_codegen.ha_source import HASource
from hassette_codegen.manifest import load_manifest, save_manifest
from hassette_codegen.pipeline import run_pipeline

from .test_pipeline_guards import STATES, make_ha_core

ORPHAN = STATES / "light.py"


@pytest.fixture
def lost_domain(tmp_path: Path) -> tuple[HASource, Path]:
    """A repo generated with ``fan`` and ``light``, plus an HA checkout that only has ``fan``."""
    repo_root = tmp_path / "repo"
    assert run_pipeline(make_ha_core(tmp_path / "before", ["fan", "light"]), repo_root, check_mode=False) == 0
    assert (repo_root / ORPHAN).exists(), "the setup run produced nothing — the orphan tests prove nothing"
    return make_ha_core(tmp_path / "after", ["fan"]), repo_root


class TestOrphansInCheckMode:
    def test_fails_and_names_the_orphan(
        self, lost_domain: tuple[HASource, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        ha_source, repo_root = lost_domain
        capsys.readouterr()

        assert run_pipeline(ha_source, repo_root, check_mode=True) == 1

        err = capsys.readouterr().err
        assert f"Orphaned files (no longer generated): {ORPHAN}" in err
        assert "1 orphans" in err

    def test_leaves_the_tree_and_manifest_untouched(self, lost_domain: tuple[HASource, Path]) -> None:
        ha_source, repo_root = lost_domain
        before = load_manifest(repo_root)

        run_pipeline(ha_source, repo_root, check_mode=True)

        assert (repo_root / ORPHAN).exists()
        assert load_manifest(repo_root) == before

    def test_a_domain_filtered_run_does_not_report_orphans_outside_the_filter(
        self, lost_domain: tuple[HASource, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        ha_source, repo_root = lost_domain
        capsys.readouterr()

        assert run_pipeline(ha_source, repo_root, check_mode=True, domain_filter={"fan"}) == 0
        assert "orphan" not in capsys.readouterr().err.lower()


class TestOrphansInAFullRun:
    def test_fails_and_names_the_orphan(
        self, lost_domain: tuple[HASource, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        ha_source, repo_root = lost_domain
        capsys.readouterr()

        assert run_pipeline(ha_source, repo_root, check_mode=False) == 1
        assert f"Orphaned files (no longer generated): {ORPHAN}" in capsys.readouterr().err

    def test_keeps_the_orphan_on_disk_and_in_the_manifest(self, lost_domain: tuple[HASource, Path]) -> None:
        # Keeping ownership is what makes the next run fail again rather than mistaking the stale
        # module for a hand-written one.
        ha_source, repo_root = lost_domain

        run_pipeline(ha_source, repo_root, check_mode=False)

        assert (repo_root / ORPHAN).exists()
        assert ORPHAN in load_manifest(repo_root)
        assert run_pipeline(ha_source, repo_root, check_mode=True) == 1

    def test_passes_once_the_orphan_is_deleted(self, lost_domain: tuple[HASource, Path]) -> None:
        ha_source, repo_root = lost_domain
        (repo_root / ORPHAN).unlink()

        assert run_pipeline(ha_source, repo_root, check_mode=False) == 0
        assert ORPHAN not in load_manifest(repo_root)

    def test_a_domain_filtered_run_keeps_its_merge_behavior(
        self, lost_domain: tuple[HASource, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        ha_source, repo_root = lost_domain
        capsys.readouterr()

        assert run_pipeline(ha_source, repo_root, check_mode=False, domain_filter={"fan"}) == 0
        assert "orphan" not in capsys.readouterr().err.lower()
        assert ORPHAN in load_manifest(repo_root)


def test_a_manifest_entry_whose_file_is_gone_is_not_an_orphan(tmp_path: Path) -> None:
    ha_source = make_ha_core(tmp_path / "core", ["fan"])
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    save_manifest(repo_root, {ORPHAN})

    assert run_pipeline(ha_source, repo_root, check_mode=False) == 0
    assert ORPHAN not in load_manifest(repo_root)
    assert run_pipeline(ha_source, repo_root, check_mode=True) == 0
