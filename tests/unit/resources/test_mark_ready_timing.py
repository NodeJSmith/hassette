"""Pin which hook each production resource calls ``mark_ready()`` from.

The table mirrors the one in ``.claude/rules/resource-lifecycle.md``. Resources with no background loop
mark ready in an init hook; ``Service`` subclasses with a ``serve()`` loop mark ready once that loop is
running. The exceptions are documented in the rule file.
"""

import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import hassette
from hassette.api.api import Api
from hassette.api.helpers import HelperClient
from hassette.api.sync import ApiSyncFacade
from hassette.api.sync_helpers import HelperClientSyncFacade
from hassette.app.app import App, AppSync
from hassette.bus.bus import Bus
from hassette.bus.sync import BusSyncFacade
from hassette.bus.sync_events import BusSyncEventShortcuts
from hassette.core.api_resource import ApiResource
from hassette.core.app_bootstrap_coordinator import AppBootstrapCoordinator
from hassette.core.app_handler import AppHandler
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.core import Hassette
from hassette.core.database_service import DatabaseService
from hassette.core.event_stream_service import EventStreamService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.logging_service import LoggingService
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.scheduler_service import SchedulerService, _ScheduledJobQueue
from hassette.core.service_watcher import ServiceWatcher
from hassette.core.session_manager import SessionManager
from hassette.core.state_proxy import StateProxy
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.core.web_api_service import WebApiService
from hassette.core.web_ui_watcher import WebUiWatcherService
from hassette.core.websocket_service import WebsocketService
from hassette.resources.base import Resource
from hassette.resources.service import Service
from hassette.scheduler.scheduler import Scheduler
from hassette.scheduler.sync import SchedulerSyncFacade
from hassette.state_manager.state_manager import StateManager
from hassette.task_bucket.task_bucket import TaskBucket
from hassette.testing._harness import _TestableHassette
from hassette.testing.recording_api import RecordingApi
from tests.support.ready_timing import assert_marks_ready_in, find_mark_ready_classes

RULE_FILE = Path(__file__).parents[3] / ".claude" / "rules" / "resource-lifecycle.md"
TABLE_ROW = re.compile(r"^\| (`\w+\(\)`.*?) \| (`.+) \|$", re.MULTILINE)
DEVIATION_BULLET = re.compile(r"^- \*\*`(\w+)`\*\*", re.MULTILINE)

MARK_READY_HOOKS: dict[type, tuple[str, ...]] = {
    # No background loop: ready in an init hook.
    Api: ("on_initialize",),
    ApiResource: ("on_initialize",),
    ApiSyncFacade: ("on_initialize",),
    AppBootstrapCoordinator: ("on_initialize",),
    AppLifecycleService: ("on_initialize",),
    Bus: ("on_initialize",),
    BusSyncFacade: ("on_initialize",),
    EventStreamService: ("on_initialize",),
    HelperClient: ("on_initialize",),
    HelperClientSyncFacade: ("on_initialize",),
    LoggingService: ("on_initialize",),
    RecordingApi: ("on_initialize",),
    RuntimeQueryService: ("on_initialize",),
    Scheduler: ("on_initialize",),
    SchedulerSyncFacade: ("on_initialize",),
    ServiceWatcher: ("on_initialize",),
    SessionManager: ("on_initialize",),
    StateProxy: ("on_initialize",),
    TelemetryQueryService: ("on_initialize",),
    _ScheduledJobQueue: ("on_initialize",),
    AppHandler: ("after_initialize",),
    StateManager: ("after_initialize",),
    TaskBucket: ("__init__",),
    # Service with a serve() loop: ready once the loop is running.
    BusService: ("serve",),
    CommandExecutor: ("serve",),
    DatabaseService: ("serve",),
    FileWatcherService: ("serve",),
    SchedulerService: ("serve",),
    SyncExecutorService: ("serve",),
    # Services that deviate from the serve() rule (see resource-lifecycle.md).
    WebApiService: ("on_initialize",),
    WebUiWatcherService: ("on_initialize", "serve"),
    WebsocketService: ("on_initialize", "start_recv_and_subscribe"),
}

# Resource subclasses that never call mark_ready(self), and who marks them ready instead. Matched by identity:
# a subclass of one of these still needs its own readiness source. Subclasses of a class in MARK_READY_HOOKS
# inherit its hook and need no entry here.
NOT_SELF_MARKED: dict[type, str] = {
    App: "AppLifecycleService marks each app instance ready after on_initialize()",
    AppSync: "subclass of App",
    BusSyncEventShortcuts: "intermediate base class of BusSyncFacade",
    Hassette: "the coordinator signals startup through ready_event, not mark_ready()",
    Service: "abstract base class",
    _TestableHassette: "the test harness sets ready_event directly, like Hassette",
}


@pytest.mark.parametrize(
    ("resource_cls", "hooks"),
    [pytest.param(cls, hooks, id=cls.__name__) for cls, hooks in MARK_READY_HOOKS.items()],
)
def test_resource_marks_ready_in_expected_hook(resource_cls: type, hooks: tuple[str, ...]) -> None:
    assert_marks_ready_in(resource_cls, *hooks)


def test_table_covers_every_resource_that_marks_itself_ready() -> None:
    """A new resource calling mark_ready(self) must be added to the table (and the rule file)."""
    source_root = Path(hassette.__file__).parent
    assert find_mark_ready_classes(source_root) == {cls.__name__ for cls in MARK_READY_HOOKS}


def all_resource_subclasses() -> set[type]:
    """Import every hassette module and return each ``Resource`` subclass defined in the package."""
    for module in pkgutil.walk_packages(hassette.__path__, f"{hassette.__name__}."):
        importlib.import_module(module.name)
    found: set[type] = set()
    pending = [Resource]
    while pending:
        for sub in pending.pop().__subclasses__():
            if sub not in found:
                found.add(sub)
                pending.append(sub)
    return {cls for cls in found if cls.__module__.startswith(f"{hassette.__name__}.")}


def test_every_resource_has_a_readiness_source() -> None:
    """A new Resource subclass must mark itself ready, inherit a class that does, or be listed in NOT_SELF_MARKED."""
    unaccounted = {
        cls.__qualname__
        for cls in all_resource_subclasses()
        if cls not in NOT_SELF_MARKED and not any(issubclass(cls, known) for known in MARK_READY_HOOKS)
    }
    assert not unaccounted, (
        f"Resource subclasses with no mark_ready(self) call and no NOT_SELF_MARKED entry: {unaccounted}"
    )


def test_rule_file_table_matches_hook_table() -> None:
    """The table in resource-lifecycle.md lists the same classes and hooks as MARK_READY_HOOKS."""
    text = RULE_FILE.read_text(encoding="utf-8")
    documented: dict[str, frozenset[str]] = {}
    for hook_cell, names_cell in TABLE_ROW.findall(text):
        hooks = frozenset(re.findall(r"`(\w+)\(\)`", hook_cell))
        for name in re.findall(r"`(\w+)`", names_cell):
            documented[name] = hooks
    expected = {cls.__name__: frozenset(hooks) for cls, hooks in MARK_READY_HOOKS.items()}

    assert documented == expected
    assert set(DEVIATION_BULLET.findall(text)) <= set(documented), "every deviation bullet names a class in the table"
