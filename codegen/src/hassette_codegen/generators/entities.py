"""Generate entity wrapper .py files from extracted domain data."""

from dataclasses import dataclass

from hassette_codegen.domain_data import ExtractedDomain, domain_to_title
from hassette_codegen.generators._env import get_jinja_env
from hassette_codegen.type_mapping import map_selector_to_type


@dataclass
class ServiceParam:
    name: str
    python_type: str
    required: bool = False


@dataclass
class ServiceForTemplate:
    name: str
    method_name: str
    params: list[ServiceParam]


def generate_entity_wrapper(domain: ExtractedDomain) -> str | None:
    """Render an entity wrapper .py file for a domain.

    Returns None if the domain has no services (state-only domain like sensor).
    """
    if not domain.services:
        return None

    env = get_jinja_env()
    template = env.get_template("entity_wrapper.py.j2")

    extra_imports: list[str] = []
    if domain.override and "entity" in domain.override.extra_imports:
        extra_imports = domain.override.extra_imports["entity"]

    services_for_template: list[ServiceForTemplate] = []
    type_aliases: list[tuple[str, str]] = []
    seen_aliases: set[str] = set()

    for service in domain.services:
        params: list[ServiceParam] = []
        for field in service.fields:
            param_name = field.name
            if domain.override and param_name in domain.override.service_param_renames:
                param_name = domain.override.service_param_renames[param_name]

            if domain.override and field.name in domain.override.param_type_overrides:
                python_type = domain.override.param_type_overrides[field.name]
            else:
                python_type = map_selector_to_type(field.selector_type, field.selector_data, domain.name)

            if python_type.startswith("Literal[") and python_type not in seen_aliases:
                alias_name = _make_alias_name(param_name)
                type_aliases.append((alias_name, python_type))
                seen_aliases.add(python_type)
                python_type = alias_name

            if not field.required:
                if "None" not in python_type:
                    python_type = f"{python_type} | None"

            params.append(ServiceParam(name=param_name, python_type=python_type, required=field.required))

        services_for_template.append(
            ServiceForTemplate(
                name=service.name,
                method_name=service.method_name,
                params=sorted(params, key=lambda p: (not p.required, p.name)),
            )
        )

    domain_title = domain_to_title(domain.name)

    return template.render(
        domain=domain.name,
        domain_title=domain_title,
        services=services_for_template,
        extra_imports=extra_imports,
        type_aliases=type_aliases,
    )


def _make_alias_name(param_name: str) -> str:
    """Convert a param name to a PascalCase type alias name."""
    return param_name.replace("_", " ").title().replace(" ", "")
