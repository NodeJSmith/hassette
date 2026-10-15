"""Test app whose base-class order fails inheritance validation."""

from typing import Any

from hassette import App, AppConfig


class InitDefiningMixin:
    """Non-App base listed before App, so its ``__init__`` would shadow ``App.__init__``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)


class InvalidInheritanceApp(InitDefiningMixin, App[AppConfig]):
    """App that lists an ``__init__``-defining base before App, which validate_app rejects."""
