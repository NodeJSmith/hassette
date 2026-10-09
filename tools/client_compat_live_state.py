"""The state ``tools/generate_client_compat_fixtures.py`` serves its fixtures from, beyond a seed scenario.

The e2e mock fixtures' apps cover only some app and instance statuses, and no seed scenario has a UUID
execution, log records linked to an execution, a traceback, or a blocking event with a captured stack. This
module adds those, to the seeded database and to the stub's live state, so the released client parses
populated bodies for them; and it reads back the identifiers the requests need (:func:`read_seed_ids`).

The seeding lives here rather than in ``scripts/seed_scenarios`` on purpose: those scenarios also feed the e2e
tests and the demo stack, which have no use for fixture-only rows.
"""

import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple
from unittest.mock import AsyncMock, MagicMock

from hassette_wire import AppStatus, ExecutionStatus, ResourceRole, ResourceStatus, StackFrame
from seed_scenarios.base import MONKEYPATCH_TIER, REASON_ATTRIBUTED, WATCHDOG_TIER, SeedContext, make_instance_name

from hassette.exceptions import AppBlockedError, AppBootstrapNotReleasedError, TelemetryUnavailableError
from hassette.schemas.app_snapshots import AppManifestInfo
from hassette.types.enums import BlockReason
from hassette.utils.stack_frames import encode_frames
from tests.e2e.mock_fixtures import build_manifests
from tests.e2e.mock_fixtures.constants import APP_KEY_MULTI_APP
from tests.support.factories import make_execution_record
from tests.support.web_manifest_helpers import make_app_instance_info, make_manifest

APP_KEY_DEGRADED_APP = "degraded_app"
"""A live app with one instance in every ``ResourceStatus``."""

APP_KEY_BLOCKED_APP = "blocked_app"
"""A live app the ``--app`` filter blocks, so starting it answers ``app_blocked`` (:func:`refuse_blocked_apps`)."""

APP_KEY_BUSY_APP = "busy_app"
"""A live app with an action always in flight, so any action on it answers ``action_in_progress``
(:func:`wire_busy_app`). It reports ``STOPPED``, as an app whose start is still running does."""

APP_KEY_ESCAPING_APP = "escaping_app"
"""A live app whose source path resolves outside its app directory, so reading its source answers
``path_traversal`` (:func:`wire_source_paths`)."""

APP_KEY_UNREADABLE_APP = "unreadable_app"
"""A live app whose source path fails to resolve, so reading its source answers ``source_unavailable``
(:func:`wire_source_paths`)."""

OUTSIDE_APP_DIR = Path("/etc/hostname")
"""Where :data:`APP_KEY_ESCAPING_APP`'s source path resolves. Any absolute path outside the app directory makes
the source route's traversal check fire; the route refuses before reading, so the file is never opened."""

MANIFEST_SEED_FIELDS = (
    "app_key",
    "class_name",
    "display_name",
    "filename",
    "enabled",
    "autostart",
    "auto_loaded",
)
"""The ``AppManifestInfo`` fields :func:`seed_live_state` copies into ``SeedContext.add_app_manifest``.

Spelled as names rather than as keyword arguments because the same seven keyword arguments already appear in
``AppRegistry`` and the e2e manifest fixtures, and the duplicate-code gate rejects a third copy."""

SERVICE_CHILDREN = (
    SimpleNamespace(
        class_name="WebsocketService",
        status=ResourceStatus.RUNNING,
        role=ResourceRole.SERVICE,
        _ready_reason="connected",
        _retry_at=None,
    ),
    SimpleNamespace(
        class_name="DatabaseService",
        status=ResourceStatus.FAILED,
        role=ResourceRole.SERVICE,
        _ready_reason=None,
        _retry_at=1_760_000_000.0,  # epoch seconds
    ),
    SimpleNamespace(
        class_name="StateProxy",
        status=ResourceStatus.STARTING,
        role=ResourceRole.RESOURCE,
        _ready_reason=None,
        _retry_at=None,
    ),
)
"""The stub's framework children, which ``/api/health`` lists as services: a ready service, a failed one
waiting to retry, and a starting resource, so every ``ServiceInfo`` field is set somewhere. They carry only the
attributes ``RuntimeQueryService.get_system_status`` reads."""

