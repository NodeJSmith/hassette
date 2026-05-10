"""Generate state model .py files from extracted domain data."""

from pathlib import Path

import jinja2

from hassette_codegen.domain_data import ExtractedDomain, domain_to_title
from hassette_codegen.property_types import resolve_property_types

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def _get_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def generate_state_model(domain: ExtractedDomain) -> str:
    """Render a state model .py file for a domain."""
    env = _get_env()
    template = env.get_template("state_model.py.j2")

    extra_imports: list[str] = []
    if domain.override and "state" in domain.override.extra_imports:
        extra_imports = list(domain.override.extra_imports["state"])

    base_class = domain.base_class
    if domain.override and domain.override.state_base_class:
        base_class = domain.override.state_base_class

    domain_title = domain_to_title(domain.name)

    pydantic_class_name = f"{domain_title}State"
    strenums, renames = _rename_collisions(domain.strenums, pydantic_class_name)

    strenum_names = {e.name for e in strenums}
    _apply_type_renames(domain.properties, renames)
    _props, type_imports = resolve_property_types(domain.properties, strenum_names)
    extra_imports.extend(sorted(type_imports))

    has_intflag = len(domain.features) > 0
    has_strenum = len(strenums) > 0

    return template.render(
        domain=domain.name,
        domain_title=domain_title,
        base_class=base_class,
        features=domain.features,
        strenums=strenums,
        properties=domain.properties,
        extra_imports=extra_imports,
        has_intflag=has_intflag,
        has_strenum=has_strenum,
    )


def _rename_collisions(strenums: list, pydantic_class_name: str) -> tuple[list, dict[str, str]]:
    """Rename StrEnums that collide with the Pydantic state class name."""
    from copy import deepcopy

    result = []
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


def _apply_type_renames(properties: list, renames: dict[str, str]) -> None:
    """Apply StrEnum renames to property type annotations."""
    for prop in properties:
        for old_name, new_name in renames.items():
            if old_name in prop.python_type:
                prop.python_type = prop.python_type.replace(old_name, new_name)
