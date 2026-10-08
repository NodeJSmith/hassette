"""Unit tests for hassette_codegen.ha_source — HA source resolution and domain discovery."""

import sys
from pathlib import Path
from textwrap import dedent

import pytest

from hassette_codegen.extractors.properties import extract_properties
from hassette_codegen.ha_source import (
    _parse_required_python_ver,
    check_python_version,
    discover_domains,
)

from .conftest import HA_CORE as _HA_CORE
from .conftest import HAS_HA_CORE as _HAS_HA_CORE

_ENTITY_MODULE_SOURCE = """\
from homeassistant.helpers.entity import Entity

CACHED_PROPERTIES_WITH_ATTR_ = {"items"}


class WidgetEntity(Entity, cached_properties=CACHED_PROPERTIES_WITH_ATTR_):
    _attr_items: list[str] | None = None
"""


class TestParsePythonVer:
    def test_parses_tuple_from_const(self) -> None:
        result = _parse_required_python_ver(_HA_CORE / "homeassistant" / "const.py")
        assert result is not None
        assert len(result) == 3
        assert all(isinstance(v, int) for v in result)
        assert result >= (3, 14, 0)

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        fake = tmp_path / "const.py"
        fake.write_text("X = 1\n")
        assert _parse_required_python_ver(fake) is None


class TestCheckPythonVersion:
    def test_raises_on_old_python(self, tmp_path: Path) -> None:
        const = tmp_path / "homeassistant" / "const.py"
        const.parent.mkdir(parents=True)
        const.write_text("from typing import Final\nREQUIRED_PYTHON_VER: Final[tuple[int, int, int]] = (99, 0, 0)\n")
        with pytest.raises(SystemExit, match="requires Python 99.0.0"):
            check_python_version(tmp_path)

    def test_passes_on_current_python(self, tmp_path: Path) -> None:
        v = sys.version_info
        const = tmp_path / "homeassistant" / "const.py"
        const.parent.mkdir(parents=True)
        const.write_text(
            f"from typing import Final\nREQUIRED_PYTHON_VER: Final[tuple[int, int, int]] = ({v.major}, {v.minor}, 0)\n"
        )
        check_python_version(tmp_path)


def _write_domain(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a synthetic HA core tree with one ``widget`` component built from ``files``."""
    comp = tmp_path / "homeassistant" / "components" / "widget"
    comp.mkdir(parents=True)
    for name, source in files.items():
        (comp / name).write_text(dedent(source))
    return tmp_path


class TestDiscoverEntityModule:
    def test_entity_class_in_init_py(self, tmp_path: Path) -> None:
        core = _write_domain(tmp_path, {"__init__.py": _ENTITY_MODULE_SOURCE})
        (widget,) = discover_domains(core)
        assert widget.entity_module.name == "__init__.py"

    def test_entity_class_in_entity_py(self, tmp_path: Path) -> None:
        core = _write_domain(
            tmp_path,
            {"__init__.py": "from .entity import WidgetEntity\n", "entity.py": _ENTITY_MODULE_SOURCE},
        )
        (widget,) = discover_domains(core)
        assert widget.name == "widget"
        assert widget.entity_module.name == "entity.py"
        assert [p.name for p in extract_properties(widget.entity_module)] == ["items"]

    def test_component_without_entity_class_is_skipped(self, tmp_path: Path) -> None:
        core = _write_domain(tmp_path, {"__init__.py": "X = 1\n", "entity.py": "Y = 2\n"})
        assert discover_domains(core) == []


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestDiscoverDomains:
    def test_finds_light(self) -> None:
        domains = discover_domains(_HA_CORE)
        names = {d.name for d in domains}
        assert "light" in names

    def test_finds_fan(self) -> None:
        domains = discover_domains(_HA_CORE)
        names = {d.name for d in domains}
        assert "fan" in names

    def test_finds_sensor(self) -> None:
        domains = discover_domains(_HA_CORE)
        names = {d.name for d in domains}
        assert "sensor" in names

    def test_finds_todo_with_entity_class_in_entity_py(self) -> None:
        domains = discover_domains(_HA_CORE)
        todo = next(d for d in domains if d.name == "todo")
        assert todo.entity_module.name == "entity.py"

    def test_discovers_expected_count(self) -> None:
        domains = discover_domains(_HA_CORE)
        assert len(domains) >= 25

    def test_light_has_services_yaml(self) -> None:
        domains = discover_domains(_HA_CORE)
        light = next(d for d in domains if d.name == "light")
        assert light.has_services_yaml is True

    def test_sensor_has_no_services_yaml(self) -> None:
        domains = discover_domains(_HA_CORE)
        sensor = next(d for d in domains if d.name == "sensor")
        assert sensor.has_services_yaml is False

    def test_light_has_const_py(self) -> None:
        domains = discover_domains(_HA_CORE)
        light = next(d for d in domains if d.name == "light")
        assert light.has_const_py is True
