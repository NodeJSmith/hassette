"""AppReconcilePlannerMixin — reads the config and app files from disk and plans what a reconcile changes.

``reconcile_from_disk`` is the one entry point for a file-watcher event and a manual reload-all. It builds the
candidate config, detects the changes, plans any reload-all, and hands the result to ``apply_changes``
(``AppChangeApplierMixin`` in ``app_lifecycle_changes``), which stops, evicts, recreates and starts the apps.
Each app's own restart decision is made there, once its lock is held. ``config_error_summary`` below
formats an invalid config's errors for a refusal.
"""

import asyncio
import functools
import sys
import time
import typing
from collections.abc import Awaitable, Callable
from copy import deepcopy
from logging import Logger
from pathlib import Path

from pydantic import ValidationError

import hassette.event_handling.accessors as A
from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_common import ManualReload, ReconcileTrigger, ReloadAllPlan, WatcherTrigger
from hassette.events.hassette import HassetteSimpleEvent
from hassette.exceptions import (
    AppBootstrapNotReleasedError,
    ConfigError,
    ReloadBusyError,
    ReloadConfigInvalidError,
    ReloadSyntaxError,
)
from hassette.schemas.app_outcomes import OutcomeResult, ReconcileResult
from hassette.types import Topic
from hassette.utils.app_modules import app_roots, describe_syntax_error, needs_reload_all, precheck_apps_package
from hassette.utils.exception_utils import validation_error_summary

if typing.TYPE_CHECKING:
    from hassette import Hassette, HassetteConfig
    from hassette.config.classes import AppManifest
    from hassette.core.app_bootstrap_coordinator import AppBootstrapCoordinator
    from hassette.core.app_change_detector import AppChangeDetector
    from hassette.core.app_key_lock import AppKeyLock
    from hassette.core.app_lifecycle_common import PendingReconciliation
    from hassette.core.app_registry import AppRegistry


