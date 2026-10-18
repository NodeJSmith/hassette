"""Tests for the entity-domain coverage check."""

import json
from pathlib import Path

import pytest

from hassette_codegen.coverage import (
    CoverageReport,
    StaleEntry,
    find_coverage_gaps,
    load_allowlist,
    report_coverage,
)
from hassette_codegen.overrides import DomainOverride

from .conftest import HA_CORE, HAS_HA_CORE

ENTITY_COMPONENT_INIT = "from homeassistant.helpers.entity_component import EntityComponent\n"
CACHED_ENTITY_MODULE = (
    "CACHED_PROPERTIES_WITH_ATTR_ = {'foo'}\n"
    "class WidgetEntity(Entity, cached_properties=CACHED_PROPERTIES_WITH_ATTR_):\n"
    "    pass\n"
)


def add_component(
    ha_core: Path, name: str, *, integration_type: str | None = "entity", init: str = ENTITY_COMPONENT_INIT
) -> Path:
    component = ha_core / "homeassistant" / "components" / name
    component.mkdir(parents=True)
    manifest: dict[str, str] = {"domain": name}
    if integration_type is not None:
        manifest["integration_type"] = integration_type
    (component / "manifest.json").write_text(json.dumps(manifest))
    (component / "__init__.py").write_text(init)
    return component


@pytest.fixture
def ha_core(tmp_path: Path) -> Path:
    root = tmp_path / "core"
    (root / "homeassistant" / "components").mkdir(parents=True)
    return root


@pytest.fixture
def states_dir(tmp_path: Path) -> Path:
    states = tmp_path / "states"
    states.mkdir()
    (states / "gadget.py").write_text('class GadgetState(BaseState):\n    domain: Literal["handwritten"]\n')
    return states


def check(
    ha_core: Path,
    states_dir: Path,
    allowlist: dict[str, str] | None = None,
    overrides: dict[str, DomainOverride] | None = None,
) -> CoverageReport:
    return find_coverage_gaps(ha_core, allowlist=allowlist or {}, overrides=overrides or {}, states_dir=states_dir)


def test_unmodeled_entity_candidate_is_reported(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "widget")
    assert check(ha_core, states_dir).gaps == ("widget",)


def test_helper_without_entity_component_is_not_reported(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "template", integration_type="helper", init="from . import sensor\n")
    assert check(ha_core, states_dir).gaps == ()


def test_helper_with_entity_component_is_reported(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "schedule", integration_type="helper")
    assert check(ha_core, states_dir).gaps == ("schedule",)


def test_non_entity_integration_type_is_not_reported(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "universal", integration_type="hub")
    add_component(ha_core, "remember_the_milk", integration_type=None)
    assert check(ha_core, states_dir).gaps == ()


def test_discovered_domain_is_modeled(ha_core: Path, states_dir: Path) -> None:
    component = add_component(ha_core, "widget")
    (component / "__init__.py").write_text(ENTITY_COMPONENT_INIT + CACHED_ENTITY_MODULE)
    assert check(ha_core, states_dir).gaps == ()


def test_manual_override_domain_is_modeled(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "widget")
    overrides = {"widget": DomainOverride(domain="widget", discovery="manual")}
    assert check(ha_core, states_dir, overrides=overrides).gaps == ()


def test_non_manual_override_does_not_count_as_modeled(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "widget")
    overrides = {"widget": DomainOverride(domain="widget")}
    assert check(ha_core, states_dir, overrides=overrides).gaps == ("widget",)


def test_simple_state_domain_is_modeled(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "conversation")
    assert check(ha_core, states_dir).gaps == ()


def test_hand_written_literal_domain_is_modeled(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "handwritten")
    assert check(ha_core, states_dir).gaps == ()


def test_domain_literal_in_comment_or_docstring_is_not_modeled(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "widget")
    (states_dir / "notes.py").write_text(
        '# domain: Literal["widget"]\nclass NotesState(BaseState):\n    """domain: Literal["widget"]"""\n'
    )
    assert check(ha_core, states_dir).gaps == ("widget",)


def test_qualified_multi_value_literal_domains_are_modeled(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "widget")
    add_component(ha_core, "gizmo")
    (states_dir / "multi.py").write_text(
        "class MultiState(BaseState):\n    domain: typing.Literal['widget', \"gizmo\"]\n"
    )
    assert check(ha_core, states_dir).gaps == ()


def test_allowlisted_candidate_is_suppressed(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "widget")
    report = check(ha_core, states_dir, allowlist={"widget": "not yet"})
    assert report.gaps == ()
    assert report.stale == ()


def test_allowlisted_non_candidate_is_not_stale(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "plant", integration_type=None)
    assert check(ha_core, states_dir, allowlist={"plant": "not yet"}).stale == ()


def test_allowlist_entry_now_modeled_is_stale(ha_core: Path, states_dir: Path) -> None:
    add_component(ha_core, "handwritten")
    report = check(ha_core, states_dir, allowlist={"handwritten": "not yet"})
    assert report.stale == (StaleEntry("handwritten", "now modeled"),)


def test_allowlist_entry_with_missing_component_is_stale(ha_core: Path, states_dir: Path) -> None:
    report = check(ha_core, states_dir, allowlist={"gone": "not yet"})
    assert report.stale == (StaleEntry("gone", "component no longer exists in HA core"),)


@pytest.mark.parametrize(
    ("report", "expected_code", "expected_line"),
    [
        (CoverageReport(gaps=(), stale=()), 0, "coverage OK"),
        (CoverageReport(gaps=("widget",), stale=()), 1, "unmodeled domain: widget"),
        (CoverageReport(gaps=(), stale=(StaleEntry("gone", "why"),)), 1, "stale allowlist entry: gone (why)"),
    ],
)
def test_report_exit_code_and_output(
    report: CoverageReport, expected_code: int, expected_line: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert report_coverage(report) == expected_code
    assert capsys.readouterr().out.splitlines() == [expected_line]


def test_allowlist_entry_without_reason_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.toml"
    path.write_text("[tag]\n")
    with pytest.raises(ValueError, match="tag"):
        load_allowlist(path)


def test_seeded_allowlist_loads() -> None:
    assert set(load_allowlist()) >= {"tag", "wake_word", "alert", "plant"}


@pytest.mark.skipif(not HAS_HA_CORE, reason="requires local HA core checkout")
def test_real_ha_core_has_no_gaps_or_stale_entries() -> None:
    report = find_coverage_gaps(HA_CORE)
    assert report.gaps == ()
    assert report.stale == ()
