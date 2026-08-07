"""Extract sensor device classes, units, and state classes from HA core."""

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedConstantSet:
    name: str
    values: list[str]
    kind: str = "literal"
    """"literal" renders as a ``Literal[...]`` type alias; "runtime_set" renders as a
    ``frozenset[str]`` runtime value. See ``generators/constants.py``."""


def extract_sensor_constants(ha_core_path: Path) -> list[ExtractedConstantSet]:
    """Extract device classes, units, and state classes from HA core."""
    results: list[ExtractedConstantSet] = []

    sensor_const = ha_core_path / "homeassistant" / "components" / "sensor" / "const.py"
    if sensor_const.exists():
        device_classes = _extract_strenum_members(sensor_const, "SensorDeviceClass")
        if device_classes:
            results.append(ExtractedConstantSet(name="DEVICE_CLASS", values=device_classes))

        non_numeric_device_classes = _extract_enum_ref_set(
            sensor_const, "NON_NUMERIC_DEVICE_CLASSES", "SensorDeviceClass"
        )
        if non_numeric_device_classes:
            results.append(
                ExtractedConstantSet(
                    name="NON_NUMERIC_DEVICE_CLASSES",
                    values=non_numeric_device_classes,
                    kind="runtime_set",
                )
            )

        state_classes = _extract_strenum_members(sensor_const, "SensorStateClass")
        if state_classes:
            results.append(ExtractedConstantSet(name="STATE_CLASS", values=state_classes))

    ha_const = ha_core_path / "homeassistant" / "const.py"
    if ha_const.exists():
        units = _extract_unit_enums(ha_const)
        if units:
            results.append(ExtractedConstantSet(name="UNIT_OF_MEASUREMENT", values=units))

    return results


def _parse_module_or_none(filepath: Path) -> ast.Module | None:
    """Parse a Python source file into an AST module, tolerating a ``SyntaxError``.

    Shared by every extractor below: each reads an upstream Home Assistant source file that may
    not parse (an unexpected format change, a partial checkout), and each must treat that as "no
    members found" rather than propagate the exception.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        return ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return None


def _extract_strenum_members(filepath: Path, class_name: str) -> list[str]:
    """Extract string values from a StrEnum class."""
    return list(_extract_strenum_name_to_value(filepath, class_name).values())


def _extract_enum_ref_set(filepath: Path, target_name: str, enum_class_name: str) -> list[str]:
    """Extract string values from a set literal of enum attribute references.

    Handles sets like ``NON_NUMERIC_DEVICE_CLASSES = {SensorDeviceClass.DATE, ...}`` — a set of
    ``ast.Attribute`` nodes, not string constants, so ``_extract_strenum_members`` does not apply
    directly. Each member is resolved against the enum's own name-to-value mapping (extracted from
    the same file) rather than lowercased, so this stays correct if a member's value ever diverges
    from its lowercased name. Tolerates a ``SyntaxError`` by returning empty, matching
    ``_extract_strenum_members``.
    """
    tree = _parse_module_or_none(filepath)
    if tree is None:
        return []

    name_to_value = _extract_strenum_name_to_value(filepath, enum_class_name)
    if not name_to_value:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == target_name for target in node.targets):
            continue
        if not isinstance(node.value, ast.Set):
            continue

        values: list[str] = []
        for elt in node.value.elts:
            if not isinstance(elt, ast.Attribute):
                continue
            if not isinstance(elt.value, ast.Name) or elt.value.id != enum_class_name:
                continue
            resolved = name_to_value.get(elt.attr)
            if resolved is not None:
                values.append(resolved)
        return values
    return []


def _extract_strenum_name_to_value(filepath: Path, class_name: str) -> dict[str, str]:
    """Extract a name-to-value mapping for a StrEnum class's string members.

    Keeps the member name (unlike ``_extract_strenum_members``, which discards it), which is what
    ``_extract_enum_ref_set`` needs to resolve ``EnumClass.MEMBER`` attribute references.
    """
    tree = _parse_module_or_none(filepath)
    if tree is None:
        return {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name != class_name:
            continue

        mapping: dict[str, str] = {}
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            for target in item.targets:
                if not isinstance(target, ast.Name):
                    continue
                if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                    mapping[target.id] = item.value.value
        return mapping
    return {}


def extract_numeric_state_expected_source(ha_core_path: Path) -> str | None:
    """Extract the source text of HA's ``_numeric_state_expected`` predicate.

    Used by the drift guard in ``pipeline.py`` to detect when Home Assistant changes the numeric
    branch's logic, which forces a human re-verification of the hand-written port in
    ``src/hassette/models/states/sensor_shapes.py``. Only the module-level function is matched
    (not the same-named compat method on the entity class) — ``tree.body`` holds only top-level
    statements, so the nested method never shadows it.

    Returns ``None`` if the file is missing, unparseable, or no longer defines the function at
    module level — all of which are themselves drift signals the caller must treat as a freshness
    failure, not skip silently.
    """
    init_py = ha_core_path / "homeassistant" / "components" / "sensor" / "__init__.py"
    if not init_py.exists():
        return None

    tree = _parse_module_or_none(init_py)
    if tree is None:
        return None

    source = init_py.read_text(encoding="utf-8")

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_numeric_state_expected":
            return ast.get_source_segment(source, node)
    return None


def _extract_unit_enums(ha_const: Path) -> list[str]:
    """Extract all unit values from UnitOf* enums in homeassistant/const.py."""
    tree = _parse_module_or_none(ha_const)
    if tree is None:
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
