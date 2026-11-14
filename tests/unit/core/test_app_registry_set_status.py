"""``AppRegistry.set_status``: the one writer of app instance status."""

import logging
from unittest.mock import MagicMock

import pytest
from hassette_wire import ResourceStatus

from hassette.core.app_registry import UNKNOWN_LABEL, AppRegistry, StatusChange
from hassette.schemas.app_snapshots import NeedsRestartInfo
from hassette.utils import date_utils
from tests.support.app_registry_helpers import seed_failed, seed_running

from .conftest import make_manifest_obj

APP_KEY = "my_app"
NAME = "kitchen"


@pytest.fixture
def registry() -> AppRegistry:
    return AppRegistry()


@pytest.fixture
def app() -> MagicMock:
    return MagicMock(instance_name=NAME, class_name="KitchenApp")


def change(
    previous: ResourceStatus,
    status: ResourceStatus,
    error: Exception | None = None,
    needs_restart: NeedsRestartInfo | None = None,
) -> StatusChange:
    return StatusChange(
        app_key=APP_KEY,
        instance_name=NAME,
        class_name="KitchenApp",
        previous=previous,
        status=status,
        error=error,
        needs_restart=needs_restart,
    )


class TestTransitions:
    def test_each_phase_is_a_change_from_the_entry_status(self, registry: AppRegistry, app: MagicMock) -> None:
        """The previous status comes from the entry, so every phase reports where it came from."""
        assert registry.set_status(APP_KEY, NAME, ResourceStatus.NOT_STARTED, app=app) is None
        assert registry.set_status(APP_KEY, NAME, ResourceStatus.STARTING) == change(
            ResourceStatus.NOT_STARTED, ResourceStatus.STARTING
        )
        assert registry.set_status(APP_KEY, NAME, ResourceStatus.RUNNING) == change(
            ResourceStatus.STARTING, ResourceStatus.RUNNING
        )
        assert registry.set_status(APP_KEY, NAME, ResourceStatus.STOPPING) == change(
            ResourceStatus.RUNNING, ResourceStatus.STOPPING
        )
        assert registry.set_status(APP_KEY, NAME, ResourceStatus.STOPPED) == change(
            ResourceStatus.STOPPING, ResourceStatus.STOPPED
        )

    @pytest.mark.parametrize("status", [ResourceStatus.STARTING, ResourceStatus.RUNNING, ResourceStatus.STOPPING])
    def test_live_writes_keep_the_app(self, registry: AppRegistry, app: MagicMock, status: ResourceStatus) -> None:
        """STARTING, RUNNING and STOPPING keep the registered App."""
        registry.set_status(APP_KEY, NAME, ResourceStatus.NOT_STARTED, app=app)

        registry.set_status(APP_KEY, NAME, status)

        entry = registry.get_instances(APP_KEY)[NAME]
        assert entry.app is app
        assert entry.status is status

    def test_failed_write_drops_the_app_and_carries_the_error(self, registry: AppRegistry, app: MagicMock) -> None:
        """A failed init goes STARTING -> FAILED over the live entry, dropping the App."""
        seed_running(registry, APP_KEY, app, status=ResourceStatus.STARTING)
        error = ValueError("boom")

        result = registry.set_status(APP_KEY, NAME, ResourceStatus.FAILED, error=error)

        assert result == change(ResourceStatus.STARTING, ResourceStatus.FAILED, error)
        assert registry.get(APP_KEY, NAME) is None
        assert registry.get_instances(APP_KEY)[NAME].error is error

    def test_stopped_change_carries_no_error(self, registry: AppRegistry) -> None:
        """Discarding a failure is FAILED -> STOPPED with no error on the change."""
        seed_failed(registry, APP_KEY, NAME, ValueError("boom"))

        result = registry.set_status(APP_KEY, NAME, ResourceStatus.STOPPED)

        assert result is not None
        assert result.previous is ResourceStatus.FAILED
        assert result.error is None


