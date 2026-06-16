"""Tests for App.app_key — per-instance identity, not class-shared.

Regression for #1060: app_key used to read the class-shared ``app_manifest``
ClassVar, so when two ``[apps.*]`` sections reused one App subclass, the section
loaded last clobbered app_key for every instance of that class. The wrong
app_key then rode out on the ``app_status_changed`` event and misattributed UI
start/stop actions.
"""

from types import SimpleNamespace

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.events.hassette import HassetteAppStateEvent
from hassette.test_utils import make_mock_hassette
from hassette.types.enums import ResourceStatus


class TestAppKey:
    def test_app_key_is_per_instance(self) -> None:
        """Each instance reports the app_key it was constructed with."""
        hassette = make_mock_hassette(sealed=False)

        app = App(
            hassette,
            app_config=AppConfig(instance_name="kitchen"),
            index=0,
            app_key="kitchen_lights",
        )

        assert app.app_key == "kitchen_lights"

    def test_app_key_ignores_shared_class_manifest(self) -> None:
        """Two app keys sharing one App subclass keep their own app_key, even
        after the shared app_manifest ClassVar is overwritten — and the status
        event carries each instance's own key."""
        hassette = make_mock_hassette(sealed=False)

        app_a = App(
            hassette,
            app_config=AppConfig(instance_name="blocking_io_lab"),
            index=0,
            app_key="blocking_io_lab",
        )
        app_b = App(
            hassette,
            app_config=AppConfig(instance_name="blocking_io_lab_ignore"),
            index=0,
            app_key="blocking_io_lab_ignore",
        )

        # Mimic the factory writing the shared ClassVar for the last section loaded.
        # App has no app_manifest in its own __dict__ by default, so deleting (not
        # restoring an original) is the correct cleanup for the attribute this test adds.
        App.app_manifest = SimpleNamespace(app_key="blocking_io_lab_ignore")
        try:
            assert app_a.app_key == "blocking_io_lab"
            assert app_b.app_key == "blocking_io_lab_ignore"

            event_a = HassetteAppStateEvent.from_data(app_a, status=ResourceStatus.STOPPED)
            event_b = HassetteAppStateEvent.from_data(app_b, status=ResourceStatus.STOPPED)
            assert event_a.payload.data.app_key == "blocking_io_lab"
            assert event_b.payload.data.app_key == "blocking_io_lab_ignore"
        finally:
            del App.app_manifest
