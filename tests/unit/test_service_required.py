"""The framework services' required/optional classification matches spec 134 D17.

``Service.__init_subclass__`` is what makes every concrete service declare one; this pins the values.
Required services end the process when they fail; the two file watchers are optional, so losing one
only disables hot reload.
"""

import pytest

from hassette.core.app_handler import AppHandler
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.core.web_api_service import WebApiService
from hassette.core.web_ui_watcher import WebUiWatcherService
from hassette.core.websocket_service import WebsocketService
from hassette.resources.service import Service

REQUIRED_BY_SERVICE: list[tuple[type[Service], bool]] = [
    (BusService, True),
    (SchedulerService, True),
    (SyncExecutorService, True),
    (WebsocketService, True),
    (DatabaseService, True),
    (CommandExecutor, True),
    (WebApiService, True),
    (AppHandler, True),
    (FileWatcherService, False),
    (WebUiWatcherService, False),
]


@pytest.mark.parametrize(("svc_cls", "required"), REQUIRED_BY_SERVICE, ids=[c.__name__ for c, _ in REQUIRED_BY_SERVICE])
def test_service_declares_required_in_its_own_body(svc_cls: type[Service], required: bool) -> None:
    assert "required" in svc_cls.__dict__, f"{svc_cls.__name__} must declare `required` in its own class body"
    assert svc_cls.required is required
