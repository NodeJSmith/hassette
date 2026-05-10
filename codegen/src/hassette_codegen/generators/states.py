"""Generate state model .py files from extracted domain data."""

from pathlib import Path

import jinja2

from hassette_codegen.domain_data import ExtractedDomain

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
        extra_imports = domain.override.extra_imports["state"]

    base_class = domain.base_class
    if domain.override and domain.override.state_base_class:
        base_class = domain.override.state_base_class

    domain_title = domain.name.replace("_", " ").title().replace(" ", "")

    return template.render(
        domain=domain.name,
        domain_title=domain_title,
        base_class=base_class,
        features=domain.features,
        properties=domain.properties,
        extra_imports=extra_imports,
    )