class AppReconcilePlannerMixin:
    """Reconciliation from disk for ``AppLifecycleService``: what a watcher event or a reload-all changes."""

    # Provided by the AppLifecycleService host (its own body, Resource, or a sibling mixin);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    registry: "AppRegistry"
    change_detector: "AppChangeDetector"
    bootstrap_coordinator: "AppBootstrapCoordinator"
    _reconcile_lock: "AppKeyLock"
    _pending_reconciliation: "PendingReconciliation | None"
    _get_app_key_lock: Callable[[str], "AppKeyLock"]
    _record_pre_release_reconciliation: Callable[..., None]
    _take_pre_release_reconciliation: Callable[
        [], tuple[dict[str, "AppManifest"] | None, dict[str, "AppManifest"] | None, frozenset[Path]]
    ]
    apply_changes: Callable[..., Awaitable[ReconcileResult]]
    persist_manifests: Callable[[], Awaitable[None]]
    set_apps_configs: Callable[[dict[str, "AppManifest"]], None]
    resolve_only_apps: Callable[[], Awaitable[None]]
    _fold_unblocked_apps_into_changes: Callable[[ChangeSet], ChangeSet]

    async def handle_change_event(
        self,
        changed_file_paths: typing.Annotated[frozenset[Path], A.get_path("payload.data.changed_file_paths")],
    ) -> None:
        """Handle changes detected by the file watcher, through ``reconcile_from_disk``.

        Called as a Bus event handler with DI-injected ``changed_file_paths``. This listener runs in the bus's
        ``parallel`` execution mode (framework tier), so two events dispatched close together are serialized by
        ``reconcile_from_disk``'s reconcile lock rather than by the bus.
        """
        await self.reconcile_from_disk(WatcherTrigger(changed_file_paths))

    async def reconcile_from_disk(self, trigger: ReconcileTrigger) -> ReconcileResult:
        """Re-read the config and app files from disk and bring the running apps in line with them.

        The one entry point for a file-watcher event and a manual reload-all. In order (spec 162 D12):

        0. Take the reconcile lock. A manual call that mustn't wait refuses if it's busy.
        1. A manual call before bootstrap release refuses. A watcher event before release commits the config and
           queues its lifecycle work for bootstrap's replay.
        2. Build a candidate config, committing nothing. An invalid one refuses a manual call; a watcher
           event logs it and reconciles against the current config with no reload-all.
        3. Detect the changes, then plan the reload-all (``_plan_reload_all``): always for a manual call, from the
           changed paths for a watcher event. A reload-all runs the syntax precheck first, which refuses a manual
           call; a watcher event logs it and drops only the reload-all part.
        4. ``apply_changes``: take the restart and orphan locks, adopt the candidate, stop, evict, create, and
           start the new apps.

        Every refusal comes before anything is committed or stopped.

        Returns:
            What the reconcile did to each app; empty when it found nothing to apply.

        Raises:
            ReloadBusyError: A manual call with ``wait`` false found another reload, or an action on an app it
                restarts, running.
            AppBootstrapNotReleasedError: A manual call before bootstrap release.
            ReloadConfigInvalidError: A manual call found the config on disk invalid.
            ReloadSyntaxError: A manual call found a syntax error in a file it would import.
        """
        started = time.perf_counter()
        manual = isinstance(trigger, ManualReload)
        fail_fast = manual and not trigger.wait
        if fail_fast and self._reconcile_lock.busy:
            raise ReloadBusyError("Another reload is still running")
        async with self._reconcile_lock:
            if manual and not self.bootstrap_coordinator.is_released():
                raise AppBootstrapNotReleasedError("Apps cannot be reloaded before bootstrap release")

            original_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items()}
            old_roots = app_roots(self.hassette.config)
            candidate = self._build_candidate(raise_invalid=manual)
            if candidate is not None:
                current_apps_config = {k: deepcopy(v) for k, v in candidate.apps.manifests.items()}
            else:
                current_apps_config = {k: deepcopy(v) for k, v in original_apps_config.items()}
            changed_file_paths = trigger.paths if isinstance(trigger, WatcherTrigger) else frozenset()

            if not self.bootstrap_coordinator.is_released():
                # Only a watcher event gets here (step 1). No app has started, so there is nothing to lock: commit
                # the config now and queue the lifecycle work for bootstrap's replay.
                await self._defer_pre_release_change(candidate, original_apps_config, changed_file_paths)
                return ReconcileResult()

            pending = self._pending_reconciliation
            if pending is not None:
                # A pre-release change is still queued. Fold it into this diff's baseline so the comparison spans
                # everything since before release. The queue is cleared only when this reconcile commits (``_adopt``),
                # so a refusal leaves it for bootstrap's replay; otherwise the replay would apply that stale snapshot
                # on top of a config it no longer matches.
                self.logger.debug("Merging queued pre-release reconciliation into post-release change")
                original_apps_config = pending.original_apps_config
                changed_file_paths |= pending.changed_paths

            new_roots = app_roots(candidate) if candidate is not None else None
            only_apps = frozenset((candidate if candidate is not None else self.hassette.config).only_apps)
            changes = self.change_detector.detect_changes(
                original_apps_config, current_apps_config, changed_file_paths, only_apps=only_apps
            )
            reload_all = None
            if new_roots is not None:  # a watcher event with an invalid config on disk runs no reload-all
                reload_all = await self._plan_reload_all(
                    current_apps_config,
                    changed_file_paths,
                    manual=manual,
                    old_roots=old_roots,
                    new_roots=new_roots,
                    excluded=changes.new_apps | changes.orphans,
                    only_apps=only_apps,
                )

            adopt = functools.partial(self._adopt, candidate, clear_pending=pending is not None)
            if not changes.has_changes and reload_all is None:
                # Nothing to stop or start, so no lock is needed: commit now. Folding in newly-unblocked apps can
                # still turn this into a change with lifecycle work, applied below on the committed config.
                changes = await adopt(changes)
                if not changes.has_any_change:
                    self.logger.debug("%s changed but no app changes detected", changed_file_paths)
                    return ReconcileResult()
                adopt = None

            self.logger.debug("%s changed, app changes detected - %s", changed_file_paths, changes)
            result = await self._reconcile_changes(
                changes,
                original_apps_config,
                current_apps_config,
                reload_all=reload_all,
                adopt=adopt,
                fail_fast=fail_fast,
                log_refused=not manual,
            )
            if reload_all is not None and not manual:  # the web route logs a manual reload-all's summary
                duration_s = time.perf_counter() - started
                self.logger.info(
                    "File-watcher reload-all finished for %d app(s) in %.1fs: %d succeeded, %d failed, %d refused",
                    len(result.apps),
                    duration_s,
                    result.count(OutcomeResult.SUCCEEDED),
                    result.count(OutcomeResult.FAILED),
                    result.count(OutcomeResult.REFUSED),
                    extra={"duration_s": duration_s},
                )
            return result

    def _build_candidate(self, *, raise_invalid: bool) -> "HassetteConfig | None":
        """Build a candidate config from disk without committing it; None when it is invalid and not raised.

        Raises:
            ReloadConfigInvalidError: ``raise_invalid`` and the config on disk is invalid.
        """
        try:
            return self.hassette.config.build_reload_candidate()
        except Exception as exc:  # an invalid config on disk (ConfigError) needs no traceback; a bug does
            if raise_invalid:
                raise ReloadConfigInvalidError(f"The configuration is invalid: {config_error_summary(exc)}") from exc
            self.logger.error("Config reload rejected: %s", exc, exc_info=not isinstance(exc, ConfigError))
            return None

    async def _plan_reload_all(
        self,
        current_config: dict[str, "AppManifest"],
        changed_paths: frozenset[Path],
        *,
        manual: bool,
        old_roots: frozenset[Path],
        new_roots: frozenset[Path],
        excluded: frozenset[str],
        only_apps: frozenset[str],
    ) -> ReloadAllPlan | None:
        """Decide whether this reconcile runs a reload-all, and plan it; None when it doesn't.

        A manual call always plans one. A watcher event plans one when a changed path needs it
        (``needs_reload_all``, spec 162 D4). Either way the syntax precheck runs first. Both scans read and parse
        files, so they run in a worker thread over a snapshot of ``sys.modules`` taken here, leaving the event loop
        free for the HA connection.

        Args:
            current_config: The app manifests the reload-all runs on.
            changed_paths: The paths the watcher reported; empty for a manual call.
            manual: Whether this is a manual reload-all, which refuses where a watcher event logs and drops it.
            old_roots: The running config's resolved app roots; evicted under too, for an ``app_dir`` the edit removed.
            new_roots: The new config's resolved app roots, which the scans read.
            excluded: Keys the other buckets already handle (new and orphaned apps), never reload-all restarts.
            only_apps: The ``--app`` filter; a key it blocks is not restarted.

        Raises:
            ReloadSyntaxError: ``manual`` and a file the reload-all would import has a syntax error.
        """
        modules = dict(sys.modules)
        if not manual:
            app_files = [manifest.full_path for manifest in current_config.values()]
            if not await asyncio.to_thread(needs_reload_all, changed_paths, app_files, new_roots, modules):
                return None
        enabled_files = [manifest.full_path for manifest in current_config.values() if manifest.enabled]
        error = await asyncio.to_thread(precheck_apps_package, new_roots, enabled_files, modules)
        if error is not None:
            detail = describe_syntax_error(error, new_roots)
            if manual:
                raise ReloadSyntaxError(detail)
            self.logger.error(
                "Reload-all cancelled, so no app restarts for it; apps whose own file changed still reload: %s", detail
            )
            return None
        return ReloadAllPlan(
            restart_keys=self._reload_all_restart_keys(current_config, excluded, only_apps),
            evict_roots=old_roots | new_roots,
        )

    def _reload_all_restart_keys(
        self, current_config: dict[str, "AppManifest"], excluded: frozenset[str], only_apps: frozenset[str]
    ) -> frozenset[str]:
        """Every key the new config runs that is tracked or has an action in flight (spec 162 D1).

        A key with any instance entry, live or FAILED, restarts; one with none (someone stopped it) doesn't. A key
        whose lock is held or awaited is included too, so a start already under way finishes before the eviction and
        is restarted onto the new code, not left on the old one. ``_decide_restart`` rechecks tracking once the lock
        is held, so a key whose in-flight action was a stop stays stopped. A key the new config removes, disables or
        blocks with ``--app`` is left to the other buckets.
        """
        runnable = {
            key for key, manifest in current_config.items() if manifest.enabled and (not only_apps or key in only_apps)
        }
        busy = {key for key in runnable if self._get_app_key_lock(key).busy}
        tracked = set(self.registry.tracked_app_keys()) | busy
        return frozenset((tracked & runnable) - excluded)

    async def _adopt(
        self, candidate: "HassetteConfig | None", changes: ChangeSet, *, clear_pending: bool = False
    ) -> ChangeSet:
        """Commit ``candidate``, reconcile the blocked state, and fold any newly-unblocked apps into ``changes``.

        ``clear_pending`` also clears the queued pre-release reconciliation this reconcile folded into its diff.
        """
        if clear_pending:
            self._take_pre_release_reconciliation()
        await self._commit_candidate(candidate)
        return self._fold_unblocked_apps_into_changes(changes)

    async def _commit_candidate(self, candidate: "HassetteConfig | None") -> None:
        """Swap in ``candidate``, set the registry's manifests and ``--app`` filter, and persist the manifests.

        None (an invalid config on disk) keeps the current config and commits nothing.
        """
        if candidate is None:
            return
        self.hassette.config.adopt(candidate)
        self.set_apps_configs(self.hassette.config.apps.manifests)
        # Restore the --app filter before the persist await, so status reads never see it cleared.
        await self.resolve_only_apps()
        await self.persist_manifests()

    async def _defer_pre_release_change(
        self,
        candidate: "HassetteConfig | None",
        original_apps_config: dict[str, "AppManifest"],
        changed_file_paths: frozenset[Path],
    ) -> None:
        """Commit a pre-release watcher change's config, and queue its lifecycle work for bootstrap's replay."""
        await self._commit_candidate(candidate)
        current_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items()}
        changes = self._fold_unblocked_apps_into_changes(
            self.change_detector.detect_changes(
                original_apps_config, current_apps_config, changed_file_paths, only_apps=self.registry.only_apps
            )
        )
        if not changes.has_any_change:
            self.logger.debug("%s changed but no app changes detected", changed_file_paths)
            return
        if changes.has_changes:
            self.logger.debug("Deferring app reconciliation until bootstrap release opens")
            self._record_pre_release_reconciliation(
                original_apps_config=original_apps_config,
                current_apps_config=current_apps_config,
                changed_file_paths=changed_file_paths,
            )
            return
        # A metadata-only change (e.g. display_name) has nothing for apply_changes()
        # to redo later, so there's no reconciliation to defer. But WebApiService can
        # already be serving manifests to a connected dashboard before bootstrap
        # release opens (see RuntimeQueryService.depends_on, which excludes
        # AppHandler), and release may not open for a long time -- or at all -- while
        # Home Assistant is unreachable. Broadcast now via _reconcile_changes(), which
        # skips apply_changes() since changes.has_changes is False here.
        self.logger.debug("%s changed (metadata-only) before bootstrap release opened", changed_file_paths)
        await self._reconcile_changes(changes, original_apps_config, current_apps_config)

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
        async with self._reconcile_lock:
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

    # dup-ignore-start: every hop of apply_changes takes the same (changes, original, current) config parameters
    async def _reconcile_changes(
        self,
        changes: ChangeSet,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
        *,
        reload_all: ReloadAllPlan | None = None,
        adopt: "Callable[[ChangeSet], Awaitable[ChangeSet]] | None" = None,
        fail_fast: bool = False,
        log_refused: bool = True,
    ) -> ReconcileResult:
        # dup-ignore-end
        """Apply a non-empty ``ChangeSet`` (or a reload-all) and broadcast a manifest-refetch signal.

        The single place ``reconcile_from_disk()`` and
        ``_replay_pre_release_reconciliation_if_needed()`` route every ``ChangeSet``-driven
        apply-then-broadcast decision through, rather than hand-rolling it at each call site's
        own terminal branch -- a new branch that calls ``apply_changes()``/``send_event()``
        directly instead of through here risks reintroducing the class of gap where one branch
        applies changes (or persists metadata) but forgets to broadcast. Callers must already
        have confirmed ``changes.has_any_change`` before calling. This is distinct from
        ``bootstrap_apps()``'s own unconditional "bootstrap sequence finished" broadcast, which
        isn't driven by a ``ChangeSet`` and stays a direct ``send_event()`` call there.

        The keyword arguments pass through to ``apply_changes`` (``AppChangeApplierMixin``).
        """
        result = ReconcileResult()
        if changes.has_changes or reload_all is not None:
            result = await self.apply_changes(
                changes,
                original_config,
                current_config,
                reload_all=reload_all,
                adopt=adopt,
                fail_fast=fail_fast,
                log_refused=log_refused,
            )

        await self.hassette.send_event(
            HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
        )
        return result


def config_error_summary(exc: Exception) -> str:
    """An invalid config's errors as ``location: message`` parts, leaving out the rejected values.

    A refusal's message reaches the web API, so a validation error is reduced to where and why
    (``validation_error_summary``). Any other error keeps its message.
    """
    cause = exc.__cause__
    if not isinstance(cause, ValidationError):
        return str(exc)
    return validation_error_summary(cause.errors())
