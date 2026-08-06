"""Shared Jinja2 environment for code generation templates."""

from functools import lru_cache
from pathlib import Path

import jinja2

from hassette_codegen.rendering import py_literal

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


@lru_cache(maxsize=1)
def get_jinja_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Templates emit Python, so upstream-derived values must never be hand-quoted — see
    # hassette_codegen.rendering. Autoescape stays off deliberately: HTML escaping is the wrong
    # escaping for this output and would corrupt generated source.
    env.filters["py_literal"] = py_literal
    return env