FAILED_RUN_TRACEBACK = (
    'Traceback (most recent call last):\n  File "/config/apps/handler.py", line 42, in on_change\n'
    '    raise RuntimeError("sensor offline")\nRuntimeError: sensor offline\n'
)

FAULTED_STATUSES = (ResourceStatus.FAILED, ResourceStatus.CRASHED)
"""Instance statuses that carry an error message."""

APP_FRAME = StackFrame(filename="/config/apps/handler.py", lineno=41, function="on_change", module="apps.handler")
LIBRARY_FRAME = StackFrame(
    filename="/usr/lib/python3/site-packages/requests/api.py", lineno=59, function="get", module="requests.api"
)

BLOCKING_STACKS: tuple[tuple[str, str | None, tuple[StackFrame, ...]], ...] = (
    (WATCHDOG_TIER, None, (LIBRARY_FRAME, APP_FRAME)),
    (MONKEYPATCH_TIER, "time.sleep", (LIBRARY_FRAME,)),
)
"""(tier, primitive, innermost-first frames) of the blocking events attached to the failed execution: a
stall whose call site is app code calling into a library, and one detected inside a library."""


@dataclass(frozen=True)
class SeedIds:
    """Identifiers present in one seeded database, ``None`` where the scenario has none."""

    app_key: str | None
    listener_id: int | None
    job_id: int | None
    execution_id: str | None
    failed_execution_id: str | None = None
    """An execution that ended in error or timed out, preferring one with a traceback."""
    logged_execution_id: str | None = None
    """A UUID execution with log records linked to it."""
    multi_app_listed: bool = False
    """Whether the database's app spine lists the multi-instance live app, so ``GET /api/apps/{app_key}``
    answers for it."""


class BaseExecution(NamedTuple):
    """The app-tier listener execution :func:`seed_failed_execution` takes its listener, session and app from."""

    listener_id: int
    session_id: int
    app_key: str
    instance_index: int
    class_name: str | None


def hold_bootstrap(hassette: MagicMock) -> None:
    """App bootstrap never released: readiness answers 503, and start/reload answer ``bootstrap_not_released``.

    Mirrors ``bootstrap_released=False`` in ``create_hassette_stub`` (``tests/support/web_mocks.py``), applied
    after the stub is wired; start and reload raise as the app lifecycle does before the release.
    """
    hassette._app_bootstrap_coordinator.is_released.return_value = False
    hassette._app_bootstrap_coordinator.wait_released.return_value = False
    not_released = AppBootstrapNotReleasedError("app bootstrap has not been released")
    hassette._app_handler.start_app.side_effect = not_released
    hassette._app_handler.reload_app.side_effect = not_released


def fail_activity_buckets(hassette: MagicMock) -> None:
    """One app-grid enrichment query fails, so the grid answers 200 with that part ``None``.

    ``app_grid`` calls ``get_per_app_activity_buckets`` only when ``since`` is set, so a request needs
    ``since`` to reach the failure.
    """
    hassette.telemetry_query_service.get_per_app_activity_buckets = AsyncMock(
        side_effect=TelemetryUnavailableError("activity buckets unavailable")
    )


def break_runtime_overlay(hassette: MagicMock) -> None:
    """The app list's runtime overlay raises an exception no handler maps, so the app answers 500.

    An unmapped exception reaches the catch-all handler ``install_problem_handlers`` registers, which answers
    ``internal_error``.
    """
    hassette.runtime_query_service.overlay_manifest_rows = MagicMock(side_effect=LookupError("overlay broke"))


