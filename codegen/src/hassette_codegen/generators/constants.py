"""Generate sensor constants file from extracted data."""

from hassette_codegen.extractors.constants import ExtractedConstantSet


def generate_sensor_constants(constant_sets: list[ExtractedConstantSet]) -> str:
    """Render src/hassette/const/sensor.py content."""
    lines = ["from typing import Literal", ""]

    for cs in constant_sets:
        lines.append(f"{cs.name} = Literal[")
        for i, val in enumerate(cs.values):
            comma = "," if i < len(cs.values) - 1 else ","
            lines.append(f'    "{val}"{comma}')
        lines.append("]")
        lines.append("")

    return "\n".join(lines)
