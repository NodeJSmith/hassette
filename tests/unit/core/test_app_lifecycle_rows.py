"""App status and block lifecycle rows, written by their owners.

Spec 152 D1 (a row per StatusChange, written in set_app_status before the event send), D2 (no writer-side
dedupe) and D3 (block rows diffed inside reconcile_blocked_apps).
"""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from hassette_wire import ResourceStatus

import hassette.core.app_lifecycle_config as config_module
import hassette.core.app_lifecycle_instances as instances_module
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import StatusChange
from hassette.types.enums import BlockReason

from .conftest import make_app_instance, make_manifest_obj

APP_KEY = "porch"


@pytest.fixture
def app_rows(monkeypatch: pytest.MonkeyPatch) -> list[StatusChange]:
    captured: list[StatusChange] = []
    monkeypatch.setattr(instances_module, "record_app_change", lambda _hassette, change: captured.append(change))
    return captured


@pytest.fixture
def block_rows(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    captured: list[tuple[str, str]] = []

    def record(_hassette: object, app_key: str, to_status: str, reason: BlockReason) -> None:
        assert reason is BlockReason.ONLY_APP
        captured.append((app_key, to_status))

    monkeypatch.setattr(config_module, "record_block_change", record)
    return captured


class TestAppStatusRows:
    async def test_each_change_writes_a_row_and_a_non_change_writes_none(
        self, real_registry_service: AppLifecycleService, app_rows: list[StatusChange]
    ) -> None:
        app = make_app_instance(APP_KEY, "main")
        await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.NOT_STARTED, app=app)
        await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.STARTING)
        await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.STARTING)

        assert [(c.previous, c.status) for c in app_rows] == [(ResourceStatus.NOT_STARTED, ResourceStatus.STARTING)]

    async def test_repeat_failure_with_a_new_error_writes_a_row_each(
        self, real_registry_service: AppLifecycleService, app_rows: list[StatusChange]
    ) -> None:
        """No writer-side dedupe: the registry says a new error object is a change, so it is a row."""
        await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.FAILED, error=ValueError("a"))
        await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.FAILED, error=ValueError("a"))

        assert [c.status for c in app_rows] == [ResourceStatus.FAILED, ResourceStatus.FAILED]

    async def test_row_is_written_before_the_send_and_survives_a_failed_send(
        self, real_registry_service: AppLifecycleService, app_rows: list[StatusChange]
    ) -> None:
        app_rows_before_send: list[int] = []

        async def failing_send(_event: object) -> None:
            app_rows_before_send.append(len(app_rows))
            raise RuntimeError("bus closed")

        real_registry_service.hassette.send_event = AsyncMock(side_effect=failing_send)
        real_registry_service.logger = Mock()

        await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.FAILED, error=ValueError("x"))

        assert app_rows_before_send == [1]
        assert [c.status for c in app_rows] == [ResourceStatus.FAILED]


class TestBlockRows:
    @staticmethod
    def configure(service: AppLifecycleService, *, enabled: set[str], only: set[str]) -> None:
        registry = service.registry
        registry.set_manifests({key: make_manifest_obj(key) for key in enabled})
        registry.set_only_apps(frozenset(only))

    def test_bootstrap_writes_a_blocked_row_per_blocked_app(
        self, real_registry_service: AppLifecycleService, block_rows: list[tuple[str, str]]
    ) -> None:
        self.configure(real_registry_service, enabled={"a", "b", "c"}, only={"a"})

        real_registry_service.reconcile_blocked_apps()

        assert block_rows == [("b", "blocked"), ("c", "blocked")]

    def test_an_unchanged_block_writes_nothing(
        self, real_registry_service: AppLifecycleService, block_rows: list[tuple[str, str]]
    ) -> None:
        self.configure(real_registry_service, enabled={"a", "b"}, only={"a"})
        real_registry_service.reconcile_blocked_apps()
        block_rows.clear()

        real_registry_service.reconcile_blocked_apps()

        assert block_rows == []

    def test_clearing_the_filter_unblocks_and_a_disabled_app_is_removed(
        self, real_registry_service: AppLifecycleService, block_rows: list[tuple[str, str]]
    ) -> None:
        self.configure(real_registry_service, enabled={"a", "b", "c"}, only={"a"})
        real_registry_service.reconcile_blocked_apps()
        block_rows.clear()

        self.configure(real_registry_service, enabled={"a", "b"}, only=set())
        left = real_registry_service.reconcile_blocked_apps()

        assert block_rows == [("b", "unblocked"), ("c", "removed")]
        assert left == {"b", "c"}  # the return value still includes removed apps


def test_mock_registry_service_still_reconciles(
    lifecycle_service: AppLifecycleService, mock_registry: MagicMock, block_rows: list[tuple[str, str]]
) -> None:
    """A removed app is told apart by enabled_manifests at reconcile time, not by the caller."""
    mock_registry.only_apps = frozenset()
    mock_registry.enabled_manifests = {"a": MagicMock()}
    mock_registry.unblock_apps = Mock(return_value={"a", "gone"})

    assert lifecycle_service.reconcile_blocked_apps() == {"a", "gone"}
    assert block_rows == [("a", "unblocked"), ("gone", "removed")]
