"""AppChangeReconcilerMixin — file-watcher and config-change detection and reconciliation."""

import asyncio
import typing
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from copy import deepcopy
from dataclasses import dataclass
from logging import Logger
from pathlib import Path

import hassette.event_handling.accessors as A
from hassette.core.app_change_detector import ChangeSet
from hassette.events.hassette import HassetteSimpleEvent
from hassette.exceptions import AppBlockedError, ConfigError
from hassette.types import Topic
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.config.classes import AppManifest
    from hassette.core.app_bootstrap_coordinator import AppBootstrapCoordinator
    from hassette.core.app_change_detector import AppChangeDetector
    from hassette.core.app_factory import AppFactory
    from hassette.core.app_key_lock import AppKeyLock
    from hassette.core.app_lifecycle_common import PendingReconciliation
    from hassette.core.app_registry import AppRegistry


@dataclass(frozen=True)
class AppRestart:
    """One app's part of a config or file change: which of its instances to stop and recreate."""

    app_key: str
    indices: tuple[int, ...] | None = None
    """The instance indices to restart, or None for every instance of the app."""
    force_reload: bool = False
    """Re-import the app class from disk before recreating (a file change)."""


class AppChangeReconcilerMixin:
    """File-watcher and config-change detection and reconciliation for ``AppLifecycleService``."""

    # Provided by the AppLifecycleService host (its own body, Resource, or a sibling mixin);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    registry: "AppRegistry"
    factory: "AppFactory"
    change_detector: "AppChangeDetector"
    bootstrap_coordinator: "AppBootstrapCoordinator"
    _change_event_lock: asyncio.Lock
    _pending_reconciliation: "PendingReconciliation | None"
    _get_app_key_lock: Callable[[str], "AppKeyLock"]
    _resolve_manifest: Callable[[str], "AppManifest | None"]
    _record_pre_release_reconciliation: Callable[..., None]
    _take_pre_release_reconciliation: Callable[
        [], tuple[dict[str, "AppManifest"] | None, dict[str, "AppManifest"] | None, frozenset[Path] | None]
    ]
    should_autostart: Callable[[str], bool]
    should_auto_reconcile: Callable[[str], bool]
    start_app: Callable[..., Awaitable[None]]
    stop_app: Callable[[str], Awaitable[None]]
    _start_app_unlocked: Callable[[str, "AppManifest", bool], Awaitable[None]]
    _stop_app_unlocked: Callable[[str], Awaitable[None]]
    _instance_index_in_range: Callable[[str, int, "AppManifest"], bool]
    _create_instance_unlocked: Callable[..., Awaitable[None]]
    _stop_instance_unlocked: Callable[[str, int], Awaitable[None]]
    persist_manifests: Callable[[], Awaitable[None]]
    set_apps_configs: Callable[[dict[str, "AppManifest"]], None]
    resolve_only_apps: Callable[[], Awaitable[None]]
    _fold_unblocked_apps_into_changes: Callable[[ChangeSet], ChangeSet]

    async def apply_changes(
        self,
        changes: ChangeSet,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
    ) -> None:
        """Apply detected changes by stopping, reloading, or starting apps.

        Precondition: the four change buckets are disjoint, as guaranteed by
        ``AppChangeDetector.detect_changes`` (orphans are keys absent from the
        current config; reimport/reload/new are all keys present in it). Orphans
        are processed first; a key in both ``orphans`` and a reload bucket would
        be stopped and then skipped. Callers constructing a ``ChangeSet`` by hand
        (e.g. tests) must keep the buckets disjoint.

        Args:
            changes: The set of changes to apply
            original_config: The app manifests before this change (used to diff per-instance
                ``app_config`` entries for the ``reload_apps`` bucket — see below)
            current_config: The app manifests after this change
        """
        self.logger.debug("Applying app changes: %s", changes)

        # AppBlockedError from the restarts and start_app() below is caught per app_key, even though it
        # should be structurally unreachable here: AppChangeDetector.detect_changes() filters every
        # ChangeSet bucket by only_apps before this method ever sees app_key, and
        # _fold_unblocked_apps_into_changes() only adds apps that were *just* unblocked. That
        # invariant spans three files and isn't enforced at this boundary, so if it's ever
        # violated, an uncaught raise here would abort every app after the blocked one.
        for app_key in changes.orphans:
            self.logger.debug("Stopping orphaned app %s", app_key)
            await self.stop_app(app_key)

        restarts = [
            *(
                AppRestart(app_key, force_reload=True)
                for app_key in changes.reimport_apps
                if self._should_restart(app_key)
            ),
            *(
                restart
                for app_key in changes.reload_apps
                if self._should_restart(app_key)
                and (restart := self._plan_reload(app_key, original_config, current_config)) is not None
            ),
        ]
        await self._restart_apps(restarts)

        for app_key in changes.new_apps:
            if not self.should_autostart(app_key):
                self.logger.debug("Skipping autostart of app %s (autostart=false)", app_key)
                continue

            self.logger.debug("Starting new app %s", app_key)
            try:
                await self.start_app(app_key)
            except AppBlockedError:
                self.logger.error("Skipping start of blocked app %s — this should not be reachable", app_key)

    def _should_restart(self, app_key: str) -> bool:
        if self.should_auto_reconcile(app_key):
            return True
        self.logger.debug("Skipping restart of autostart=false app %s (not running)", app_key)
        return False

    def _plan_reload(
        self,
        app_key: str,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
    ) -> "AppRestart | None":
        """Plan the restart a config change needs: only the instances whose ``app_config`` dict
        changed, or every instance when the app has none running (dormant), the instance count
        changed, or a manifest is missing on either side. None when no instance changed.

        A dormant app (no running instances) that reaches here via should_auto_reconcile
        (autostart just flipped to True) needs all instances created, not just the changed ones,
        or its unchanged siblings would stay unstarted.
        """
        old_manifest = original_config.get(app_key)
        new_manifest = current_config.get(app_key)
        if app_key not in self.registry or old_manifest is None or new_manifest is None:
            return AppRestart(app_key)

        old_instances = self.factory.normalize_configs(old_manifest.app_config)
        new_instances = self.factory.normalize_configs(new_manifest.app_config)
        if len(old_instances) != len(new_instances):
            self.logger.debug(
                "Instance count changed for app %s (%d -> %d) - reloading all instances",
                app_key,
                len(old_instances),
                len(new_instances),
            )
            return AppRestart(app_key)

        changed = tuple(i for i in range(len(new_instances)) if old_instances[i] != new_instances[i])
        if not changed:
            self.logger.debug("No per-instance config changes detected for app %s", app_key)
            return None
        return AppRestart(app_key, indices=changed)

    async def _restart_apps(self, restarts: list["AppRestart"]) -> None:
        """Stop every instance the restarts replace, then create every replacement.

        Bus/Scheduler owner registries are keyed by instance name, and a config change can hand a
        name from one instance to another, within one app or across apps (``a`` -> ``b`` while
        another instance goes ``b`` -> ``c``). Creating any replacement while the old holder of its
        name is still running would let the old one's teardown remove the new one's registrations,
        so nothing is created until everything being replaced has stopped.

        Every affected app-key lock is held across both phases, taken in sorted order so two
        callers can't deadlock, and released only after the last replacement is created.
        """
        if not restarts:
            return

        async with AsyncExitStack() as stack:
            for app_key in sorted({r.app_key for r in restarts}):
                await stack.enter_async_context(self._get_app_key_lock(app_key))

            for restart in restarts:
                await self._stop_for_restart(restart)
            for restart in restarts:
                await self._start_for_restart(restart)

    async def _stop_for_restart(self, restart: "AppRestart") -> None:
        # Both stop bodies catch and log their own failures, so one app's failed stop can't abort the batch.
        if restart.indices is None:
            self.logger.debug("Stopping app %s for reload", restart.app_key)
            await self._stop_app_unlocked(restart.app_key)
            return
        self.logger.debug("Stopping changed instance(s) %s of app %s", list(restart.indices), restart.app_key)
        await asyncio.gather(*(self._stop_instance_unlocked(restart.app_key, idx) for idx in restart.indices))

    async def _start_for_restart(self, restart: "AppRestart") -> None:
        # Re-resolved here, not when planned: the manifest can change while the locks were awaited.
        app_key = restart.app_key
        app_manifest = self._resolve_manifest(app_key)
        if not app_manifest:
            self.logger.warning("App %s has no manifest any more; not restarting it", app_key)
            return

        if restart.indices is None:
            try:
                await self._start_app_unlocked(app_key, app_manifest, restart.force_reload)
            except AppBlockedError:
                self.logger.error("Skipping reload of blocked app %s — this should not be reachable", app_key)
            except Exception:
                self.logger.error("Failed to reload app %s:\n%s", app_key, get_short_traceback())
            return

        async def create_one(idx: int) -> None:
            # A failure at one index must not abort the other indices, or the other apps in the batch.
            try:
                await self._create_instance_unlocked(app_key, idx, app_manifest)
            except Exception:
                self.logger.error("Failed to reload instance %d of app %s:\n%s", idx, app_key, get_short_traceback())

        valid = [idx for idx in restart.indices if self._instance_index_in_range(app_key, idx, app_manifest)]
        await asyncio.gather(*(create_one(idx) for idx in valid))

    async def handle_change_event(
        self,
        changed_file_paths: typing.Annotated[
            frozenset[Path] | None, A.get_path("payload.data.changed_file_paths")
        ] = None,
    ) -> None:
        """Handle changes detected by the file watcher.

        Called as a Bus event handler with DI-injected ``changed_file_paths``. Serialized by
        ``self._change_event_lock`` — this listener runs in the bus's ``parallel`` execution
        mode (framework tier), so two file-watcher events dispatched close together would
        otherwise run this method concurrently and race on ``_pending_reconciliation`` and on
        ``refresh_config()``'s in-place mutation of ``self.registry.manifests``.
        """
        async with self._change_event_lock:
            self.logger.debug("Handling app change event for files: %s", changed_file_paths)

            original_apps_config, current_apps_config = await self.refresh_config()
            await self.resolve_only_apps()

            if self.bootstrap_coordinator.is_released() and self._pending_reconciliation is not None:
                # A pre-release change is still queued. Fold it into this diff's baseline so the
                # comparison spans everything since before release, then clear the queue — otherwise
                # bootstrap's later replay would apply that stale snapshot on top of a config it no
                # longer matches (see integration review finding on stale pre-release replay).
                self.logger.debug("Merging queued pre-release reconciliation into post-release change")
                pending_original, _, pending_paths = self._take_pre_release_reconciliation()
                if pending_original is not None:
                    original_apps_config = pending_original
                    if pending_paths is None or changed_file_paths is None:
                        changed_file_paths = None
                    else:
                        changed_file_paths |= pending_paths

            changes = self.change_detector.detect_changes(
                original_apps_config, current_apps_config, changed_file_paths, only_apps=self.registry.only_apps
            )

            changes = self._fold_unblocked_apps_into_changes(changes)

            if not changes.has_any_change:
                self.logger.debug("%s changed but no app changes detected", changed_file_paths)
                return

            if not self.bootstrap_coordinator.is_released():
                if changes.has_changes:
                    self.logger.debug("Deferring app reconciliation until bootstrap release opens")
                    self._record_pre_release_reconciliation(
                        original_apps_config=original_apps_config,
                        current_apps_config=current_apps_config,
                        changed_file_paths=changed_file_paths,
                    )
                else:
                    # A metadata-only change (e.g. display_name) has nothing for apply_changes()
                    # to redo later, so there's no reconciliation to defer. But WebApiService can
                    # already be serving manifests to a connected dashboard before bootstrap
                    # release opens (see RuntimeQueryService.depends_on, which excludes
                    # AppHandler), and release may not open for a long time -- or at all -- while
                    # Home Assistant is unreachable. Broadcast now via _reconcile_changes(), which
                    # skips apply_changes() since changes.has_changes is False here.
                    self.logger.debug("%s changed (metadata-only) before bootstrap release opened", changed_file_paths)
                    await self._reconcile_changes(changes, original_apps_config, current_apps_config)
                return

            self.logger.debug("%s changed, app changes detected - %s", changed_file_paths, changes)
            await self._reconcile_changes(changes, original_apps_config, current_apps_config)

    async def refresh_config(self) -> tuple[dict[str, "AppManifest"], dict[str, "AppManifest"]]:
        """Reload the configuration and return (original_apps_config, current_apps_config).

        Both dicts include every manifest regardless of `enabled` status -- not filtered here,
        and not by the exclusive-app filter either, so both configs stay directly comparable.
        `AppChangeDetector.detect_changes()` derives its own enabled-only view internally for
        lifecycle actions, but needs the full picture to also catch a metadata-only change to
        an app that's disabled on both sides (see `ChangeSet.metadata_apps`).
        """
        original_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items()}
        try:  # reload() swaps in only a valid config: on failure, config and registry stay as they are
            self.hassette.config.reload()
        except Exception as exc:  # an invalid config on disk (ConfigError) needs no traceback; a bug does
            self.logger.error("Config reload rejected: %s", exc, exc_info=not isinstance(exc, ConfigError))
            return original_apps_config, {k: deepcopy(v) for k, v in original_apps_config.items()}

        self.set_apps_configs(self.hassette.config.apps.manifests)
        await self.persist_manifests()
        current_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items()}

        return original_apps_config, current_apps_config

    async def _replay_pre_release_reconciliation_if_needed(self) -> bool:
        """Replay a deferred pre-release reconciliation, if one is queued.

        Returns:
            True if a queued reconciliation was replayed and broadcast a manifest-refetch
            signal via ``_reconcile_changes`` -- callers that send their own unconditional
            "bootstrap finished" broadcast afterward should skip it when this returns True,
            or the same signal goes out twice for one bootstrap pass.
        """
        # Shares _pending_reconciliation state with handle_change_event(), which serializes on
        # this same lock — without it, a file-watcher event arriving as bootstrap replays could
        # race the take/clear of that state.
        async with self._change_event_lock:
            if self._pending_reconciliation is None:
                return False

            original_apps_config, current_apps_config, changed_file_paths = self._take_pre_release_reconciliation()
            if original_apps_config is None or current_apps_config is None:
                return False
            self.logger.debug("Replaying deferred app reconciliation after bootstrap release opens")
            await self.resolve_only_apps()

            changes = self.change_detector.detect_changes(
                original_apps_config, current_apps_config, changed_file_paths, only_apps=self.registry.only_apps
            )

            changes = self._fold_unblocked_apps_into_changes(changes)

            if not changes.has_any_change:
                self.logger.debug("Deferred app reconciliation produced no changes")
                return False

            await self._reconcile_changes(changes, original_apps_config, current_apps_config)
            return True

    async def _reconcile_changes(
        self,
        changes: ChangeSet,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
    ) -> None:
        """Apply a non-empty ``ChangeSet`` and broadcast a manifest-refetch signal.

        The single place ``handle_change_event()`` and
        ``_replay_pre_release_reconciliation_if_needed()`` route every ``ChangeSet``-driven
        apply-then-broadcast decision through, rather than hand-rolling it at each call site's
        own terminal branch -- a new branch that calls ``apply_changes()``/``send_event()``
        directly instead of through here risks reintroducing the class of gap where one branch
        applies changes (or persists metadata) but forgets to broadcast. Callers must already
        have confirmed ``changes.has_any_change`` before calling. This is distinct from
        ``bootstrap_apps()``'s own unconditional "bootstrap sequence finished" broadcast, which
        isn't driven by a ``ChangeSet`` and stays a direct ``send_event()`` call there.
        """
        if changes.has_changes:
            await self.apply_changes(changes, original_config, current_config)

        await self.hassette.send_event(
            HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
        )
