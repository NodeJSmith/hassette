"""Extract sensor device classes, units, and state classes from HA core."""

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedConstantSet:
    name: str
    values: list[str]


def extract_sensor_constants(ha_core_path: Path) -> list[ExtractedConstantSet]:
    """Extract device classes, units, and state classes from HA core."""
    results: list[ExtractedConstantSet] = []

    sensor_const = ha_core_path / "homeassistant" / "components" / "sensor" / "const.py"
    if sensor_const.exists():
        device_classes = _extract_strenum_members(sensor_const, "SensorDeviceClass")
        if device_classes:
            results.append(ExtractedConstantSet(name="DEVICE_CLASS", values=device_classes))

        state_classes = _extract_strenum_members(sensor_const, "SensorStateClass")
        if state_classes:
            results.append(ExtractedConstantSet(name="STATE_CLASS", values=state_classes))

    ha_const = ha_core_path / "homeassistant" / "const.py"
    if ha_const.exists():
        units = _extract_unit_enums(ha_const)
        if units:
            results.append(ExtractedConstantSet(name="UNIT_OF_MEASUREMENT", values=units))

    return results


def _extract_strenum_members(filepath: Path, class_name: str) -> list[str]:
    """Extract string values from a StrEnum class."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name != class_name:
            continue

        members: list[str] = []
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                members.append(item.value.value)
        return members
    return []


def _extract_unit_enums(ha_const: Path) -> list[str]:
    """Extract all unit values from UnitOf* enums in homeassistant/const.py."""
    source = ha_const.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(ha_const))
    except SyntaxError:
        return []

    units: list[str] = []
    seen: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not node.name.startswith("UnitOf"):
            continue

        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                val = item.value.value
                if val not in seen:
                    units.append(val)
                    seen.add(val)

    return units
