from pathlib import Path

from watchfiles import awatch

from hassette import Service
from hassette.core.events.hassette import create_file_watcher_event


class _FileWatcher(Service):
    """Background task to watch for file changes and reload apps."""

    async def run_forever(self) -> None:
        """Watch app directories for changes and trigger reloads."""
        try:
            self.logger.info("Starting file watcher service")

            paths = self.hassette.config.get_watchable_files()

            self.logger.info("Watching app directories for changes: %s", ", ".join(str(p) for p in paths))

            await self.handle_start()
            async for changes in awatch(
                *paths,
                stop_event=self.hassette._shutdown_event,
                step=self.hassette.config.file_watcher_step_milliseconds,
                debounce=self.hassette.config.file_watcher_debounce_milliseconds,
            ):
                if self.hassette._shutdown_event.is_set():
                    break

                for _, changed_path in changes:
                    changed_path = Path(changed_path).resolve()
                    self.logger.info("Detected change in %s", changed_path)
                    event = create_file_watcher_event(changed_file_path=changed_path)
                    await self.hassette.send_event(event.topic, event)

                # update paths in case new apps were added
                paths = self.hassette.config.get_watchable_files()

        except Exception as e:
            self.logger.exception("App watcher encountered an error, exception args: %s", e.args)
            await self.handle_crash(e)
            raise
