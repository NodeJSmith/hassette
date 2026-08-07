"""Generate sensor constants file from extracted data."""

from hassette_codegen.extractors.constants import ExtractedConstantSet
from hassette_codegen.rendering import py_literal


def generate_sensor_constants(constant_sets: list[ExtractedConstantSet]) -> str:
    """Render src/hassette/const/sensor.py content."""
    lines = ["from typing import Literal", ""]

    for cs in constant_sets:
        if cs.kind == "runtime_set":
            lines.append(f"{cs.name}: frozenset[str] = frozenset(")
            lines.append("    {")
            for val in cs.values:
                lines.append(f"        {py_literal(val)},")
            lines.append("    }")
            lines.append(")")
            lines.append("")
            continue

        lines.append(f"{cs.name} = Literal[")
        for val in cs.values:
            lines.append(f"    {py_literal(val)},")
        lines.append("]")
        lines.append("")

    return "\n".join(lines)
