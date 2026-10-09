"""AppConfigStateMixin — manifest persistence, config installation, and the ``--app`` exclusive filter."""

import asyncio
import typing
from copy import deepcopy
from logging import Logger

import anyio

from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_common import MANIFEST_UPSERT_TIMEOUT_SECONDS
from hassette.types.enums import BlockReason

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.config.classes import AppManifest
    from hassette.core.app_registry import AppRegistry


class AppConfigStateMixin:
    """Manifest persistence, config installation, and the ``--app`` exclusive filter for ``AppLifecycleService``."""

    # Provided by the AppLifecycleService host (its own body, Resource, or a sibling mixin);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    registry: "AppRegistry"

    async def persist_manifests(self) -> None:
        """Upsert all current manifests into the ``app_manifests`` DB table concurrently.

        Called from ``bootstrap_apps()`` (initial load, after ``set_apps_configs()`` and before
        ``start_apps()``) and ``refresh_config()`` (hot reload, after ``set_apps_configs()`` and
        before ``apply_changes()`` in the caller). Manifests are upserted concurrently via
        ``asyncio.gather(return_exceptions=True)``, matching ``start_apps()`` — a sequential loop
        here would serialize up to ``N * MANIFEST_UPSERT_TIMEOUT_SECONDS`` onto every boot and
        hot-reload if the DB is merely slow rather than down. Each upsert still has its own
        ``anyio.fail_after()`` timeout and try/except (see ``persist_manifest()``), so one app's
        failure never affects another's, and a failed write is self-correcting on the next
        successful write. This must never block app startup or a config reload.
        """
        manifests = self.registry.manifests
        self.logger.debug("Persisting %d manifest(s) to the app_manifests table", len(manifests))
        await asyncio.gather(
            *(self.persist_manifest(app_key, manifest) for app_key, manifest in manifests.items()),
            return_exceptions=True,
        )
        self.logger.debug("Finished persisting manifests")

    async def persist_manifest(self, app_key: str, manifest: "AppManifest") -> None:
        """Upsert a single manifest, isolating its own timeout and failure from the batch.

        Never raises — a timeout or a genuine write failure is logged and swallowed so that
        one app's persistence problem can't affect any other app's, whether called from the
        ``persist_manifests()`` batch or directly for a single app.
        """
        try:
            with anyio.fail_after(MANIFEST_UPSERT_TIMEOUT_SECONDS):
                await self.hassette.command_executor.upsert_app_manifest(manifest)
        except TimeoutError:
            # This timeout only cancels our wait on `DatabaseService`'s write queue — the
            # single-writer worker task isn't inside this scope, so the write may still land
            # moments after we give up on it. Unlike a genuine write failure, "timed out"
            # doesn't mean the write didn't happen.
            self.logger.warning(
                "Timed out waiting for manifest persist for app '%s' — write may still complete "
                "in the background; dashboard metadata may be stale until the next successful write",
                app_key,
            )
        except Exception:
            self.logger.warning(
                "Failed to persist manifest for app '%s' — dashboard metadata may be stale "
                "until the next successful write",
                app_key,
                exc_info=True,
            )

    def set_apps_configs(self, apps_config: dict[str, "AppManifest"]) -> None:
        """Set the apps configuration.

        Args:
            apps_config: The new apps configuration.
        """
        self.logger.debug("Setting apps configuration")
        self.registry.set_manifests(deepcopy(apps_config))
        self.registry.set_only_apps(())  # reset the filter, it is recomputed on next initialize

        self.logger.debug(
            "Found %d apps in configuration: %s", len(self.registry.manifests), list(self.registry.manifests.keys())
        )

    async def resolve_only_apps(self) -> None:
        """Apply the ``--app`` exclusive-app filter, if given."""
        requested = set(self.hassette.config.only_apps)
        if not requested:
            return

        known = requested & set(self.registry.enabled_manifests)
        unknown = requested - known
        if unknown:
            self.logger.error(
                "No enabled app matches --app key(s) %s; enabled apps are: %s",
                ", ".join(sorted(unknown)),
                ", ".join(sorted(self.registry.enabled_manifests)) or "(none)",
            )
        if known:
            self.logger.warning("Running only %s, skipping all other apps", ", ".join(sorted(known)))

        # Deliberately `requested`, not `known` — narrowing to `known` would turn an all-typo
        # request into an empty filter, which means "no filter" and starts every app.
        self.registry.set_only_apps(requested)

    def _fold_unblocked_apps_into_changes(self, changes: ChangeSet) -> ChangeSet:
        """Reconcile blocked-app state and fold any newly-unblocked apps into ``changes`` as starts.

        Shared by ``handle_change_event()`` and ``_replay_pre_release_reconciliation_if_needed()``,
        both of which reconcile the ``--app`` filter's blocked-app state against the current
        registry before applying detected changes.
        """
        unblocked = self.reconcile_blocked_apps()
        to_start = unblocked - set(self.registry.app_keys()) - changes.new_apps - changes.reimport_apps
        if not to_start:
            return changes
        self.logger.debug("Starting previously-blocked apps: %s", to_start)
        return ChangeSet(
            orphans=changes.orphans,
            new_apps=changes.new_apps | frozenset(to_start),
            reimport_apps=changes.reimport_apps,
            reload_apps=changes.reload_apps - to_start,
            metadata_apps=changes.metadata_apps,
        )

    def reconcile_blocked_apps(self) -> set[str]:
        """Synchronize blocked state with the current exclusive-app filter.

        Returns:
            App keys that were unblocked (previously blocked but no longer).
        """
        previously_blocked = self.registry.unblock_apps(BlockReason.ONLY_APP)

        currently_blocked: set[str] = set()
        if self.registry.only_apps:
            for app_key in self.registry.enabled_manifests:
                if app_key not in self.registry.only_apps:
                    self.registry.block_app(app_key, BlockReason.ONLY_APP)
                    currently_blocked.add(app_key)

        return previously_blocked - currently_blocked
