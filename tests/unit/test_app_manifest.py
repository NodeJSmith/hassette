"""Tests for App.app_manifest — per-instance, not class-shared.

Regression for #1062: app_manifest used to be a ClassVar the factory overwrote
once per ``[apps.*]`` section, so when two sections reused one App subclass the
section loaded last clobbered ``display_name``/``enabled``/``auto_loaded`` for
every instance of that class. This mirrors the per-instance app_key fix
(#1060/#1064): each instance now carries its own manifest.
"""

from pathlib import Path
from types import SimpleNamespace

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.test_utils import create_app_manifest, make_mock_hassette


class TestAppManifest:
    def test_app_manifest_is_per_instance(self) -> None:
        """Each instance reports the manifest it was constructed with."""
        hassette = make_mock_hassette(sealed=False)
        manifest = create_app_manifest("kitchen", app_dir=Path("/tmp/apps"))

        app = App(
            hassette,
            app_config=AppConfig(instance_name="kitchen"),
            index=0,
            app_key="my_app_kitchen",
            app_manifest=manifest,
        )

        assert app.app_manifest is manifest

    def test_app_manifest_ignores_shared_class_attr(self) -> None:
        """Two instances sharing one App subclass keep their own manifest, even
        after a clobbering class-level attribute is written for the last section."""
        hassette = make_mock_hassette(sealed=False)
        manifest_a = create_app_manifest("a", app_dir=Path("/tmp/apps"))
        manifest_b = create_app_manifest("b", app_dir=Path("/tmp/apps"))

        app_a = App(
            hassette,
            app_config=AppConfig(instance_name="a"),
            index=0,
            app_key="my_app_a",
            app_manifest=manifest_a,
        )
        app_b = App(
            hassette,
            app_config=AppConfig(instance_name="b"),
            index=0,
            app_key="my_app_b",
            app_manifest=manifest_b,
        )

        # Mimic the old factory writing a shared class attr for the last section loaded.
        # The clobber value matches neither instance's display_name, so each assertion
        # below fails if the instance read falls through to the class attribute. App has
        # no app_manifest in its own __dict__ now, so deleting (not restoring an original)
        # is the correct cleanup for the attribute this test adds.
        App.app_manifest = SimpleNamespace(display_name="CLOBBERED")  # pyright: ignore[reportAttributeAccessIssue]
        try:
            assert app_a.app_manifest is manifest_a
            assert app_b.app_manifest is manifest_b
            assert app_a.app_manifest.display_name == "MyAppA"
            assert app_b.app_manifest.display_name == "MyAppB"
        finally:
            del App.app_manifest
