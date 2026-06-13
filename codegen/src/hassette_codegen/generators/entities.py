"""Generate entity wrapper .py files from extracted domain data.

This is the second of two sync-facade codegen paths. The first — `codegen/src/hassette_codegen/sync_facade/` — wraps
`Api`/`Bus`/`Scheduler` methods via AST body-copy and emits `self.task_bucket.run_sync(...)`.
This path is template-driven (`templates/entity_wrapper.py.j2`) and emits per-domain
`{Domain}EntitySyncFacade` classes that delegate through `self.entity.api.sync.call_service(...)`.

The two paths share no abstraction, so a cross-cutting change to sync dispatch — a new timeout
parameter, telemetry on every sync call, a different error surface — must be applied in both.
Consolidating them is tracked in #938; until then, edit both when changing how sync facades
dispatch.
"""

import textwrap
from dataclasses import dataclass

from hassette_codegen.domain_data import ExtractedDomain, domain_to_title
from hassette_codegen.generators._env import get_jinja_env
from hassette_codegen.type_mapping import map_selector_to_type

DOCSTRING_INDENT = " " * 8
LINE_LENGTH = 120


@dataclass
class ServiceParam:
    name: str
    python_type: str
    required: bool = False
    description: str | None = None


@dataclass
class ServiceForTemplate:
    name: str
    method_name: str
    params: list[ServiceParam]
    async_doc: str
    sync_doc: str


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

            params.append(
                ServiceParam(
                    name=param_name,
                    python_type=python_type,
                    required=field.required,
                    description=field.description,
                )
            )

        sorted_params = sorted(params, key=lambda p: (not p.required, p.name))
        summary = f"Call the {domain.name}.{service.name} service"
        services_for_template.append(
            ServiceForTemplate(
                name=service.name,
                method_name=service.method_name,
                params=sorted_params,
                async_doc=build_method_docstring(f"{summary}.", sorted_params, returns_none=False),
                sync_doc=build_method_docstring(f"{summary} synchronously.", sorted_params, returns_none=True),
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


def build_method_docstring(summary: str, params: list[ServiceParam], *, returns_none: bool) -> str:
    """Build a Google-style docstring body for an entity service method.

    The returned string carries its own 8-space indentation and triple quotes, so the template
    inserts it verbatim. Only params with a resolved Home Assistant description appear in ``Args``;
    descriptions are rewrapped to the project line length and given a trailing period when they
    lack terminal punctuation.
    """
    lines = [f'{DOCSTRING_INDENT}"""{summary}']

    documented = [p for p in params if p.description]
    if documented:
        lines.append("")
        lines.append(f"{DOCSTRING_INDENT}Args:")
        for param in documented:
            text = " ".join((param.description or "").split())
            if not text.endswith((".", "!", "?")):
                text += "."
            # Google hanging indent: the ``name:`` label sits at +4, continuation lines at +8.
            lines.append(
                textwrap.fill(
                    text,
                    width=LINE_LENGTH,
                    initial_indent=f"{DOCSTRING_INDENT}    {param.name}: ",
                    subsequent_indent=f"{DOCSTRING_INDENT}        ",
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )

    if returns_none:
        lines.append("")
        lines.append(f"{DOCSTRING_INDENT}Returns:")
        lines.append(f"{DOCSTRING_INDENT}    None.")

    lines.append(f'{DOCSTRING_INDENT}"""')
    return "\n".join(lines)
