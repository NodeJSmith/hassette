"""AppLifecycleService — owns app lifecycle orchestration and change handling."""

import asyncio
import typing
from pathlib import Path

from hassette_wire import LogLevel

from hassette.core.app_change_detector import AppChangeDetector
from hassette.core.app_factory import AppFactory
from hassette.core.app_key_lock import AppKeyLock
from hassette.core.app_lifecycle_changes import AppChangeReconcilerMixin
from hassette.core.app_lifecycle_common import (
    AppAdmissionMode,
    PendingReconciliation,
)
from hassette.core.app_lifecycle_config import AppConfigStateMixin
from hassette.core.app_lifecycle_instances import AppInstanceLifecycleMixin
from hassette.core.app_lifecycle_registrations import AppRegistrationReconcilerMixin
from hassette.core.app_lifecycle_start_stop import AppStartStopMixin
from hassette.events.hassette import HassetteSimpleEvent
from hassette.exceptions import AppBootstrapNotReleasedError
from hassette.resources.base import Resource
from hassette.resources.lifecycle import handle_crash, mark_ready
from hassette.types import Topic

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.config.classes import AppManifest
    from hassette.core.app_bootstrap_coordinator import AppBootstrapCoordinator
    from hassette.core.app_registry import AppRegistry


class AppLifecycleService(
    AppInstanceLifecycleMixin,
    AppStartStopMixin,
    AppChangeReconcilerMixin,
    AppConfigStateMixin,
    AppRegistrationReconcilerMixin,
    Resource,
):
    """Manages app lifecycle orchestration, change detection, and event emission.

    Folds in all functionality from ``AppLifecycleManager`` and absorbs the
    implementation methods from ``AppHandler`` that deal with starting, stopping,
    reloading, and change-handling of apps.

    Owns:
        - ``AppFactory`` (plain utility, created internally)
        - ``AppChangeDetector`` (plain utility, created internally)

    Receives:
        - ``AppRegistry`` (shared reference from AppHandler)
    """

    registry: "AppRegistry"
    """Shared registry for tracking app state (owned by AppHandler)."""

    factory: AppFactory
    """Factory for creating app instances."""

    change_detector: AppChangeDetector
    """Detector for configuration changes."""

    def __init__(
        self,
        hassette: "Hassette",
        *,
        parent: Resource | None = None,
        registry: "AppRegistry",
    ) -> None:
        super().__init__(hassette, parent=parent)

        self.registry = registry
        self.factory = AppFactory(hassette, self.registry)
        self.change_detector = AppChangeDetector()
        self._pending_reconciliation: PendingReconciliation | None = None
        # Bus dispatch spawns a fresh task per handler invocation rather than awaiting handlers
        # sequentially (see BusService._dispatch), so two file-watcher events arriving close
        # together can produce two concurrently-running handle_change_event() coroutines. Each
        # does real awaited I/O (refresh_config(), resolve_only_apps()) before touching
        # ``_pending_reconciliation``, and refresh_config() mutates self.registry.manifests
        # in place — so overlapping calls can race on the "what was the world like before this
        # change" snapshot. This lock serializes handle_change_event so only one reconciliation
        # pass runs at a time, matching the "single reconciliation in flight" model the rest of
        # this class already assumes.
        self._change_event_lock = asyncio.Lock()
        # Serializes the create->initialize->reconcile pipeline per app_key. Without it, bootstrap's parked
        # start_app() (waiting in _admit_start()) and a post-release start/reload of the same app_key can both
        # reach factory.create_instances(); register_app() then overwrites without tearing down the loser's
        # instance, and the second reconcile can retire the first caller's live listener/job rows. Never held
        # across the admission wait, so REJECT_IF_UNRELEASED callers fail fast. The web API reads it via
        # is_action_in_progress() to reject concurrent actions. Never pruned; bounded by distinct app_keys.
        self._app_key_locks: dict[str, AppKeyLock] = {}

    async def on_initialize(self) -> None:
        """Signal readiness immediately — no dependencies to wait for."""
        mark_ready(self, reason="AppLifecycleService initialized")

    @property
    def config_log_level(self) -> LogLevel:
        return self.hassette.config.logging.app_handler

    @property
    def startup_timeout(self) -> int:
        """Timeout in seconds for app instance initialization."""
        return self.hassette.config.lifecycle.app_startup_timeout_seconds

    @property
    def shutdown_timeout(self) -> int:
        """Timeout in seconds for app instance shutdown."""
        return self.hassette.config.lifecycle.app_shutdown_timeout_seconds

    @property
    def cleanup_timeout(self) -> int:
        """Timeout in seconds for cleaning up a failed app instance's listeners and jobs."""
        return self.hassette.config.lifecycle.failed_instance_cleanup_timeout_seconds

    @property
    def bootstrap_coordinator(self) -> "AppBootstrapCoordinator":
        return self.hassette.app_bootstrap_coordinator

    def _get_app_key_lock(self, app_key: str) -> AppKeyLock:
        return self._app_key_locks.setdefault(app_key, AppKeyLock())

    def is_action_in_progress(self, app_key: str) -> bool:
        """Whether a start, stop, reload, or config reconciliation holds or is waiting for ``app_key``'s lock."""
        lock = self._app_key_locks.get(app_key)
        return lock is not None and lock.busy

    def _resolve_manifest(self, app_key: str) -> "AppManifest | None":
        """Fetch ``app_key``'s manifest, logging the standard skip message if it is absent.

        A missing manifest means the app is disabled or unknown, which every lifecycle path
        treats as a silent no-op skip. Callers keep their own ``return`` so this works the same
        in public methods and in ``_unlocked`` helpers.
        """
        app_manifest = self.registry.get_manifest(app_key)
        if app_manifest is None:
            self.logger.debug("Skipping disabled or unknown app %s", app_key)
        return app_manifest

    async def _admit_start(self, *, app_key: str, admission_mode: AppAdmissionMode) -> None:
        if admission_mode is AppAdmissionMode.WAIT_FOR_RELEASE:
            await self.bootstrap_coordinator.wait_released()
            return
        if self.bootstrap_coordinator.is_released():
            return
        raise AppBootstrapNotReleasedError(f"App {app_key!r} cannot start before bootstrap release")

    def _record_pre_release_reconciliation(
        self,
        *,
        original_apps_config: dict[str, "AppManifest"],
        current_apps_config: dict[str, "AppManifest"],
        changed_file_paths: frozenset[Path] | None,
    ) -> None:
        pending = self._pending_reconciliation

        if pending is None:
            # First deferred change since the queue was last taken: this call's own baseline
            # and paths become the queue's baseline and paths.
            merged_original = original_apps_config
            merged_paths = changed_file_paths
        elif changed_file_paths is None or pending.changed_paths is None:
            # Either this call or a previous one couldn't scope its paths, so the merged scope
            # degrades to "unknown" (None means "assume everything may have changed").
            merged_original = pending.original_apps_config
            merged_paths = None
        else:
            # Keep the original pre-existing baseline (the "before" snapshot from the first
            # deferred change), union the newly-touched paths onto the ones already queued.
            merged_original = pending.original_apps_config
            merged_paths = pending.changed_paths | changed_file_paths

        self._pending_reconciliation = PendingReconciliation(
            original_apps_config=merged_original,
            current_apps_config=current_apps_config,
            changed_paths=merged_paths,
        )

    def _take_pre_release_reconciliation(
        self,
    ) -> tuple[dict[str, "AppManifest"] | None, dict[str, "AppManifest"] | None, frozenset[Path] | None]:
        pending = self._pending_reconciliation
        self._pending_reconciliation = None
        if pending is None:
            return None, None, None
        return pending.original_apps_config, pending.current_apps_config, pending.changed_paths

    async def bootstrap_apps(self, *, admission_mode: AppAdmissionMode) -> None:
        """Initialize all configured and enabled apps, called at AppHandler startup.

        All declared dependencies are guaranteed ready by AppHandler's depends_on
        auto-wait before this method is invoked.
        """
        if not self.registry.manifests:
            self.logger.debug("No apps configured, skipping initialization")
            if admission_mode is AppAdmissionMode.WAIT_FOR_RELEASE:
                await self.bootstrap_coordinator.wait_released()
                replayed = await self._replay_pre_release_reconciliation_if_needed()
                # Matches the main branch below: a connected dashboard needs a refetch cue once
                # this bootstrap sequence finishes, regardless of whether the replay above found
                # anything to do -- but skip it if the replay already broadcast one itself, or
                # this bootstrap pass would send the same signal twice.
                if not replayed:
                    await self.hassette.send_event(
                        HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
                    )
            return

        try:
            await self.resolve_only_apps()
            self.reconcile_blocked_apps()
            await self.persist_manifests()
            await self.start_apps(admission_mode=admission_mode)
            replayed = await self._replay_pre_release_reconciliation_if_needed()
            snapshot = self.registry.get_snapshot()
            if not snapshot.running_count and not snapshot.failed_count:
                self.logger.warning("No apps were initialized (all apps may be disabled)")
            else:
                self.logger.debug(
                    "Initialized %d apps successfully, %d failed to start",
                    snapshot.running_count,
                    snapshot.failed_count,
                )

            if not replayed:
                await self.hassette.send_event(
                    HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
                )
        except Exception as exc:
            self.logger.exception("Failed to initialize apps")
            await handle_crash(self, exc)
            raise

    def should_autostart(self, app_key: str) -> bool:
        """A new/not-yet-running app auto-starts only if its manifest allows it."""
        manifest = self.registry.get_manifest(app_key)
        return bool(manifest and manifest.autostart)

    def should_auto_reconcile(self, app_key: str) -> bool:
        """Already-running apps are always reconciled; dormant apps only if autostart."""
        return app_key in self.registry or self.should_autostart(app_key)

    async def start_apps(
        self,
        apps: set[str] | None = None,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> None:
        """Create initialization tasks for apps.

        Args:
            apps: Set of app keys to initialize. If None, initialize all autostart-enabled apps.
        """
        apps = apps if apps is not None else set(self.registry.autostart_manifests.keys())

        results = await asyncio.gather(
            *[self.start_app(app_key, admission_mode=admission_mode) for app_key in apps],
            return_exceptions=True,
        )

        # asyncio.CancelledError is a BaseException, not an Exception, so it is invisible to
        # the `isinstance(r, Exception)` filter below — asyncio.gather(return_exceptions=True)
        # collects it as an ordinary result instead of propagating it. Left unchecked, a
        # cancelled start_app() (e.g. shutdown firing while _admit_start() is parked) would be
        # silently dropped here, and bootstrap_apps() would proceed to emit
        # HASSETTE_EVENT_APP_LOAD_COMPLETED as if startup finished normally. Re-raise the first
        # one found so cancellation propagates to the caller instead.
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result

        exception_results = [r for r in results if isinstance(r, Exception)]
        for result in exception_results:
            self.logger.error("Error during app initialization: %s", result, exc_info=result)