class TestMissingEntry:
    def test_registration_onto_a_missing_entry_is_no_change(self, registry: AppRegistry, app: MagicMock) -> None:
        """A missing entry reads as NOT_STARTED, so registering creates the entry but owes no event."""
        assert registry.set_status(APP_KEY, NAME, ResourceStatus.NOT_STARTED, app=app) is None
        assert registry.get(APP_KEY, NAME) is app

    def test_create_time_failure_is_a_change_from_not_started(self, registry: AppRegistry) -> None:
        """A failure before any App existed is NOT_STARTED -> FAILED, with the manifest's class name."""
        manifest = make_manifest_obj(APP_KEY)
        registry.set_manifests({APP_KEY: manifest})
        error = ValueError("bad config")

        result = registry.set_status(APP_KEY, NAME, ResourceStatus.FAILED, error=error)

        assert result == StatusChange(
            app_key=APP_KEY,
            instance_name=NAME,
            class_name=manifest.class_name,
            previous=ResourceStatus.NOT_STARTED,
            status=ResourceStatus.FAILED,
            error=error,
        )

    def test_class_name_without_app_or_manifest_is_unknown(self, registry: AppRegistry) -> None:
        result = registry.set_status(APP_KEY, NAME, ResourceStatus.FAILED, error=ValueError("x"))

        assert result is not None
        assert result.class_name == UNKNOWN_LABEL

    @pytest.mark.parametrize(
        "to", [ResourceStatus.STARTING, ResourceStatus.RUNNING, ResourceStatus.STOPPING, ResourceStatus.STOPPED]
    )
    def test_other_writes_onto_a_missing_entry_are_dropped(self, registry: AppRegistry, to: ResourceStatus) -> None:
        """A late writer racing exit or a concurrent stop can't create a ghost entry or a bogus change."""
        assert registry.set_status(APP_KEY, NAME, to) is None
        assert registry.get_instances(APP_KEY) == {}
        assert APP_KEY not in registry._instances

    def test_a_restart_reports_not_started_to_starting(self, registry: AppRegistry, app: MagicMock) -> None:
        """STOPPED removes the entry, so the next start is a new instance."""
        seed_running(registry, APP_KEY, app)
        registry.set_status(APP_KEY, NAME, ResourceStatus.STOPPED)

        registry.set_status(APP_KEY, NAME, ResourceStatus.NOT_STARTED, app=app)
        result = registry.set_status(APP_KEY, NAME, ResourceStatus.STARTING)

        assert result == change(ResourceStatus.NOT_STARTED, ResourceStatus.STARTING)


class TestChangeDetection:
    def test_same_status_is_no_change(self, registry: AppRegistry, app: MagicMock) -> None:
        seed_running(registry, APP_KEY, app)

        assert registry.set_status(APP_KEY, NAME, ResourceStatus.RUNNING) is None

    def test_a_new_error_object_is_a_change(self, registry: AppRegistry) -> None:
        """FAILED -> FAILED with a different error emits, so the UI shows the current failure."""
        seed_failed(registry, APP_KEY, NAME, ValueError("first"))
        second = ValueError("second")

        result = registry.set_status(APP_KEY, NAME, ResourceStatus.FAILED, error=second)

        assert result is not None
        assert result.previous is ResourceStatus.FAILED
        assert result.error is second

    def test_the_same_error_object_is_no_change(self, registry: AppRegistry) -> None:
        error = ValueError("same")
        seed_failed(registry, APP_KEY, NAME, error)

        assert registry.set_status(APP_KEY, NAME, ResourceStatus.FAILED, error=error) is None

    def test_a_retry_over_a_failure_is_failed_to_not_started(self, registry: AppRegistry, app: MagicMock) -> None:
        """Registering over an unflagged failure clears it in the UI."""
        seed_failed(registry, APP_KEY, NAME, ValueError("boom"))

        result = registry.set_status(APP_KEY, NAME, ResourceStatus.NOT_STARTED, app=app)

        assert result == change(ResourceStatus.FAILED, ResourceStatus.NOT_STARTED)
        assert registry.get(APP_KEY, NAME) is app


