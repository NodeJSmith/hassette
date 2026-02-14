"""Hassette Web UI — Jinja2 template engine setup."""

from pathlib import Path

from starlette.templating import Jinja2Templates

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