def live_manifests() -> list[AppManifestInfo]:
    """The stub's live apps: the e2e fixtures' apps, plus the states and failure triggers they lack.

    Between them every ``AppStatus`` and ``ResourceStatus`` the app routes report appears at least once.
    """
    degraded_instances = [
        make_app_instance_info(
            app_key=APP_KEY_DEGRADED_APP,
            index=index,
            class_name="DegradedApp",
            status=status,
            error_message=f"instance {index} {status}" if status in FAULTED_STATUSES else None,
            owner_id=f"DegradedApp.DegradedApp[{index}]",
        )
        for index, status in enumerate(ResourceStatus)
    ]
    return [
        *build_manifests(),
        make_manifest(
            app_key=APP_KEY_DEGRADED_APP,
            class_name="DegradedApp",
            display_name="Degraded App",
            filename="degraded_app.py",
            status=AppStatus.DEGRADED,
            instance_count=len(degraded_instances),
            instances=degraded_instances,
        ),
        make_manifest(
            app_key=APP_KEY_BLOCKED_APP,
            class_name="BlockedApp",
            display_name="Blocked App",
            filename="blocked_app.py",
            status=AppStatus.BLOCKED,
            block_reason=BlockReason.ONLY_APP,
            instance_count=0,
        ),
        *(
            make_manifest(
                app_key=key,
                class_name=name,
                display_name=name,
                filename=f"{key}.py",
                status=AppStatus.STOPPED,
                instance_count=0,
            )
            for key, name in (
                (APP_KEY_ESCAPING_APP, "EscapingApp"),
                (APP_KEY_UNREADABLE_APP, "UnreadableApp"),
                (APP_KEY_BUSY_APP, "BusyApp"),
            )
        ),
    ]


def wire_app_outcomes(hassette: MagicMock, manifests: Iterable[AppManifestInfo]) -> None:
    """Make app actions, config and source reads answer the way each live app's state implies."""
    by_key = {manifest.app_key: manifest for manifest in manifests}
    refuse_blocked_apps(hassette, by_key)
    wire_busy_app(hassette)
    wire_failed_instances(hassette, by_key)
    wire_multi_app_config(hassette, by_key[APP_KEY_MULTI_APP])
    wire_source_paths(hassette)
    wire_framework_services(hassette)
    wire_app_filter(hassette, by_key)


def wire_framework_services(hassette: MagicMock) -> None:
    """Give the stub :data:`SERVICE_CHILDREN` as its children, which ``/api/health`` lists as services."""
    hassette.children = list(SERVICE_CHILDREN)


def wire_app_filter(hassette: MagicMock, by_key: Mapping[str, AppManifestInfo]) -> None:
    """Set the ``--app`` filter that :data:`APP_KEY_BLOCKED_APP`'s ``ONLY_APP`` block reason implies.

    The filter is an allowlist, so it names every other live app. ``/api/apps`` reports it as ``only_apps``;
    the app's refusal to start is wired separately, by :func:`refuse_blocked_apps`.
    """
    hassette._app_handler.registry.only_apps = frozenset(by_key) - {APP_KEY_BLOCKED_APP}


def refuse_blocked_apps(hassette: MagicMock, by_key: Mapping[str, AppManifestInfo]) -> None:
    """Start and reload of a blocked app raise ``AppBlockedError``, which answers ``app_blocked``."""

    async def refuse_blocked(app_key: str, *_args: Any, **_kwargs: Any) -> None:
        if by_key[app_key].status is AppStatus.BLOCKED:
            raise AppBlockedError(f"{app_key} is blocked")

    hassette._app_handler.start_app.side_effect = refuse_blocked
    hassette._app_handler.reload_app.side_effect = refuse_blocked


def wire_busy_app(hassette: MagicMock) -> None:
    """:data:`APP_KEY_BUSY_APP` reports an action in progress, so any action on it answers ``action_in_progress``.

    The route checks this before running the action, so the stub's action mocks are never reached for it.
    """
    hassette._app_handler.is_action_in_progress.side_effect = lambda app_key: app_key == APP_KEY_BUSY_APP


def wire_failed_instances(hassette: MagicMock, by_key: Mapping[str, AppManifestInfo]) -> None:
    """An app's ``FAILED`` instances are the registry's recorded failures.

    A start or reload that leaves a recorded failure answers ``action_failed``, which is how the e2e fixtures'
    broken app reaches that code.
    """

    def failed_instances(app_key: str) -> dict[int, Any]:
        instances = by_key[app_key].instances if app_key in by_key else ()
        return {info.index: info for info in instances if info.status is ResourceStatus.FAILED}

    hassette._app_handler.registry.get_failed_instance_infos.side_effect = failed_instances


