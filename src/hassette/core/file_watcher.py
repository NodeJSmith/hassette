import typing
from copy import deepcopy
from pathlib import Path

from deepdiff import DeepDiff
from watchfiles import awatch

from hassette import Service
from hassette.core.apps.app_handler import ROOT_PATH, USER_CONFIG_PATH
from hassette.core.events.hassette import create_file_watcher_event

if typing.TYPE_CHECKING:
    from hassette.config.app_manifest import AppManifest


class _FileWatcher(Service):
    """Background task to watch for file changes and reload apps."""

    # TODO: double check only_app when any source files change, in case the only flag changed

    async def run_forever(self) -> None:
        """Watch app directories for changes and trigger reloads."""
        try:
            self.logger.info("Starting file watcher service")

            if not (await self.hassette.wait_for_resources_running([self.hassette._app_handler])):
                self.logger.error("App handler is not running, cannot start file watcher")
                return

            paths = self.hassette.config.get_watchable_files()

            self.logger.info("Watching app directories for changes: %s", ", ".join(str(p) for p in paths))

            await self.handle_start()
            async for changes in awatch(*paths, stop_event=self.hassette._shutdown_event):
                if self.hassette._shutdown_event.is_set():
                    break

                for _, changed_path in changes:
                    changed_path = Path(changed_path).resolve()
                    self.logger.info("Detected change in %s", changed_path)
                    await self.handle_changes(changed_path)
                    continue
        except Exception as e:
            self.logger.exception("App watcher encountered an error, exception args: %s", e.args)
            await self.handle_crash(e)
            raise

    async def handle_changes(self, changed_path: Path) -> None:
        """Handle changes detected by the watcher."""

        original_apps_config = deepcopy(self.hassette._app_handler.active_apps_config)

        # Reinitialize config to pick up changes.
        # https://docs.pydantic.dev/latest/concepts/pydantic_settings/#in-place-reloading
        try:
            self.hassette.config.__init__()
        except Exception as e:
            self.logger.exception("Failed to reload configuration: %s", e)
            return
        self.hassette._app_handler.set_apps_configs(self.hassette.config.apps)
        curr_apps_config = deepcopy(self.hassette._app_handler.active_apps_config)

        config_diff = DeepDiff(
            original_apps_config, curr_apps_config, ignore_order=True, include_paths=[ROOT_PATH, USER_CONFIG_PATH]
        )

        orphans, new_apps = self._calculate_app_changes(original_apps_config, curr_apps_config)
        await self._handle_removed_apps(orphans)
        await self._handle_new_apps(new_apps)

        force_reload_apps = self._apps_requiring_force_reload(curr_apps_config, changed_path)
        await self._reload_apps_due_to_file_change(force_reload_apps, new_apps, orphans)
        await self._reload_apps_due_to_config(config_diff, new_apps, orphans, force_reload_apps)

    def _calculate_app_changes(
        self, original_apps_config: dict[str, "AppManifest"], curr_apps_config: dict[str, "AppManifest"]
    ) -> tuple[set[str], set[str]]:
        """Return removed and newly added app keys."""

        original_app_keys = set(original_apps_config.keys())
        curr_app_keys = set(curr_apps_config.keys())

        orphans = original_app_keys - curr_app_keys
        new_apps = curr_app_keys - original_app_keys
        return orphans, new_apps

    async def _handle_removed_apps(self, orphans: set[str]) -> None:
        if not orphans:
            return

        self.logger.info("Apps removed from config: %s", orphans)
        event = create_file_watcher_event(event_type="orphaned_apps", orphaned_apps=orphans)
        await self.hassette.send_event(event.topic, event)

    async def _handle_new_apps(self, new_apps: set[str]) -> None:
        if not new_apps:
            self.logger.debug("No new apps to add")
            return

        self.logger.info("New apps added to config: %s", new_apps)
        event = create_file_watcher_event(event_type="new_apps", new_apps=new_apps)
        await self.hassette.send_event(event.topic, event)

    def _apps_requiring_force_reload(self, curr_apps_config: dict[str, "AppManifest"], changed_path: Path) -> set[str]:
        """Identify app keys that must reload because their source file changed."""

        return {app.app_key for app in curr_apps_config.values() if app.full_path == changed_path}

    async def _reload_apps_due_to_file_change(
        self, force_reload_apps: set[str], new_apps: set[str], orphans: set[str]
    ) -> None:
        if not force_reload_apps:
            return

        apps = {app_key for app_key in force_reload_apps if app_key not in new_apps and app_key not in orphans}

        if not apps:
            return

        self.logger.debug("Apps to force reload due to file change: %s", apps)
        event = create_file_watcher_event(event_type="reimport_apps", reimport_apps=apps)
        await self.hassette.send_event(event.topic, event)

    async def _reload_apps_due_to_config(
        self,
        config_diff: DeepDiff,
        new_apps: set[str],
        orphans: set[str],
        force_reload_apps: set[str],
    ) -> None:
        if not config_diff:
            return

        self.logger.debug("App configuration changes detected: %s", config_diff)
        app_keys = config_diff.affected_root_keys

        apps = {
            app_key
            for app_key in app_keys
            if app_key not in new_apps and app_key not in orphans and app_key not in force_reload_apps
        }
        if not apps:
            return

        self.logger.info("Apps to reload due to config changes: %s", apps)
        event = create_file_watcher_event(event_type="reload_apps", reload_apps=apps)
        await self.hassette.send_event(event.topic, event)
