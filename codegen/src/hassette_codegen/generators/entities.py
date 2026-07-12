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
    doc: str


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
    literal_shape_to_alias: dict[str, str] = {}
    used_alias_names: set[str] = set()
    domain_title = domain_to_title(domain.name)

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

            # Promote Literal[...] sets to named aliases for readability — whether the type is
            # a bare Literal[...] or a list[Literal[...]] (from a multiple: true select). Key the
            # cache by literal shape, not param name: two services can share a param name (e.g.
            # "mode") with different Literal sets, so alias names must stay distinct or the second
            # set would silently overwrite the first.
            list_wrapped = python_type.startswith("list[Literal[") and python_type.endswith("]")
            literal_shape = python_type[len("list[") : -1] if list_wrapped else python_type
            if literal_shape.startswith("Literal["):
                alias_name = literal_shape_to_alias.get(literal_shape)
                if alias_name is None:
                    base_name = _make_alias_name(param_name, domain_title)
                    alias_name = base_name
                    # Disambiguate collisions with a numeric suffix from 2: ClimateMode, ClimateMode2, ClimateMode3.
                    suffix = 2
                    while alias_name in used_alias_names:
                        alias_name = f"{base_name}{suffix}"
                        suffix += 1
                    literal_shape_to_alias[literal_shape] = alias_name
                    used_alias_names.add(alias_name)
                    type_aliases.append((alias_name, literal_shape))
                python_type = f"list[{alias_name}]" if list_wrapped else alias_name

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
        summary = service.description or f"Call the {domain.name}.{service.name} service."
        services_for_template.append(
            ServiceForTemplate(
                name=service.name,
                method_name=service.method_name,
                params=sorted_params,
                doc=build_method_docstring(summary, sorted_params),
            )
        )

    return template.render(
        domain=domain.name,
        domain_title=domain_title,
        services=services_for_template,
        extra_imports=extra_imports,
        type_aliases=type_aliases,
    )


def _make_alias_name(param_name: str, domain_title: str) -> str:
    """Convert a param name to a domain-prefixed PascalCase type alias name."""
    base = param_name.replace("_", " ").title().replace(" ", "")
    return f"{domain_title}{base}"


def build_method_docstring(summary: str, params: list[ServiceParam]) -> str:
    """Build a Google-style docstring body for an entity service method.

    The returned string carries its own 8-space indentation and triple quotes, so the template
    inserts it verbatim. ``summary`` is Home Assistant's own service description; only params with
    a resolved field description appear in ``Args``. Text is rewrapped to the project line length
    and given a trailing period when it lacks terminal punctuation. No ``Returns`` section is
    emitted — the ``-> None`` / ``-> Coroutine`` annotation already states the return.
    """
    lines = textwrap.fill(
        _with_period(summary),
        width=LINE_LENGTH,
        initial_indent=f'{DOCSTRING_INDENT}"""',
        subsequent_indent=DOCSTRING_INDENT,
        break_long_words=False,
        break_on_hyphens=False,
    ).splitlines()

    documented = [p for p in params if p.description]
    if documented:
        lines.append("")
        lines.append(f"{DOCSTRING_INDENT}Args:")
        for param in documented:
            # Google hanging indent: the ``name:`` label sits at +4, continuation lines at +8.
            lines.append(
                textwrap.fill(
                    _with_period(param.description or ""),
                    width=LINE_LENGTH,
                    initial_indent=f"{DOCSTRING_INDENT}    {param.name}: ",
                    subsequent_indent=f"{DOCSTRING_INDENT}        ",
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )

    lines.append(f'{DOCSTRING_INDENT}"""')
    return "\n".join(lines)


def _with_period(text: str) -> str:
    """Collapse whitespace and append a period when the text lacks terminal punctuation."""
    text = " ".join(text.split())
    if text and not text.endswith((".", "!", "?")):
        text += "."
    return text