class TestNeedsRestart:
    def test_the_flag_is_part_of_the_failed_write(self, registry: AppRegistry, app: MagicMock) -> None:
        """One FAILED write both reports the failure and stores the flag; flagging isn't a separate step."""
        seed_running(registry, APP_KEY, app, status=ResourceStatus.STOPPING)
        error = ValueError("hung")
        flag = NeedsRestartInfo(reason="work still running", pending_tasks=(), flagged_at=date_utils.now())

        result = registry.set_status(APP_KEY, NAME, ResourceStatus.FAILED, error=error, needs_restart=flag)

        assert result == change(ResourceStatus.STOPPING, ResourceStatus.FAILED, error, needs_restart=flag)
        assert registry.get_needs_restart(APP_KEY, NAME) is flag

    def test_flagging_a_failed_entry_with_the_same_error_is_a_change(self, registry: AppRegistry) -> None:
        """Adding the flag to a FAILED entry reports a change even when the error object is unchanged."""
        error = ValueError("hung")
        seed_failed(registry, APP_KEY, NAME, error)
        flag = NeedsRestartInfo(reason="work still running", pending_tasks=(), flagged_at=date_utils.now())

        result = registry.set_status(APP_KEY, NAME, ResourceStatus.FAILED, error=error, needs_restart=flag)

        assert result is not None
        assert (result.previous, result.status, result.needs_restart) == (
            ResourceStatus.FAILED,
            ResourceStatus.FAILED,
            flag,
        )

    def test_a_later_failure_reports_the_standing_flag(self, registry: AppRegistry) -> None:
        """A FAILED change over a flagged entry carries the flag it keeps, so its event still says needs-restart."""
        seed_failed(registry, APP_KEY, NAME, ValueError("first"), needs_restart="first reason")

        result = registry.set_status(APP_KEY, NAME, ResourceStatus.FAILED, error=ValueError("second"))

        assert result is not None
        assert result.needs_restart is not None
        assert result.needs_restart.reason == "first reason"

    def test_the_first_flag_stands_and_a_later_failure_replaces_the_error(self, registry: AppRegistry) -> None:
        """A FAILED write over a flagged entry keeps the original flag, and a new error still emits."""
        seed_failed(registry, APP_KEY, NAME, ValueError("first"), needs_restart="first reason")
        second = ValueError("second")

        result = registry.set_status(APP_KEY, NAME, ResourceStatus.FAILED, error=second)

        assert result is not None
        entry = registry.get_instances(APP_KEY)[NAME]
        assert entry.error is second
        assert entry.needs_restart is not None
        assert entry.needs_restart.reason == "first reason"

    @pytest.mark.parametrize("to", [ResourceStatus.NOT_STARTED, ResourceStatus.STARTING, ResourceStatus.STOPPED])
    def test_non_failed_writes_to_a_flagged_entry_are_refused(
        self, registry: AppRegistry, app: MagicMock, to: ResourceStatus, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Only clear_all removes a flagged entry; a write that tries is a bug, so it logs a WARNING."""
        seed_failed(registry, APP_KEY, NAME, ValueError("hung"), needs_restart="work still running")

        with caplog.at_level(logging.WARNING):
            assert registry.set_status(APP_KEY, NAME, to, app=app) is None

        assert registry.get_needs_restart(APP_KEY, NAME) is not None
        assert any("flagged needs-restart" in r.getMessage() for r in caplog.records if r.levelname == "WARNING")

    def test_clear_all_removes_flagged_entries(self, registry: AppRegistry) -> None:
        seed_failed(registry, APP_KEY, NAME, ValueError("hung"), needs_restart="work still running")

        registry.clear_all()

        assert registry.get_needs_restart(APP_KEY, NAME) is None
        assert registry.flagged_app_keys() == []
