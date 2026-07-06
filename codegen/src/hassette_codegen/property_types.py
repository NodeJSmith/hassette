"""Map HA-internal property types to hassette-compatible types.

When the property extractor produces raw HA types via ast.unparse(), some of those
types reference HA-internal classes that won't exist in the generated output. This
module resolves them:

1. StrEnum names from the same domain -> kept as-is (the generator will produce them)
2. HA datetime types -> mapped to whenever library equivalents
3. HA-internal types -> mapped to Python equivalents
"""

import re

from hassette_codegen.extractors.properties import ExtractedProperty

# HA types that should be mapped to hassette-compatible types.
# Ordered longest-first so "dt.datetime" matches before "datetime".
HA_TYPE_MAP: list[tuple[str, str]] = [
    ("dt.datetime", "ZonedDateTime"),
    ("dt.date", "Date"),
    ("dt.time", "Time"),
    ("datetime", "ZonedDateTime"),
    ("date", "Date"),
    ("time", "Time"),
    ("StateType", "str | int | float | None"),
    ("UndefinedType", "object"),
    ("TodoItem", "Any"),
]

# Types that need import lines added to the generated file.
NEEDED_IMPORTS: dict[str, str] = {
    "ZonedDateTime": "from whenever import Date, Time, ZonedDateTime",
    "Date": "from whenever import Date, Time, ZonedDateTime",
    "Time": "from whenever import Date, Time, ZonedDateTime",
    "Decimal": "from decimal import Decimal",
    "Any": "from typing import Any",
}


def resolve_property_types(
    properties: list[ExtractedProperty],
    domain_strenum_names: set[str],
) -> tuple[list[ExtractedProperty], set[str]]:
    """Resolve HA-internal types in property annotations.

    Returns (new_properties, extra_imports) without mutating the originals.
    """
    extra_imports: set[str] = set()
    resolved_props: list[ExtractedProperty] = []

    for prop in properties:
        resolved, imports = _resolve_type(prop.python_type, domain_strenum_names)
        resolved_props.append(ExtractedProperty(name=prop.name, python_type=resolved, has_default=prop.has_default))
        extra_imports.update(imports)

    return resolved_props, extra_imports


def _resolve_type(type_str: str, domain_strenum_names: set[str]) -> tuple[str, set[str]]:
    """Resolve a single type string, returning (resolved_type, needed_imports)."""
    imports: set[str] = set()

    for ha_type, replacement in HA_TYPE_MAP:
        type_str = re.sub(rf"\b{re.escape(ha_type)}\b", replacement, type_str)

    for type_name, import_line in NEEDED_IMPORTS.items():
        if re.search(rf"\b{re.escape(type_name)}\b", type_str) and type_name not in domain_strenum_names:
            imports.add(import_line)

    return type_str, imports
