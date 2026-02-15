"""Watch web UI static files and templates, broadcasting reload signals over WebSocket."""

from pathlib import Path

from watchfiles import awatch

from hassette.resources.base import Service

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_WATCH_DIRS = [_WEB_DIR / "static", _WEB_DIR / "templates"]


def _change_kind(path: str) -> str:
    """Classify a changed file path as css, js, or template.

    Classification is by file extension only because the watcher is scoped
    to ``_WATCH_DIRS`` (static/ and templates/), so non-asset files won't
    be seen.
    """
    if path.endswith(".css"):
        return "css"
    if path.endswith(".js"):
        return "js"
    return "template"


class WebUiWatcherService(Service):
    """Watches web UI static/template files and broadcasts reload signals to browsers."""

    async def on_initialize(self) -> None:
        if not self.hassette.config.web_ui_hot_reload:
            self.mark_ready(reason="Web UI hot reload disabled")

    async def serve(self) -> None:
        if not self.hassette.config.web_ui_hot_reload:
            await self.shutdown_event.wait()
            return

        dirs = [d for d in _WATCH_DIRS if d.is_dir()]
        if not dirs:
            self.logger.warning("No web UI directories found to watch")
            return

        self.logger.info("Watching web UI files for hot reload: %s", ", ".join(str(d) for d in dirs))
        self.mark_ready(reason="Web UI hot reload started")

        async for changes in awatch(*dirs, stop_event=self.shutdown_event, debounce=300):
            if self.shutdown_event.is_set():
                break

            for _, changed_path in changes:
                kind = _change_kind(changed_path)
                self.logger.debug("Web UI file changed (%s): %s", kind, changed_path)
                try:
                    relative_path = str(Path(changed_path).relative_to(_WEB_DIR))
                except ValueError:
                    relative_path = Path(changed_path).name
                await self.hassette.data_sync_service.broadcast(
                    {"type": "dev_reload", "data": {"path": relative_path, "kind": kind}}
                )
