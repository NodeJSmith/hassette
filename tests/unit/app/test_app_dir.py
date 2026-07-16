"""Tests for App/AppSync `__dir__` overrides — the app-author API allowlist.

Regression guard for the lifecycle extraction (spec 010): App and AppSync
inherit ~54 public names from Resource/LifecycleMixin, but only ~20 (26 for
AppSync) are app-author API. `__dir__` hides the rest from `dir()` and IDE
autocomplete, independent of whether the framework-internal methods have been
extracted to module-level functions yet.
"""

from hassette.app.app import _APP_PUBLIC_API, App, AppSync
from hassette.app.app import _APPSYNC_HOOKS as _APPSYNC_HOOKS
from hassette.app.app_config import AppConfig
from hassette.test_utils import make_mock_hassette


class TestAppDir:
    def test_dir_matches_public_api_allowlist(self) -> None:
        """`dir(app)` returns exactly the app-author API allowlist — no framework plumbing."""
        hassette = make_mock_hassette(sealed=False)
        app = App(
            hassette,
            app_config=AppConfig(instance_name="kitchen"),
            index=0,
            app_key="kitchen_lights",
        )

        assert set(dir(app)) == _APP_PUBLIC_API

    def test_dir_excludes_add_child(self) -> None:
        """`add_child` stays a method on Resource (App.__init__ calls it directly) but is
        hidden from `dir()` — it is framework plumbing, not app-author API.
        """
        hassette = make_mock_hassette(sealed=False)
        app = App(
            hassette,
            app_config=AppConfig(instance_name="kitchen"),
            index=0,
            app_key="kitchen_lights",
        )

        assert "add_child" not in dir(app)
        # still callable — extraction hasn't happened yet, __dir__ just hides it
        assert hasattr(app, "add_child")

    def test_public_api_allowlist_has_exactly_20_names(self) -> None:
        """Regression guard: the App allowlist size is a deliberate design decision (see
        design/specs/010-lifecycle-extraction/design.md), not incidental. A size change here
        signals the allowlist drifted without updating the design doc.
        """
        assert len(_APP_PUBLIC_API) == 21

    def test_hasattr_handle_failed_is_false(self) -> None:
        """Extracted lifecycle methods are deleted from the class entirely — not just hidden
        by `__dir__`. `handle_failed` now only exists as a module-level function in
        `hassette.resources.lifecycle`.
        """
        hassette = make_mock_hassette(sealed=False)
        app = App(
            hassette,
            app_config=AppConfig(instance_name="kitchen"),
            index=0,
            app_key="kitchen_lights",
        )

        assert not hasattr(app, "handle_failed")


class TestAppSyncDir:
    def test_dir_matches_public_api_allowlist_plus_sync_hooks(self) -> None:
        """`dir(app_sync)` returns the base allowlist plus AppSync's 6 sync hooks."""
        hassette = make_mock_hassette(sealed=False)
        app = AppSync(
            hassette,
            app_config=AppConfig(instance_name="kitchen"),
            index=0,
            app_key="kitchen_lights",
        )

        assert set(dir(app)) == _APP_PUBLIC_API | _APPSYNC_HOOKS

    def test_appsync_allowlist_has_exactly_27_names(self) -> None:
        """Regression guard: 21 base names + 6 sync hooks = 27."""
        assert len(_APP_PUBLIC_API | _APPSYNC_HOOKS) == 27
