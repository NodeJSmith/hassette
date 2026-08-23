"""Tests for the pipeline's guards on where generated output is allowed to land.

A domain name is a Home Assistant component directory name used verbatim as an output basename,
so a component called ``base`` would write straight over the hand-written
``models/states/base.py``. These cover the two gates that stop it: the reserved-name check at
discovery, and the manifest-ownership check before each write.

Every end-to-end test generates a second, ordinary domain in the same run. Without that control
a test proving "the file was not overwritten" would also pass if the pipeline never ran at all.
"""

from pathlib import Path

import pytest

from hassette_codegen import pipeline
from hassette_codegen.ha_source import DiscoveredDomain, HASource
from hassette_codegen.manifest import load_manifest, save_manifest
from hassette_codegen.pipeline import (
    RESERVED_BASENAMES,
    Rejection,
    _may_overwrite,
    _reject_unsafe_domain_names,
    run_pipeline,
)

# The smallest component that discover_domains() will pick up: the marker constant it greps for,
# plus a class inheriting from a known entity base, plus one _attr_ field to extract.
COMPONENT_SOURCE = '''"""A synthetic Home Assistant component."""

CACHED_PROPERTIES_WITH_ATTR_ = {"percentage"}


class DemoEntity(Entity):
    _attr_percentage: int | None = None
'''

HAND_WRITTEN = '"""Hand-written, not generated."""\n\nSENTINEL = "do not overwrite"\n'

# A services.yaml key becomes a method name verbatim, so a key that is not an identifier is what
# makes generate_entity_wrapper refuse the whole wrapper.
UNSAFE_SERVICE_YAML = "turn on:\n  fields: {}\n"

STATES = Path("src/hassette/models/states")


def make_ha_core(root: Path, domain_names: list[str], services: dict[str, str] | None = None) -> HASource:
    """Build the minimal HA core layout the pipeline walks.

    ``services`` maps a domain name to the body of its ``services.yaml``, for the domains that
    need service wrappers generated.
    """
    (root / "homeassistant").mkdir(parents=True)
    (root / "homeassistant" / "const.py").write_text("REQUIRED_PYTHON_VER = (3, 11, 0)\n", encoding="utf-8")

    components = root / "homeassistant" / "components"
    components.mkdir()
    for name in domain_names:
        component = components / name
        component.mkdir()
        (component / "__init__.py").write_text(COMPONENT_SOURCE, encoding="utf-8")
        if services and name in services:
            (component / "services.yaml").write_text(services[name], encoding="utf-8")

    return HASource(path=root, version="test")


def make_domains(*names: str) -> list[DiscoveredDomain]:
    return [DiscoveredDomain(name=name, path=Path(name), has_services_yaml=False, has_const_py=False) for name in names]


class TestRejectUnsafeDomainNames:
    def test_keeps_ordinary_domains(self) -> None:
        safe, rejected = _reject_unsafe_domain_names(make_domains("fan", "light"))

        assert [d.name for d in safe] == ["fan", "light"]
        assert rejected == []

    @pytest.mark.parametrize("name", ["base", "catalog", "input", "simple", "__init__"])
    def test_drops_names_reserved_for_hand_written_modules(self, name: str) -> None:
        expected = (make_domains("fan"), [Rejection(name, "domain name")])
        assert _reject_unsafe_domain_names(make_domains(name, "fan")) == expected

    @pytest.mark.parametrize("name", ["not a domain", "fan-2", "2fan", "fan.evil", "class"])
    def test_drops_names_that_are_not_importable_modules(self, name: str) -> None:
        expected = (make_domains("fan"), [Rejection(name, "domain name")])
        assert _reject_unsafe_domain_names(make_domains(name, "fan")) == expected

    def test_reserves_every_hand_written_module_that_is_not_a_domain(self) -> None:
        # These four have no Home Assistant component of the same name, so nothing but this list
        # keeps a future one from landing on them before a manifest exists.
        hand_written = {"base", "catalog", "input", "simple"}

        assert hand_written <= RESERVED_BASENAMES

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

    def test_a_failed_write_does_not_claim_manifest_ownership(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The manifest is what _may_overwrite consults on the next run, so recording a path whose
        # write failed would hand the generator ownership of a file it never produced.
        ha_source = make_ha_core(tmp_path / "core", ["fan"])
        repo_root = tmp_path / "repo"
        real_atomic_write = pipeline.atomic_write

        def fail_package_inits(out_path: Path, content: str) -> bool:
            return False if out_path.name == "__init__.py" else real_atomic_write(out_path, content)

        monkeypatch.setattr(pipeline, "atomic_write", fail_package_inits)
        run_pipeline(ha_source, repo_root, check_mode=False)

        manifest = load_manifest(repo_root)
        assert Path(STATES / "fan.py") in manifest, "the run produced nothing — guard proves nothing"
        assert not [path for path in manifest if path.name == "__init__.py"]


class TestCheckModeReportsRejections:
    """--check answers "is the committed tree current against upstream?".

    A domain the pipeline refuses to touch leaves whatever is committed for it unexamined, so
    check mode has to fail on it. Every test here generates first so the tree is genuinely current
    — the exit code then turns on the rejection alone, not on drift.
    """

    # dup-ignore-start: each test needs its own generate-then-check lifecycle
    def test_a_clean_tree_passes(self, tmp_path: Path) -> None:
        # The control: without a rejection the same setup exits 0, so the failures below are not
        # just "check mode always fails on a freshly generated tree".
        ha_source = make_ha_core(tmp_path / "core", ["fan"])
        repo_root = tmp_path / "repo"
        run_pipeline(ha_source, repo_root, check_mode=False)

        assert run_pipeline(ha_source, repo_root, check_mode=True) == 0

    def test_fails_when_a_domain_name_is_rejected(self, tmp_path: Path) -> None:
        ha_source = make_ha_core(tmp_path / "core", ["base", "fan"])
        repo_root = tmp_path / "repo"
        run_pipeline(ha_source, repo_root, check_mode=False)

        assert run_pipeline(ha_source, repo_root, check_mode=True) == 1

    def test_names_the_rejected_domain(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        ha_source = make_ha_core(tmp_path / "core", ["base", "fan"])
        repo_root = tmp_path / "repo"
        run_pipeline(ha_source, repo_root, check_mode=False)
        capsys.readouterr()  # drop the write run's output so only the check run is asserted on

        run_pipeline(ha_source, repo_root, check_mode=True)

        assert "Rejected: base (domain name)" in capsys.readouterr().err

    def test_fails_when_an_entity_wrapper_is_rejected(self, tmp_path: Path) -> None:
        ha_source = make_ha_core(tmp_path / "core", ["fan"], services={"fan": UNSAFE_SERVICE_YAML})
        repo_root = tmp_path / "repo"
        run_pipeline(ha_source, repo_root, check_mode=False)

        # The state model generated fine; only the wrapper was refused, and that alone must fail.
        assert (repo_root / STATES / "fan.py").exists()
        assert run_pipeline(ha_source, repo_root, check_mode=True) == 1

    def test_ignores_a_rejection_outside_the_requested_filter(self, tmp_path: Path) -> None:
        # --domain fan asks about fan. An unrelated bad name upstream is not that run's answer.
        ha_source = make_ha_core(tmp_path / "core", ["base", "fan"])
        repo_root = tmp_path / "repo"
        run_pipeline(ha_source, repo_root, check_mode=False)

        assert run_pipeline(ha_source, repo_root, check_mode=True, domain_filter={"fan"}) == 0

    # dup-ignore-end
