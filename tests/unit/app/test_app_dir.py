"""Tests for App/AppSync `__dir__` overrides — the app-author API allowlist.

Regression guard for the lifecycle extraction (spec 010): App and AppSync
inherit ~54 public names from Resource/LifecycleMixin, but only ~20 (26 for
AppSync) are app-author API. `__dir__` hides the rest from `dir()` and IDE
autocomplete, independent of whether the framework-internal methods have been
extracted to module-level functions yet.
"""

from hassette.app.app import _APP_PUBLIC_API, AppSync
from hassette.app.app import _APPSYNC_HOOKS as _APPSYNC_HOOKS
from tests.support.factories import make_app


class TestAppDir:
    def test_dir_matches_public_api_allowlist(self) -> None:
        """`dir(app)` returns exactly the app-author API allowlist — no framework plumbing."""
        app = make_app()

        assert set(dir(app)) == _APP_PUBLIC_API

    def test_dir_excludes_add_child(self) -> None:
        """`add_child` stays a method on Resource (App.__init__ calls it directly) but is
        hidden from `dir()` — it is framework plumbing, not app-author API.
        """
        app = make_app()

        assert "add_child" not in dir(app)
        # still callable — extraction hasn't happened yet, __dir__ just hides it
        assert hasattr(app, "add_child")

    def test_public_api_allowlist_has_exactly_23_names(self) -> None:
        """Regression guard: the App allowlist size is a deliberate design decision (see
        design/specs/010-lifecycle-extraction/design.md), not incidental. A size change here
        signals the allowlist drifted without updating the design doc.
        """
        assert len(_APP_PUBLIC_API) == 23

    def test_hasattr_handle_failed_is_false(self) -> None:
        """Extracted lifecycle methods are deleted from the class entirely — not just hidden
        by `__dir__`. `handle_failed` now only exists as a module-level function in
        `hassette.resources.lifecycle`.
        """
        app = make_app()

        assert not hasattr(app, "handle_failed")


class TestAppSyncDir:
    def test_dir_matches_public_api_allowlist_plus_sync_hooks(self) -> None:
        """`dir(app_sync)` returns the base allowlist plus AppSync's 6 sync hooks."""
        app = make_app(cls=AppSync)

        assert set(dir(app)) == _APP_PUBLIC_API | _APPSYNC_HOOKS

    def test_appsync_allowlist_has_exactly_29_names(self) -> None:
        """Regression guard: 23 base names + 6 sync hooks = 29."""
        assert len(_APP_PUBLIC_API | _APPSYNC_HOOKS) == 29
