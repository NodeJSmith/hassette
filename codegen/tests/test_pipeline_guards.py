"""Tests for the pipeline's guards on where generated output is allowed to land.

A domain name is a Home Assistant component directory name used verbatim as an output basename,
so a component called ``base`` would write straight over the hand-written
``models/states/base.py``. These cover the two gates that stop it: the reserved-name check at
discovery, and the manifest-ownership check before each write.

Every end-to-end test generates a second, ordinary domain in the same run. Without that control
a test proving "the file was not overwritten" would also pass if the pipeline never ran at all.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.ha_source import DiscoveredDomain, HASource
from hassette_codegen.manifest import load_manifest, save_manifest
from hassette_codegen.pipeline import _may_overwrite, _reject_unsafe_domain_names, run_pipeline

# The smallest component that discover_domains() will pick up: the marker constant it greps for,
# plus a class inheriting from a known entity base, plus one _attr_ field to extract.
COMPONENT_SOURCE = '''"""A synthetic Home Assistant component."""

CACHED_PROPERTIES_WITH_ATTR_ = {"percentage"}


class DemoEntity(Entity):
    _attr_percentage: int | None = None
'''

HAND_WRITTEN = '"""Hand-written, not generated."""\n\nSENTINEL = "do not overwrite"\n'

STATES = Path("src/hassette/models/states")


def make_ha_core(root: Path, domain_names: list[str]) -> HASource:
    """Build the minimal HA core layout the pipeline walks."""
    (root / "homeassistant").mkdir(parents=True)
    (root / "homeassistant" / "const.py").write_text("REQUIRED_PYTHON_VER = (3, 11, 0)\n", encoding="utf-8")

    components = root / "homeassistant" / "components"
    components.mkdir()
    for name in domain_names:
        component = components / name
        component.mkdir()
        (component / "__init__.py").write_text(COMPONENT_SOURCE, encoding="utf-8")

    return HASource(path=root, version="test")


def make_domains(*names: str) -> list[DiscoveredDomain]:
    return [DiscoveredDomain(name=name, path=Path(name), has_services_yaml=False, has_const_py=False) for name in names]


class TestRejectUnsafeDomainNames:
    def test_keeps_ordinary_domains(self) -> None:
        assert [d.name for d in _reject_unsafe_domain_names(make_domains("fan", "light"))] == ["fan", "light"]

    @pytest.mark.parametrize("name", ["base", "catalog", "__init__"])
    def test_drops_names_reserved_for_hand_written_modules(self, name: str) -> None:
        assert _reject_unsafe_domain_names(make_domains(name, "fan")) == make_domains("fan")

    @pytest.mark.parametrize("name", ["not a domain", "fan-2", "2fan", "fan.evil", "class"])
    def test_drops_names_that_are_not_importable_modules(self, name: str) -> None:
        assert _reject_unsafe_domain_names(make_domains(name, "fan")) == make_domains("fan")

    def test_explains_each_rejection(self, capsys: pytest.CaptureFixture[str]) -> None:
        _reject_unsafe_domain_names(make_domains("base", "fan-2"))
        err = capsys.readouterr().err

        assert "reserved for hand-written files" in err
        assert "not a usable Python identifier" in err


class TestMayOverwrite:
    def test_allows_a_file_that_does_not_exist_yet(self, tmp_path: Path) -> None:
        assert _may_overwrite(tmp_path / "new.py", Path("new.py"), {Path("other.py")}, tracked=True) is True

    def test_allows_a_file_the_generator_owns(self, tmp_path: Path) -> None:
        target = tmp_path / "owned.py"
        target.write_text("stale", encoding="utf-8")

        assert _may_overwrite(target, Path("owned.py"), {Path("owned.py")}, tracked=True) is True

    def test_refuses_an_existing_file_the_generator_does_not_own(self, tmp_path: Path) -> None:
        target = tmp_path / "hand_written.py"
        target.write_text(HAND_WRITTEN, encoding="utf-8")

        assert _may_overwrite(target, Path("hand_written.py"), {Path("other.py")}, tracked=True) is False

    def test_falls_through_when_the_generator_has_never_run(self, tmp_path: Path) -> None:
        # No manifest file at all means no ownership information to consult; refusing everything
        # would make the first run a no-op.
        target = tmp_path / "existing.py"
        target.write_text("content", encoding="utf-8")

        assert _may_overwrite(target, Path("existing.py"), set(), tracked=False) is True

    def test_an_empty_manifest_owns_nothing_rather_than_everything(self, tmp_path: Path) -> None:
        # A manifest that exists but lists nothing is a recorded state, not missing information.
        target = tmp_path / "existing.py"
        target.write_text(HAND_WRITTEN, encoding="utf-8")

        assert _may_overwrite(target, Path("existing.py"), set(), tracked=True) is False


class TestPipelineWriteGuards:
    def test_reserved_domain_name_leaves_the_hand_written_file_untouched(self, tmp_path: Path) -> None:
        ha_source = make_ha_core(tmp_path / "core", ["base", "fan"])
        repo_root = tmp_path / "repo"
        hand_written = repo_root / STATES / "base.py"
        hand_written.parent.mkdir(parents=True)
        hand_written.write_text(HAND_WRITTEN, encoding="utf-8")

        run_pipeline(ha_source, repo_root, check_mode=False)

        assert hand_written.read_text(encoding="utf-8") == HAND_WRITTEN
        assert (repo_root / STATES / "fan.py").exists(), "the run produced nothing — guard proves nothing"
        assert Path(STATES / "base.py") not in load_manifest(repo_root)

    def test_unowned_collision_leaves_the_existing_file_untouched(self, tmp_path: Path) -> None:
        ha_source = make_ha_core(tmp_path / "core", ["mydomain", "fan"])
        repo_root = tmp_path / "repo"
        collision = repo_root / STATES / "mydomain.py"
        collision.parent.mkdir(parents=True)
        collision.write_text(HAND_WRITTEN, encoding="utf-8")
        save_manifest(repo_root, {Path(STATES / "somethingelse.py")})

        run_pipeline(ha_source, repo_root, check_mode=False)

        assert collision.read_text(encoding="utf-8") == HAND_WRITTEN
        assert (repo_root / STATES / "fan.py").exists(), "the run produced nothing — guard proves nothing"

    def test_owned_file_is_still_regenerated(self, tmp_path: Path) -> None:
        ha_source = make_ha_core(tmp_path / "core", ["fan"])
        repo_root = tmp_path / "repo"
        owned = repo_root / STATES / "fan.py"
        owned.parent.mkdir(parents=True)
        owned.write_text("# stale\n", encoding="utf-8")
        save_manifest(repo_root, {Path(STATES / "fan.py")})

        run_pipeline(ha_source, repo_root, check_mode=False)

        assert "class FanState" in owned.read_text(encoding="utf-8")

    def test_new_domain_generates_even_though_the_manifest_predates_it(self, tmp_path: Path) -> None:
        ha_source = make_ha_core(tmp_path / "core", ["newdomain"])
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        save_manifest(repo_root, {Path(STATES / "fan.py")})

        run_pipeline(ha_source, repo_root, check_mode=False)

        assert (repo_root / STATES / "newdomain.py").exists()
