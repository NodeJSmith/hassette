"""Unit tests for constants extraction and __init__.py generation."""

import ast
import os
import py_compile
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.extractors.constants import (
    ExtractedConstantSet,
    extract_numeric_state_expected_source,
    extract_sensor_constants,
)
from hassette_codegen.generators.constants import generate_sensor_constants
from hassette_codegen.generators.exports import generate_init_py
from hassette_codegen.pipeline import _check_predicate_freshness

_HA_CORE = Path(os.environ.get("HA_CORE_PATH", "~/source/core")).expanduser()
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


class TestConstantsEscaping:
    """Sensor constant values come from HA's StrEnum members and land inside a ``Literal[...]``.

    Hand-quoting made a value containing a quote split into two literals — valid syntax, wrong
    content — so the assertions count literals rather than compare strings.
    """

    @staticmethod
    def _literals(output: str) -> list[str]:
        module = ast.parse(output)
        return [
            node.value for node in ast.walk(module) if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]

    def test_quote_in_value_stays_one_literal(self) -> None:
        hostile = 'closes", "and reopens'
        output = generate_sensor_constants([ExtractedConstantSet(name="DEVICE_CLASS", values=[hostile])])

        assert self._literals(output) == [hostile]

    def test_backslash_in_value_is_not_read_as_an_escape(self) -> None:
        output = generate_sensor_constants([ExtractedConstantSet(name="DEVICE_CLASS", values=["C:\\new"])])

        assert self._literals(output) == ["C:\\new"]

    def test_hostile_values_still_compile(self) -> None:
        values = ['a", "b', "trailing \\", 'quote " here', "newline\nhere"]
        output = generate_sensor_constants([ExtractedConstantSet(name="DEVICE_CLASS", values=values)])

        assert self._literals(output) == values


class TestNonNumericDeviceClasses:
    """``NON_NUMERIC_DEVICE_CLASSES`` is generated from HA core as a runtime set, not

    hand-maintained, and does not disturb the existing ``Literal`` rendering for the other sets.
    """

    @pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
    def test_extracted_as_runtime_set_with_correct_members(self) -> None:
        results = extract_sensor_constants(_HA_CORE)
        nn = next((r for r in results if r.name == "NON_NUMERIC_DEVICE_CLASSES"), None)
        assert nn is not None
        assert nn.kind == "runtime_set"
        assert set(nn.values) == {"date", "enum", "timestamp", "uptime"}

    def test_renders_as_runtime_frozenset(self) -> None:
        output = generate_sensor_constants(
            [ExtractedConstantSet(name="NON_NUMERIC_DEVICE_CLASSES", values=["date", "enum"], kind="runtime_set")]
        )
        assert "NON_NUMERIC_DEVICE_CLASSES: frozenset[str] = frozenset(" in output
        assert "Literal[" not in output

    def test_generated_runtime_set_compiles_with_correct_values(self) -> None:
        output = generate_sensor_constants(
            [ExtractedConstantSet(name="NON_NUMERIC_DEVICE_CLASSES", values=["date", "enum"], kind="runtime_set")]
        )
        namespace: dict[str, object] = {}
        exec(compile(output, "<generated>", "exec"), namespace)  # noqa: S102
        assert namespace["NON_NUMERIC_DEVICE_CLASSES"] == frozenset({"date", "enum"})

    def test_literal_rendering_unaffected_by_runtime_set_support(self) -> None:
        """Adding runtime-set rendering must not change how ``Literal`` constants render."""
        output = generate_sensor_constants([ExtractedConstantSet(name="DEVICE_CLASS", values=["temperature"])])
        assert output == 'from typing import Literal\n\nDEVICE_CLASS = Literal[\n    "temperature",\n]\n'


class TestPredicateFreshnessDriftGuard:
    """A mismatch between the committed snapshot and HA's current

    ``_numeric_state_expected`` source fails the freshness check; a matching snapshot passes.
    """

    def test_extraction_failure_fails_freshness(self, tmp_path: Path) -> None:
        # No homeassistant/ tree under tmp_path, so extraction itself returns None — that must
        # also fail the check rather than being silently skipped.
        assert _check_predicate_freshness(tmp_path, tmp_path / "snapshot.txt") is False

    @pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
    def test_missing_snapshot_file_fails(self, tmp_path: Path) -> None:
        assert _check_predicate_freshness(_HA_CORE, tmp_path / "does-not-exist.txt") is False

    @pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
    def test_matching_snapshot_passes(self, tmp_path: Path) -> None:
        current = extract_numeric_state_expected_source(_HA_CORE)
        assert current is not None
        snapshot = tmp_path / "numeric_state_expected.py.txt"
        snapshot.write_text(current + "\n", encoding="utf-8")

        assert _check_predicate_freshness(_HA_CORE, snapshot) is True

    @pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
    def test_modified_snapshot_fails_then_restored_snapshot_passes(self, tmp_path: Path) -> None:
        current = extract_numeric_state_expected_source(_HA_CORE)
        assert current is not None
        snapshot = tmp_path / "numeric_state_expected.py.txt"
        snapshot.write_text(current + "\n", encoding="utf-8")
        assert _check_predicate_freshness(_HA_CORE, snapshot) is True

        # Deliberately modify the snapshot to simulate upstream drift.
        snapshot.write_text(current.replace("return False", "return True") + "\n", encoding="utf-8")
        assert _check_predicate_freshness(_HA_CORE, snapshot) is False

        # Restored — passes again.
        snapshot.write_text(current + "\n", encoding="utf-8")
        assert _check_predicate_freshness(_HA_CORE, snapshot) is True
