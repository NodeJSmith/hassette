"""Generate state model .py files from extracted domain data."""

import re
from copy import deepcopy

from hassette_codegen.domain_data import ExtractedDomain, domain_to_title
from hassette_codegen.extractors.features import ExtractedEnum
from hassette_codegen.extractors.properties import ExtractedProperty
from hassette_codegen.generators._env import get_jinja_env
from hassette_codegen.property_types import resolve_property_types

_ATTRIBUTE_SUFFIX_RE = re.compile(r"(?:Entity)?(?P<attr_type>State|Capability)Attribute$")


def generate_state_model(domain: ExtractedDomain) -> str:
    """Render a state model .py file for a domain."""
    env = get_jinja_env()
    template = env.get_template("state_model.py.j2")

    extra_imports: list[str] = []
    if domain.override and "state" in domain.override.extra_imports:
        extra_imports = list(domain.override.extra_imports["state"])

    base_class = domain.base_class
    if domain.override and domain.override.state_base_class:
        base_class = domain.override.state_base_class

    domain_title = domain_to_title(domain.name)

    strenums, prefix_renames = _normalize_enum_prefixes(domain.strenums, domain_title)
    pydantic_class_name = f"{domain_title}State"
    strenums, collision_renames = rename_collisions(strenums, pydantic_class_name)
    renames = {**prefix_renames, **collision_renames}

    strenum_names = {e.name for e in strenums}
    properties = _apply_type_renames(domain.properties, renames)
    properties, type_imports = resolve_property_types(properties, strenum_names)
    extra_imports.extend(sorted(type_imports))

    has_intflag = len(domain.features) > 0
    has_strenum = len(strenums) > 0

    datetime_fields = [p.name for p in properties if _is_pure_datetime_field(p.python_type)]
    if datetime_fields:
        extra_imports.append("from hassette.utils.date_utils import convert_datetime_str_to_system_tz")

    return template.render(
        domain=domain.name,
        domain_title=domain_title,
        base_class=base_class,
        features=domain.features,
        strenums=strenums,
        properties=properties,
        extra_imports=sorted(set(extra_imports)),
        has_intflag=has_intflag,
        has_strenum=has_strenum,
        datetime_fields=datetime_fields,
    )


def _normalize_enum_prefixes(
    strenums: list[ExtractedEnum], domain_title: str
) -> tuple[list[ExtractedEnum], dict[str, str]]:
    """Normalize domain-prefixed enum names to use the canonical domain title and include 'Entity'."""
    result: list[ExtractedEnum] = []
    renames: dict[str, str] = {}
    for enum in strenums:
        match = _ATTRIBUTE_SUFFIX_RE.search(enum.name)
        if not match:
            result.append(enum)
            continue

        attr_type = match.group("attr_type")
        prefix = enum.name[: match.start()]

        if prefix.lower() != domain_title.lower():
            result.append(enum)
            continue

        canonical = f"{domain_title}Entity{attr_type}Attribute"
        if canonical == enum.name:
            result.append(enum)
            continue

        renamed = deepcopy(enum)
        renamed.name = canonical
        result.append(renamed)
        renames[enum.name] = canonical

    return result, renames


def rename_collisions(
    strenums: list[ExtractedEnum], pydantic_class_name: str
) -> tuple[list[ExtractedEnum], dict[str, str]]:
    """Rename StrEnums that collide with the Pydantic state class name."""
    result: list[ExtractedEnum] = []
    renames: dict[str, str] = {}
    for enum in strenums:
        if enum.name == pydantic_class_name:
            renamed = deepcopy(enum)
            renamed.name = f"{enum.name}Value"
            result.append(renamed)
            renames[enum.name] = renamed.name
        else:
            result.append(enum)
    return result, renames


def _apply_type_renames(properties: list[ExtractedProperty], renames: dict[str, str]) -> list[ExtractedProperty]:
    """Apply StrEnum renames to property type annotations, returning new objects."""
    result: list[ExtractedProperty] = []
    for prop in properties:
        python_type = prop.python_type
        for old_name, new_name in renames.items():
            if old_name in python_type:
                python_type = python_type.replace(old_name, new_name)
        result.append(ExtractedProperty(name=prop.name, python_type=python_type, has_default=prop.has_default))
    return result


def _is_pure_datetime_field(python_type: str) -> bool:
    """Check if a type annotation is purely ZonedDateTime (not a broad union with other types)."""
    parts = {p.strip() for p in python_type.split("|")}
    return "ZonedDateTime" in parts and parts <= {"ZonedDateTime", "None"}