def wire_multi_app_config(hassette: MagicMock, multi_app: AppManifestInfo) -> None:
    """The multi-instance app's config lists one entry per instance.

    That makes its higher instance indexes addressable, for the ``app-multi-instance-stop`` and
    ``app-multi-config`` fixtures.
    """
    hassette._app_handler.registry.get_manifest(APP_KEY_MULTI_APP).app_config = [
        {"instance_name": info.instance_name, "env_prefix": f"{APP_KEY_MULTI_APP}_"} for info in multi_app.instances
    ]


def wire_source_paths(hassette: MagicMock) -> None:
    """Point the escaping and unreadable apps' source paths where the source route refuses them.

    :data:`APP_KEY_ESCAPING_APP` resolves to :data:`OUTSIDE_APP_DIR` (``path_traversal``), and
    :data:`APP_KEY_UNREADABLE_APP` fails to resolve (``source_unavailable``).
    """
    registry = hassette._app_handler.registry
    registry.get_manifest(APP_KEY_ESCAPING_APP).full_path.resolve.return_value = OUTSIDE_APP_DIR
    registry.get_manifest(APP_KEY_UNREADABLE_APP).full_path.resolve.side_effect = OSError("unreadable")


def seed_live_state(db_path: Path, manifests: Iterable[AppManifestInfo]) -> None:
    """Add the stub's live apps and one failed execution to a seeded database.

    The app routes list the database's app spine and overlay live status onto it, so the live apps need
    ``app_manifests`` rows for their statuses to reach a response. A scenario with no app-tier listener
    execution (``empty``) has nothing to extend and is left as seeded, so its fixtures keep the empty shapes
    and its execution-detail requests are skipped. That's why the ``empty`` coverage kind is judged across
    all scenarios rather than per scenario.
    """
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        cursor = conn.cursor()
        cursor.row_factory = sqlite3.Row
        row = cursor.execute(
            "SELECT e.listener_id, e.session_id, l.app_key, l.instance_index, m.class_name FROM executions e "
            "JOIN listeners l ON l.id = e.listener_id LEFT JOIN app_manifests m ON m.app_key = l.app_key "
            "WHERE l.source_tier = 'app' ORDER BY e.id LIMIT 1"
        ).fetchone()
        if row is None:
            return
        base = BaseExecution(**dict(row))
        ctx = SeedContext(conn.cursor())
        conn.execute("BEGIN")
        for manifest in manifests:
            ctx.add_app_manifest(**{field: getattr(manifest, field) for field in MANIFEST_SEED_FIELDS})
        seed_failed_execution(ctx, conn, base)
        conn.execute("COMMIT")
    finally:
        conn.close()


