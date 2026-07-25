"""Tests for the deprecated `@only_app` decorator.

`hassette run --app <key>` replaces it (issue #961). The decorator still sets `_only_app`
so existing apps keep working, but it warns and points at the CLI flag.
"""

import pytest

from hassette.app.app import App, only_app
from hassette.app.app_config import AppConfig


class TestOnlyAppDeprecation:
    def test_warns_and_points_at_the_cli_flag(self) -> None:
        with pytest.warns(DeprecationWarning, match=r"hassette run --app <key>"):

            @only_app
            class DecoratedApp(App[AppConfig]): ...

        assert DecoratedApp._only_app is True

    def test_undecorated_app_does_not_warn(self, recwarn: pytest.WarningsRecorder) -> None:
        class PlainApp(App[AppConfig]): ...

        assert PlainApp._only_app is False
        assert not [w for w in recwarn if issubclass(w.category, DeprecationWarning)]
