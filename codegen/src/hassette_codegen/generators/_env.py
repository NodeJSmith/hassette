"""Shared Jinja2 environment for code generation templates."""

from functools import lru_cache
from pathlib import Path

import jinja2

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


@lru_cache(maxsize=1)
def get_jinja_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
