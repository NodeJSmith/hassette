"""Generate sensor constants file from extracted data."""

from hassette_codegen.extractors.constants import ExtractedConstantSet


def generate_sensor_constants(constant_sets: list[ExtractedConstantSet]) -> str:
    """Render src/hassette/const/sensor.py content."""
    lines = ["from typing import Literal", ""]

    for cs in constant_sets:
        lines.append(f"{cs.name} = Literal[")
        for val in cs.values:
            lines.append(f'    "{val}",')
        lines.append("]")
        lines.append("")

    return "\n".join(lines)
