import re

from hassette.core.type_registry import register_type_converter_fn


@register_type_converter_fn
def str_with_units_to_float(value: str) -> float:
    """Extract numeric value from string with units.

    Example: '23.5 °C' → 23.5
    Types inferred from signature: str → float
    """
    match = re.match(r"^([-+]?[0-9]*\.?[0-9]+)", value.strip())
    if match:
        return float(match.group(1))
    raise ValueError(f"Cannot extract number from '{value}'")
