"""Unit tests for AppLifecycleService — reconciliation, config, and manifest persistence.

Part of the AppLifecycleService unit-test family (``test_app_lifecycle_service*.py``);
shared fixtures live in ``_fixtures_app_lifecycle.py`` via ``conftest.py``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.types.enums import BlockReason


class TestReconcileBlockedApps:
    def test_blocks_non_only_apps(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Blocks all apps except the ones in the exclusive-app filter."""
        mock_registry.only_apps = frozenset({"app_a"})
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock(), "app_c": MagicMock()}
        mock_registry.unblock_apps = Mock(return_value=set())

        lifecycle_service.reconcile_blocked_apps()

        block_calls = mock_registry.block_app.call_args_list
        blocked_keys = {call[0][0] for call in block_calls}
        assert blocked_keys == {"app_b", "app_c"}
        for call in block_calls:
            assert call[0][1] == BlockReason.ONLY_APP

    def test_keeps_every_app_in_a_multi_key_filter(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """`--app a --app b` blocks only the apps outside the filter."""
        mock_registry.only_apps = frozenset({"app_a", "app_b"})
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock(), "app_c": MagicMock()}
        mock_registry.unblock_apps = Mock(return_value=set())

        lifecycle_service.reconcile_blocked_apps()

        blocked_keys = {call[0][0] for call in mock_registry.block_app.call_args_list}
        assert blocked_keys == {"app_c"}

    def test_unblocks_when_only_apps_cleared(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Unblocks previously blocked apps when the exclusive-app filter is empty."""
        mock_registry.only_apps = frozenset()
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock()}
        mock_registry.unblock_apps = Mock(return_value={"app_b"})

        result = lifecycle_service.reconcile_blocked_apps()

        mock_registry.unblock_apps.assert_called_once_with(BlockReason.ONLY_APP)
        mock_registry.block_app.assert_not_called()
        assert result == {"app_b"}


class TestResolveOnlyApps:
    async def test_config_keys_set_the_filter(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Every requested key that names an enabled app becomes the filter."""
        mock_hassette.config.only_apps = ("app_a", "app_b")
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock(), "app_c": MagicMock()}

        await lifecycle_service.resolve_only_apps()

        mock_registry.set_only_apps.assert_called_with({"app_a", "app_b"})

    async def test_unknown_key_still_filters_everything_out(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """A mistyped key matches no app rather than silently starting all of them."""
        mock_hassette.config.only_apps = ("app_typo",)
        mock_registry.enabled_manifests = {"app_a": MagicMock()}

        await lifecycle_service.resolve_only_apps()

        mock_registry.set_only_apps.assert_called_with({"app_typo"})

    async def test_honored_in_prod_mode(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """The --app flag works in both dev and production mode."""
        mock_hassette.config.dev_mode = False
        mock_hassette.config.only_apps = ("app_a",)
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock()}

        await lifecycle_service.resolve_only_apps()

        mock_registry.set_only_apps.assert_called_with({"app_a"})


class TestRefreshConfig:
    async def test_reloads_config_and_returns_before_after(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """Calls config.reload() and returns original and current manifests."""
        manifest1 = MagicMock()
        manifest1.enabled = True
        mock_registry.manifests = {"app_a": manifest1}
        mock_hassette.config.apps.manifests = {"app_a": manifest1}
        reload_mock = Mock()
        object.__setattr__(mock_hassette.config, "reload", reload_mock)

        original, current = await lifecycle_service.refresh_config()

        reload_mock.assert_called_once()
        assert "app_a" in original
        assert "app_a" in current


class TestReconcileAppRegistrations:
    """Tests for reconcile_app_registrations — the post-ready reconciliation helper."""

    async def test_reconcile_calls_reconcile_registrations(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_app_instance: AsyncMock,
    ) -> None:
        """reconcile_registrations() is called with live IDs after barriers complete."""
        instances = {0: mock_app_instance}
        await lifecycle_service.reconcile_app_registrations("test_app", instances)

        mock_hassette.command_executor.reconcile_registrations.assert_awaited_once()
        call_kwargs = mock_hassette.command_executor.reconcile_registrations.call_args
        assert call_kwargs.args[0] == "test_app"

    async def test_reconcile_failure_does_not_raise(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_app_instance: AsyncMock,
    ) -> None:
        """Reconciliation failure is swallowed — does not propagate to caller."""
        mock_hassette.command_executor.reconcile_registrations = AsyncMock(side_effect=RuntimeError("DB full"))

        instances = {0: mock_app_instance}

        await lifecycle_service.reconcile_app_registrations("test_app", instances)


class TestSetAppsConfigs:
    def test_sets_manifests_on_registry(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls registry.set_manifests with the provided config."""
        manifests = {"app_a": MagicMock()}

        lifecycle_service.set_apps_configs(manifests)

        mock_registry.set_manifests.assert_called_once()
        mock_registry.set_only_apps.assert_called_with(())


class TestPersistManifests:
    """Tests for persist_manifests() — the per-item-isolated manifest upsert trigger."""

    async def test_upserts_every_manifest_in_registry(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """Calls command_executor.upsert_app_manifest once per manifest currently in the registry."""
        manifest_a = MagicMock()
        manifest_b = MagicMock()
        mock_registry.manifests = {"app_a": manifest_a, "app_b": manifest_b}
        mock_hassette.command_executor.upsert_app_manifest = AsyncMock()

        await lifecycle_service.persist_manifests()

        mock_hassette.command_executor.upsert_app_manifest.assert_any_call(manifest_a)
        mock_hassette.command_executor.upsert_app_manifest.assert_any_call(manifest_b)
        assert mock_hassette.command_executor.upsert_app_manifest.await_count == 2

    async def test_one_failure_does_not_block_remaining_upserts(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """A failed upsert is isolated — the remaining manifests still get persisted, and the
        failure never propagates out of persist_manifests() to the bootstrap/reload caller.
        """
        manifest_a = MagicMock()
        manifest_b = MagicMock()
        mock_registry.manifests = {"app_a": manifest_a, "app_b": manifest_b}
        mock_hassette.command_executor.upsert_app_manifest = AsyncMock(side_effect=[RuntimeError("DB full"), 1])

        await lifecycle_service.persist_manifests()

        assert mock_hassette.command_executor.upsert_app_manifest.await_count == 2

    async def test_upserts_run_concurrently_not_sequentially(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """A sequential loop would hang here: each upsert only returns once *both* are in
        flight, so a sequential implementation would await the first call forever — surfaced
        by `asyncio.wait_for` below as a `TimeoutError` rather than an actual hang. Deterministic
        per CLAUDE.md's startup-race pattern — no sleep-based timing races.
        """
        both_in_flight = asyncio.Event()
        in_flight_count = 0

        async def blocking_upsert(_manifest: object) -> None:
            nonlocal in_flight_count
            in_flight_count += 1
            if in_flight_count == 2:
                both_in_flight.set()
            await both_in_flight.wait()

        mock_registry.manifests = {"app_a": MagicMock(), "app_b": MagicMock()}
        mock_hassette.command_executor.upsert_app_manifest = AsyncMock(side_effect=blocking_upsert)

        await asyncio.wait_for(lifecycle_service.persist_manifests(), timeout=1)

        assert in_flight_count == 2
