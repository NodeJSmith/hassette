"""Unit tests for constants extraction and __init__.py generation."""

import py_compile
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.extractors.constants import extract_sensor_constants
from hassette_codegen.generators.constants import generate_sensor_constants
from hassette_codegen.generators.exports import generate_init_py

_HA_CORE = Path("~/source/core").expanduser()
_HAS_HA_CORE = _HA_CORE.exists()
_STATES_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "hassette" / "models" / "states"


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestConstantsExtraction:
    def test_finds_device_classes(self) -> None:
        results = extract_sensor_constants(_HA_CORE)
        dc = next((r for r in results if r.name == "DEVICE_CLASS"), None)
        assert dc is not None
        assert len(dc.values) > 30
        assert "temperature" in dc.values

    def test_finds_state_classes(self) -> None:
        results = extract_sensor_constants(_HA_CORE)
        sc = next((r for r in results if r.name == "STATE_CLASS"), None)
        assert sc is not None
        assert len(sc.values) >= 3

    def test_finds_units(self) -> None:
        results = extract_sensor_constants(_HA_CORE)
        units = next((r for r in results if r.name == "UNIT_OF_MEASUREMENT"), None)
        assert units is not None
        assert len(units.values) > 100

    def test_generated_constants_compile(self) -> None:
        results = extract_sensor_constants(_HA_CORE)
        output = generate_sensor_constants(results)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(output)
            f.flush()
            py_compile.compile(f.name, doraise=True)


class TestExportsGenerator:
    def test_includes_generated_and_handwritten(self) -> None:
        output = generate_init_py(_STATES_DIR)
        assert "FanState" in output
        assert "LightState" in output
        assert "BinarySensorState" in output
        assert "InputBooleanState" in output
        assert "BaseState" in output

    def test_includes_enum_exports(self) -> None:
        output = generate_init_py(_STATES_DIR)
        assert "FanEntityFeature" in output
        assert "LightEntityFeature" in output

    def test_sorted_order(self) -> None:
        output = generate_init_py(_STATES_DIR)
        all_section = output.split("__all__ = [")[1].split("]")[0]
        names = [line.strip().strip('"').strip(",").strip('"') for line in all_section.splitlines() if line.strip()]
        assert names == sorted(names)

    def test_output_compiles(self) -> None:
        output = generate_init_py(_STATES_DIR)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(output)
            f.flush()
            py_compile.compile(f.name, doraise=True)
