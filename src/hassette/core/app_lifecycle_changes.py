"""AppChangeReconcilerMixin — file-watcher and config-change detection and reconciliation."""

import asyncio
import typing
from collections.abc import Awaitable, Callable
from copy import deepcopy
from logging import Logger
from pathlib import Path

import hassette.event_handling.accessors as A
from hassette.core.app_change_detector import ChangeSet
from hassette.events.hassette import HassetteSimpleEvent
from hassette.exceptions import AppBlockedError
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
    reload_app: Callable[..., Awaitable[None]]
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

        # AppBlockedError from reload_app()/start_app()/_reload_app_or_changed_instances()
        # below is caught per app_key in every loop, even though it should be structurally
        # unreachable here: AppChangeDetector.detect_changes() filters every ChangeSet bucket
        # by only_apps before this method ever sees app_key, and
        # _fold_unblocked_apps_into_changes() only adds apps that were *just* unblocked. That
        # invariant spans three files and isn't enforced at this boundary, so if it's ever
        # violated, an uncaught raise here would abort the rest of this bucket and every
        # bucket after it — not just the one blocked app_key.
        for app_key in changes.orphans:
            self.logger.debug("Stopping orphaned app %s", app_key)
            await self.stop_app(app_key)

        for app_key in changes.reimport_apps:
            if not self.should_auto_reconcile(app_key):
                self.logger.debug("Skipping reimport of autostart=false app %s (not running)", app_key)
                continue

            self.logger.debug("Reloading app %s due to file change", app_key)
            try:
                await self.reload_app(app_key, force_reload=True)
            except AppBlockedError:
                self.logger.error("Skipping reimport of blocked app %s — this should not be reachable", app_key)

        for app_key in changes.reload_apps:
            if not self.should_auto_reconcile(app_key):
                self.logger.debug("Skipping reload of autostart=false app %s (not running)", app_key)
                continue

            try:
                await self._reload_app_or_changed_instances(app_key, original_config, current_config)
            except AppBlockedError:
                self.logger.error("Skipping reload of blocked app %s — this should not be reachable", app_key)

        for app_key in changes.new_apps:
            if not self.should_autostart(app_key):
                self.logger.debug("Skipping autostart of app %s (autostart=false)", app_key)
                continue

            self.logger.debug("Starting new app %s", app_key)
            try:
                await self.start_app(app_key)
            except AppBlockedError:
                self.logger.error("Skipping start of blocked app %s — this should not be reachable", app_key)

    async def _reload_app_or_changed_instances(
        self,
        app_key: str,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
    ) -> None:
        """Reload only the instances whose ``app_config`` dict changed, or fall back to a full
        app-key reload when the app has no running instances (dormant), the instance list length
        changed, or a name collision would occur (see design doc "Data flow for selective restart").

        A missing entry on either side of ``original_config``/``current_config`` (should not
        happen for a key already in ``changes.reload_apps``, but config snapshots are caller-
        supplied) falls back to a full reload rather than raising.
        """
        # A dormant app (no running instances) that reaches here via should_auto_reconcile
        # (autostart just flipped to True) needs all instances created, not just the ones whose
        # app_config changed. The selective path only creates changed indices, permanently
        # leaving unchanged siblings unstarted.
        if app_key not in self.registry:
            self.logger.debug("App %s has no running instances - starting all via full reload", app_key)
            await self.reload_app(app_key)
            return

        old_manifest = original_config.get(app_key)
        new_manifest = current_config.get(app_key)
        if old_manifest is None or new_manifest is None:
            self.logger.debug("Reloading app %s due to config change", app_key)
            await self.reload_app(app_key)
            return

        old_instances = self.factory.normalize_configs(old_manifest.app_config)
        new_instances = self.factory.normalize_configs(new_manifest.app_config)

        if len(old_instances) != len(new_instances):
            self.logger.debug(
                "Instance count changed for app %s (%d -> %d) - reloading all instances",
                app_key,
                len(old_instances),
                len(new_instances),
            )
            await self.reload_app(app_key)
            return

        changed_indices = [i for i in range(len(new_instances)) if old_instances[i] != new_instances[i]]
        if not changed_indices:
            self.logger.debug("No per-instance config changes detected for app %s", app_key)
            return

        # A changed index can adopt an instance_name that an *unchanged* sibling still holds —
        # e.g. index 0's instance_name changes A -> B while index 1's instance_name stays B (see
        # PR #1687 review finding, filed against the stop-all/create-all fix above). Neither this
        # method's changed_indices computation nor _reload_changed_indices' batch reload ever
        # looks at indices outside the batch, so index 1 is never touched: after the batch
        # reload, index 0 (now "B") and index 1 (still "B") both exist and both derive the same
        # App.unique_name, permanently sharing one entry in the Bus/Scheduler owner-keyed
        # registries. instance_name uniqueness within one app_key's app_config is not enforced
        # anywhere at config-validation time (see config/classes.py's validate_app_config, which
        # only fills in a *missing* instance_name — it never checks for duplicates), so this
        # overlap is not something we can reject as an invalid config: the new config is valid on
        # its own, it only conflicts with the *currently running* old config during the
        # transition. Detect the overlap here and fall back to a full app reload, which stops
        # every instance (including untouched ones) before recreating any of them.
        changed_set = set(changed_indices)
        unchanged_names = {old_instances[i]["instance_name"] for i in range(len(old_instances)) if i not in changed_set}
        new_names_list = [new_instances[i]["instance_name"] for i in changed_set]
        new_names = set(new_names_list)
        overlap = unchanged_names & new_names
        if overlap:
            self.logger.debug(
                "Changed instance(s) of app %s would adopt instance_name(s) %s still held by an "
                "unchanged sibling instance - reloading all instances to avoid a name collision",
                app_key,
                sorted(overlap),
            )
            await self.reload_app(app_key)
            return

        # Two *changed* indices can also adopt the same new instance_name from each other --
        # e.g. index 0: a -> c, index 1: b -> c. No unchanged sibling holds "c", so the check
        # above sees no overlap, but _reload_changed_indices' create-all phase would still
        # create two live instances both deriving App.unique_name "c", the same permanent
        # owner-registry collision as the unchanged-sibling case. `new_names` (a set) silently
        # collapses such duplicates, so compare its length against the changed-index count
        # rather than checking membership.
        if len(new_names) != len(new_names_list):
            self.logger.debug(
                "Changed instance(s) of app %s would collide on a shared new instance_name - "
                "reloading all instances to avoid a name collision",
                app_key,
            )
            await self.reload_app(app_key)
            return

        await self._reload_changed_indices(app_key, changed_indices)

    async def _reload_changed_indices(self, app_key: str, changed_indices: list[int]) -> None:
        """Reload the given instance indices of ``app_key`` under one lock, stopping every
        affected index before creating any replacement.

        Extracted from ``_reload_app_or_changed_instances`` — see that method for the fallback
        cases (missing manifest, instance-count changed) that precede this batch reload.

        Split into a stop-all phase followed by a create-all phase (rather than reloading each
        index fully concurrently, stop-then-create) — see PR #1687 review finding. A batch that
        renames multiple instances can make a *new* instance take an ``instance_name`` (and
        therefore ``App.unique_name``/owner_id) still held by *another* instance in the same
        batch — e.g. index 0's ``instance_name`` changes ``A`` -> ``B`` while index 1's changes
        ``B`` -> ``C``. Bus/Scheduler owner registries (``BusService.router``,
        ``BusService._removal_callbacks``, the equivalent Scheduler structures) are keyed by that
        name string alone, not by ``(app_key, index)``. Interleaving each index's stop-then-create
        concurrently (the previous ``asyncio.gather`` over full per-index reloads) could let index
        0's new "B" register its listeners/jobs/removal-callback before index 1's old "B" finished
        tearing down — the old teardown would then rip out the new instance's freshly-registered
        state, since both are indistinguishable by owner_id alone. Stopping every affected index
        first (nothing new has been registered yet, so no create can collide with an in-flight
        stop) and only then creating replacements eliminates the interleaving hazard structurally,
        regardless of which names overlap or in which order — no overlap detection needed.
        """
        self.logger.debug("Reloading changed instance(s) %s of app %s", changed_indices, app_key)

        app_manifest = self._resolve_manifest(app_key)
        if not app_manifest:
            return

        valid_indices = [idx for idx in changed_indices if self._instance_index_in_range(app_key, idx, app_manifest)]
        if not valid_indices:
            return

        async def _create_one(idx: int) -> None:
            # Per-index try/except, mirroring the previous _reload_one() guard — a failure at
            # one index must not abort the remaining indices in this batch, nor the caller's
            # loop over other app_keys in apply_changes() (see code review finding).
            try:
                await self._create_instance_unlocked(app_key, idx, app_manifest)
            except Exception:
                self.logger.error("Failed to reload instance %d of app %s:\n%s", idx, app_key, get_short_traceback())

        # Single lock acquisition for the whole batch — reload_instance() also acquires this
        # lock, so calling it per-index here (instead of the unlocked body) would deadlock on
        # the non-reentrant asyncio.Lock on the second index. Instances of the same app_key
        # share no mutable state (each owns its own Bus/Scheduler/StateManager/Api/AsyncCache —
        # see design.md "Dependencies and Assumptions"), so each phase runs concurrently within
        # itself. This bounds the lock's hold time at roughly two instances' timeouts (one stop
        # phase plus one create phase) instead of N — looser than the previous single-phase
        # claim of "one instance's timeout," but still far short of a fully sequential N-instance
        # bound, and necessary to close the name-collision race described above.
        #
        # _stop_instance_unlocked already wraps its own body in try/except (see its docstring),
        # so a stop failure at one index is isolated and logged there without needing a guard
        # here too — unlike the create phase below, which needs its own per-index try/except.
        async with self._get_app_key_lock(app_key):
            await asyncio.gather(*(self._stop_instance_unlocked(app_key, idx) for idx in valid_indices))
            await asyncio.gather(*(_create_one(idx) for idx in valid_indices))

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

        # Reinitialize config to pick up changes.
        # https://docs.pydantic.dev/latest/concepts/pydantic_settings/#in-place-reloading
        try:
            self.hassette.config.reload()
        except Exception as exc:
            self.logger.exception("Failed to reload configuration: %s", exc)

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
