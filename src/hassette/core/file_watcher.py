from pathlib import Path

from watchfiles import awatch

from hassette.events.hassette import HassetteFileWatcherEvent
from hassette.resources.base import Service


class FileWatcherService(Service):
    """Background task to watch for file changes and reload apps."""

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.file_watcher_log_level

    async def before_initialize(self) -> None:
        self.logger.debug("Waiting for Hassette ready event")
        await self.hassette.ready_event.wait()

    async def serve(self) -> None:
        """Watch app directories for changes and trigger reloads."""
        if not self.hassette.config.watch_files:
            self.logger.warning("File watching is disabled due to configuration")
            return

        paths = self.hassette.config.get_watchable_files()

        self.logger.debug("Watching app directories for changes: %s", ", ".join(str(p) for p in paths))
        self.mark_ready(reason="File watcher started")

        async for changes in awatch(
            *paths,
            stop_event=self.shutdown_event,
            step=self.hassette.config.file_watcher_step_milliseconds,
            debounce=self.hassette.config.file_watcher_debounce_milliseconds,
        ):
            if self.shutdown_event.is_set():
                break

            for _, changed_path in changes:
                changed_path = Path(changed_path).resolve()
                self.logger.debug("Detected change in %s", changed_path)
                event = HassetteFileWatcherEvent.create_event(changed_file_path=changed_path)
                await self.hassette.send_event(event.topic, event)

            # update paths in case new apps were added
            paths = self.hassette.config.get_watchable_files()
