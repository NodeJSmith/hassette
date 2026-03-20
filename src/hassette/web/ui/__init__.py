"""Hassette Web UI — Jinja2 template engine setup."""

from pathlib import Path

from starlette.templating import Jinja2Templates

from hassette.web.ui.context import classify_error_rate, classify_health_bar

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
templates.env.globals["classify_error_rate"] = classify_error_rate
templates.env.globals["classify_health_bar"] = classify_health_bar
