from pathlib import Path

from watchfiles import awatch

from hassette import Service

from .events import FileWatcherEventPayload


class _FileWatcher(Service):  # pyright: ignore[reportUnusedClass]
    """Background task to watch for file changes and reload apps."""

    async def run_forever(self) -> None:
        """Watch app directories for changes and trigger reloads."""
        if not self.hassette.config.watch_files:
            self.logger.info("File watching is disabled")
            return

        self.logger.debug("Waiting for Hassette ready event")
        await self.hassette.ready_event.wait()

        try:
            async with self.starting():
                paths = self.hassette.config.get_watchable_files()

                self.logger.debug("Watching app directories for changes: %s", ", ".join(str(p) for p in paths))

            async for changes in awatch(
                *paths,
                stop_event=self.hassette.shutdown_event,
                step=self.hassette.config.file_watcher_step_milliseconds,
                debounce=self.hassette.config.file_watcher_debounce_milliseconds,
            ):
                if self.hassette.shutdown_event.is_set():
                    break

                for _, changed_path in changes:
                    changed_path = Path(changed_path).resolve()
                    self.logger.info("Detected change in %s", changed_path)
                    event = FileWatcherEventPayload.create_event(changed_file_path=changed_path)
                    await self.hassette.send_event(event.topic, event)

                # update paths in case new apps were added
                paths = self.hassette.config.get_watchable_files()

        except Exception as e:
            self.logger.exception("App watcher encountered an error, exception args: %s", e.args)
            await self.handle_crash(e)
            raise
