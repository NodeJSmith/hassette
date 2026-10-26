import asyncio
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar

from hassette_wire import LogLevel
from watchfiles import awatch

from hassette.events.hassette import HassetteFileWatcherEvent
from hassette.resources.lifecycle import mark_ready
from hassette.resources.service import Service


class FileWatcherService(Service):
    """Background task to watch for file changes and reload apps."""

    required: ClassVar[bool] = False

    @property
    def config_log_level(self) -> LogLevel:
        """Return the configured ``logging.file_watcher`` log level."""
        return self.hassette.config.logging.file_watcher

    async def before_initialize(self) -> None:
        """Wait until the database and session are ready before the watcher initializes."""
        await self.hassette.ready_event.wait()

    async def on_initialize(self) -> None:
        """Mark the service ready right away when file watching is disabled in config.

        When watching is enabled, readiness is deferred to ``serve()`` once the watch starts.
        """
        if not self.hassette.config.file_watcher.watch_files:
            mark_ready(self, reason="File watching disabled")

    async def serve(self) -> None:
        """Watch app directories for changes and trigger reloads."""
        if not self.hassette.config.file_watcher.watch_files:
            self.logger.warning("File watching is disabled due to configuration")
            await self.shutdown_event.wait()
            return

        paths = self.hassette.config.get_watchable_files()

        self.logger.debug("Watching app directories for changes: %s", ", ".join(str(p) for p in paths))
        mark_ready(self, reason="File watcher started")

        async for changes in awatch(
            *paths,
            stop_event=self.shutdown_event,
            step=self.hassette.config.file_watcher.step_milliseconds,
            debounce=self.hassette.config.file_watcher.debounce_milliseconds,
        ):
            if self.shutdown_event.is_set():
                break

            all_changed_paths = await asyncio.to_thread(collapse_changed_paths, changes)

            if all_changed_paths:
                self.logger.debug("Detected changes in %s", all_changed_paths)
                event = HassetteFileWatcherEvent.from_paths(changed_file_paths=all_changed_paths)
                await self.hassette.send_event(event)

            # update paths in case new apps were added
            paths = self.hassette.config.get_watchable_files()


def collapse_changed_paths(changes: Iterable[tuple[object, str]]) -> set[Path]:
    """Resolve each changed path, skipping one already seen or whose parent directory was already seen."""
    all_changed_paths: set[Path] = set()
    for _, raw_path in changes:
        changed_path = Path(raw_path).resolve()
        if changed_path in all_changed_paths:
            continue
        if changed_path.parent in all_changed_paths:
            continue

        all_changed_paths.add(changed_path)
    return all_changed_paths
