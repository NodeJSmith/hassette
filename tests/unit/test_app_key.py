"""Tests for App.app_key — per-instance identity, not class-shared.

Regression for #1060: app_key used to read the class-shared ``app_manifest``
ClassVar, so when two ``[apps.*]`` sections reused one App subclass, the section
loaded last clobbered app_key for every instance of that class. The wrong
app_key then rode out on the ``app_status_changed`` event and misattributed UI
start/stop actions.
"""

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from hassette_wire import ResourceStatus

from hassette.app.app import App
from hassette.events.hassette import HassetteAppStateEvent
from tests.support.factories import make_app
from tests.support.mock_hassette import make_mock_hassette

if TYPE_CHECKING:
    from hassette.config.classes import AppManifest


class TestAppKey:
    def test_app_key_is_per_instance(self) -> None:
        """Each instance reports the app_key it was constructed with."""
        app = make_app()

        assert app.app_key == "kitchen_lights"

    def test_app_key_ignores_shared_class_manifest(self) -> None:
        """Two app keys sharing one App subclass keep their own app_key, even
        after the shared app_manifest ClassVar is overwritten — and the status
        event carries each instance's own key.
        """
        hassette = make_mock_hassette(sealed=False)

        app_a = make_app(hassette=hassette, instance_name="blocking_io_lab", app_key="blocking_io_lab")
        app_b = make_app(hassette=hassette, instance_name="blocking_io_lab_ignore", app_key="blocking_io_lab_ignore")

        # Mimic the factory writing the shared ClassVar for the last section loaded.
        # App has no app_manifest in its own __dict__ by default, so deleting (not
        # restoring an original) is the correct cleanup for the attribute this test adds.
        App.app_manifest = cast("AppManifest", SimpleNamespace(app_key="blocking_io_lab_ignore"))
        try:
            assert app_a.app_key == "blocking_io_lab"
            assert app_b.app_key == "blocking_io_lab_ignore"

            event_a = HassetteAppStateEvent.from_app(app_a, status=ResourceStatus.STOPPED)
            event_b = HassetteAppStateEvent.from_app(app_b, status=ResourceStatus.STOPPED)
            assert event_a.payload.data.app_key == "blocking_io_lab"
            assert event_b.payload.data.app_key == "blocking_io_lab_ignore"
        finally:
            del App.app_manifest