def seed_failed_execution(ctx: SeedContext, conn: sqlite3.Connection, base: BaseExecution) -> None:
    """Seed one failed execution of ``base``'s listener, newest in the database, with everything linked to it.

    It has a UUIDv7 id (``/api/executions/{id}`` only accepts UUIDs, which no seed scenario uses), an error
    with a traceback, trigger fields, two log records (one with ``exc_info``), and the blocking events in
    :data:`BLOCKING_STACKS`.
    """
    started = first_value(conn, "SELECT MAX(execution_start_ts) FROM executions") + 60.0
    seq = first_value(conn, "SELECT COALESCE(MAX(seq), 0) + 1 FROM log_records")
    execution_id = uuid7_at(started)
    instance_name = make_instance_name(base.class_name, base.instance_index) if base.class_name else None
    ctx.add_execution(
        make_execution_record(
            session_id=base.session_id,
            listener_id=base.listener_id,
            app_key=base.app_key,
            instance_index=base.instance_index,
            status=ExecutionStatus.ERROR,
            execution_start_ts=started,
            duration_ms=250.0,
            error_type="RuntimeError",
            error_message="sensor offline",
            error_traceback=FAILED_RUN_TRACEBACK,
            execution_id=execution_id,
            trigger_context_id="01JCLIENTCOMPAT0000000000",
            trigger_origin="LOCAL",
        )
    )
    linked = {"app_key": base.app_key, "instance_name": instance_name, "instance_index": base.instance_index}
    log_fields = {
        **linked,
        "logger_name": f"hassette.apps.{base.app_key}",
        "func_name": "on_change",
        "source_tier": "app",
    }
    ctx.add_log_record(
        seq=seq,
        timestamp=started,
        level="INFO",
        message="reading sensor",
        lineno=40,
        execution_id=execution_id,
        **log_fields,
    )
    ctx.add_log_record(
        seq=seq + 1,
        timestamp=started + 0.25,
        level="ERROR",
        message="handler failed",
        lineno=42,
        exc_info=FAILED_RUN_TRACEBACK,
        execution_id=execution_id,
        **log_fields,
    )
    for tier, primitive, frames in BLOCKING_STACKS:
        ctx.add_blocking_event(
            tier=tier,
            reason=REASON_ATTRIBUTED,
            session_id=base.session_id,
            execution_id=execution_id,
            primitive=primitive,
            source_location=f"{APP_FRAME.filename}:{APP_FRAME.lineno}",
            stall_duration_ms=1500.0,
            detected_ts=started + 0.1,
            source_tier="app",
            frames=encode_frames(frames),
            **linked,
        )


def uuid7_at(timestamp: float) -> str:
    """A fixed UUIDv7 whose embedded time is ``timestamp``, so a reseeded scenario gets the same id."""
    # UUIDv7 layout: a 48-bit Unix-millisecond timestamp, the version nibble 7 (rand_a zeroed), then the
    # variant bits 0b10 (rand_b fixed).
    millis = f"{int(timestamp * 1000):012x}"
    return f"{millis[:8]}-{millis[8:]}-7000-8000-000000000001"


def read_seed_ids(db_path: Path) -> SeedIds:
    """The identifiers the success requests need, from a database :func:`seed_live_state` has extended.

    ``app_key`` is the first app with listeners, since the per-app telemetry routes have rows for it. It falls
    back to the first app the spine lists so that a scenario registering apps without listeners still gets
    the per-app requests (no current scenario does). ``empty`` has no rows and no execution to extend, so
    every identifier is ``None`` and the requests that need one are skipped.
    """
    conn = sqlite3.connect(db_path)
    try:
        logged = [
            row[0]
            for row in conn.execute(
                "SELECT execution_id FROM log_records WHERE execution_id IS NOT NULL "
                "GROUP BY execution_id ORDER BY MIN(id)"
            )
        ]
        return SeedIds(
            app_key=first_value(conn, "SELECT app_key FROM listeners ORDER BY id LIMIT 1")
            or first_value(conn, "SELECT app_key FROM app_manifests ORDER BY app_key LIMIT 1"),
            listener_id=first_value(conn, "SELECT id FROM listeners ORDER BY id LIMIT 1"),
            job_id=first_value(conn, "SELECT id FROM scheduled_jobs ORDER BY id LIMIT 1"),
            execution_id=first_value(conn, "SELECT execution_id FROM executions ORDER BY id LIMIT 1"),
            # Rows with a traceback sort first (``error_traceback IS NULL`` is 0 for them), then the oldest.
            failed_execution_id=first_value(
                conn,
                "SELECT execution_id FROM executions WHERE status IN (?, ?) ORDER BY error_traceback IS NULL, id "
                "LIMIT 1",
                ExecutionStatus.ERROR.value,
                ExecutionStatus.TIMED_OUT.value,
            ),
            logged_execution_id=next((value for value in logged if is_uuid(value)), None),
            multi_app_listed=first_value(conn, "SELECT 1 FROM app_manifests WHERE app_key = ?", APP_KEY_MULTI_APP)
            is not None,
        )
    finally:
        conn.close()


def first_value(conn: sqlite3.Connection, query: str, *params: Any) -> Any:
    row = conn.execute(query, params).fetchone()
    return row[0] if row else None


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
