import asyncio
import sqlite3
import time
import typing
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import aiosqlite

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.migration_runner import _collect_migrations, _read_user_version, run_migrations
from hassette.exceptions import SchemaVersionError
from hassette.resources.lifecycle import create_lifecycle_task, hooks_pool_remaining, mark_not_ready, mark_ready
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.types.enums import RestartType
from hassette.types.types import LOG_LEVEL_TYPE, SourceTier
from hassette.utils.aiosqlite_utils import close_connection_pair, connect_daemon, stop_connection_sync

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.config.config import HassetteConfig
    from hassette.resources.base import Resource

_WriteQueueItem = tuple[Coroutine[Any, Any, Any], asyncio.Future[Any] | None]
"""Type alias for items placed on the DB write queue."""

# Maximum seconds update_heartbeat() waits for its write to be queued and executed.
# A wedged write worker stops draining the queue without ever raising, so an unbounded
# await would park serve() forever and never reach its failure-count escalation.
# Sized between the two clocks it sits between: comfortably above _BUSY_TIMEOUT_MS (5s), so a
# healthy write merely blocked on the SQLite lock is never mistaken for a wedge, and well under
# the default heartbeat interval (300s, see DatabaseConfig.heartbeat_interval_seconds), so a
# timed-out attempt cannot overlap the next tick. Three strikes therefore escalate roughly
# DatabaseConfig.max_consecutive_heartbeat_failures intervals in.
_HEARTBEAT_WRITE_TIMEOUT_SECONDS = 30

# Ceiling on the seconds on_shutdown() waits for the write queue to drain. A worker that is
# dead (nobody left to call task_done()) or wedged (stuck mid-write) never lets the join
# complete on its own, so it must not outlast the shutdown hooks pool that run_hooks()
# already bounds on_shutdown() with — the effective budget is the smaller of this and
# _DRAIN_TIMEOUT_POOL_FRACTION of the pool remaining, never this constant on its own.
# The pool share is what binds at stock settings: the default resource_shutdown_timeout_seconds
# of 10s yields a 2.5s hooks pool, so the drain gets at most ~1.25s. This ceiling only takes
# effect on installs that raise that timeout past roughly 18s, where half the pool exceeds 5s.
_SHUTDOWN_DRAIN_TIMEOUT_SECONDS = 5

# Share of the remaining hooks pool the drain may claim, leaving the rest for cancelling the
# worker and closing both connections in the same hook. An even split because neither half is
# the clear loser: the drain is best-effort telemetry, while the close it funds is what keeps
# the aiosqlite threads from falling through to the daemon-thread safety net.
_DRAIN_TIMEOUT_POOL_FRACTION = 0.5

_BUSY_TIMEOUT_MS = 5000
"""SQLite busy_timeout (ms) applied to both read and write connections."""

_VACUUM_CHECKPOINT_RETRY_ATTEMPTS = 2
"""Attempts _vacuum_and_checkpoint_with_retry() makes for the incremental_vacuum/wal_checkpoint
pair before giving up on the current tier. One retry absorbs a transient lock; a second
consecutive failure moves on to the next priority tier instead of retrying indefinitely."""

# dup-ignore-start: production source of truth for the log_records column set, asserted against
# verbatim by tests/unit/core/test_log_records.py and mirrored independently in
# tests/integration/database/test_database_service_migrations.py's EXPECTED_TABLES literal (a
# different test tier). A test asserting against this production tuple's contents is not real
# duplication with the tuple itself, and merging the two test-tier literals would couple
# otherwise-independent test suites.
LOG_RECORD_COLUMNS = (
    "seq",
    "timestamp",
    "level",
    "logger_name",
    "func_name",
    "lineno",
    "message",
    "exc_info",
    "app_key",
    "instance_name",
    "instance_index",
    "execution_id",
    "source_tier",
)
# dup-ignore-end
"""log_records table columns (excluding the autoincrement id). Public so `scripts/seed_db.py`
can import the single source of truth instead of hand-keeping a duplicate tuple."""

_LOG_INSERT_SQL = (
    f"INSERT INTO log_records ({', '.join(LOG_RECORD_COLUMNS)}) "
    f"VALUES ({', '.join(':' + c for c in LOG_RECORD_COLUMNS)})"
)


_SQL_BEGIN = "BEGIN"


class _RetentionBatchError(Exception):
    """Raised by ``_delete_target_batched()`` when a batch DELETE fails.

    Carries ``partial_deleted`` — the count of rows already committed by earlier batches for
    this target — so the caller can record real partial progress instead of a false zero. The
    stack frame holding the local accumulator is gone once this propagates, so the count has
    to ride out on the exception itself rather than a return value.

    ``partial_deleted`` is a lower bound, not necessarily exact: if the failure occurs during
    ``commit()`` itself (e.g. ``SQLITE_BUSY`` mid-fsync, or an ``OSError`` from a full disk), the
    current batch's rows are counted as not deleted even though the commit's actual outcome may
    be ambiguous. This is safe (age-based deletes are idempotent and a retry re-selects any rows
    not actually committed) but means the reported count can undercount when correlating with
    other operational symptoms.
    """

    def __init__(self, partial_deleted: int, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.partial_deleted = partial_deleted


@dataclass(frozen=True)
class RetentionTarget:
    """Declarative specification for a table managed by retention cleanup and size failsafe."""

    table: str
    timestamp_col: str
    priority: int
    retention_days_getter: Callable[["HassetteConfig"], int]
    failsafe_label: str
    source_tier: SourceTier | None = None
    """Restrict this target to rows of one source tier. ``None`` means no tier filter (the
    target's table has no ``source_tier`` column, or every row in it should be managed together)."""


_RETENTION_TABLES: list[RetentionTarget] = [
    RetentionTarget(
        table="executions",
        timestamp_col="execution_start_ts",
        priority=1,
        retention_days_getter=lambda cfg: cfg.database.framework_retention_days,
        failsafe_label="framework executions",
        source_tier="framework",
    ),
    RetentionTarget(
        table="blocking_events",
        timestamp_col="detected_ts",
        priority=2,
        retention_days_getter=lambda cfg: cfg.database.retention_days,
        failsafe_label="blocking events",
    ),
    RetentionTarget(
        table="executions",
        timestamp_col="execution_start_ts",
        priority=3,
        retention_days_getter=lambda cfg: cfg.database.retention_days,
        failsafe_label="app executions",
        source_tier="app",
    ),
    RetentionTarget(
        table="log_records",
        timestamp_col="timestamp",
        priority=4,
        retention_days_getter=lambda cfg: cfg.logging.log_retention_days,
        failsafe_label="log records",
    ),
]


def _build_tier_where(target: RetentionTarget) -> tuple[str, list[Any]]:
    """Build a ``WHERE source_tier = ?`` clause (with trailing space) for ``target``, or an
    empty clause when it carries no tier filter. Shared by the size failsafe's delete and its
    stale-row probe, which filter by tier alone (no age cutoff).
    """
    if target.source_tier:
        return "WHERE source_tier = ? ", [target.source_tier]
    return "", []


def _build_age_where(target: RetentionTarget, cutoff: float) -> tuple[str, list[Any]]:
    """Build the ``WHERE ... < cutoff`` clause (plus tier filter, when set) for ``target``.

    Shared by the age-based retention delete and its stale-row probe.
    """
    where = f"{target.timestamp_col} < ?"
    params: list[Any] = [cutoff]
    if target.source_tier:
        where = f"source_tier = ? AND {where}"
        params.insert(0, target.source_tier)
    return where, params


async def _execute_target_delete(
    db: aiosqlite.Connection,
    target: RetentionTarget,
    *,
    cutoff: float,
    batch_limit: int,
) -> int:
    """Delete up to ``batch_limit`` rows in ``target.table`` older than ``cutoff``, filtered by
    ``target.source_tier`` when set, for age-based retention cleanup.

    Does not manage transactions -- the caller owns BEGIN/commit/rollback.
    """
    where, params = _build_age_where(target, cutoff)
    cursor = await db.execute(
        f"DELETE FROM {target.table} WHERE id IN (SELECT id FROM {target.table} WHERE {where} LIMIT ?)",
        [*params, batch_limit],
    )
    return cursor.rowcount or 0


async def _execute_failsafe_delete(
    db: aiosqlite.Connection,
    target: RetentionTarget,
    *,
    batch_limit: int,
) -> int:
    """Delete the oldest ``batch_limit`` rows in ``target.table``, filtered by
    ``target.source_tier`` when set, for the size failsafe.

    Does not manage transactions -- the caller owns commit.
    """
    where_clause, params = _build_tier_where(target)
    cursor = await db.execute(
        f"DELETE FROM {target.table} WHERE id IN "
        f"(SELECT id FROM {target.table} {where_clause}ORDER BY {target.timestamp_col} ASC LIMIT ?)",
        [*params, batch_limit],
    )
    return cursor.rowcount or 0


async def _safe_rollback(db: aiosqlite.Connection, owner: "DatabaseService", context: str) -> None:
    """Roll back a transaction, logging (not raising) if the rollback itself fails.

    Callers remain responsible for handling the original exception (re-raising, logging,
    etc.) after this returns -- this only guards the rollback attempt itself. ``owner.logger``
    is accessed only on the failure path, matching pre-extraction behavior where a caller whose
    rollback always succeeds never had to have a real logger configured.

    A failed rollback here leaves the shared write connection's transaction state unknown --
    the next queued write (heartbeat, another retention batch) executes against whatever was
    left behind, not a guaranteed-clean slate. The log message names that consequence rather
    than just the event.
    """
    try:
        await db.rollback()
    except Exception:
        owner.logger.exception("Rollback also failed for %s — write connection state is now unknown", context)


def _target_failure_reasons(failed_labels: set[str], incomplete_labels: set[str]) -> list[str]:
    """Format a retention-cleanup cycle's failed/incomplete targets for a log message.

    Shared by the parent-guard skip warning and the cycle summary log in
    ``_do_run_retention_cleanup()`` — both need the same "failed: X; incomplete: Y" phrasing.
    """
    reasons: list[str] = []
    if failed_labels:
        reasons.append(f"failed: {', '.join(sorted(failed_labels))}")
    if incomplete_labels:
        reasons.append(f"incomplete: {', '.join(sorted(incomplete_labels))}")
    return reasons


class DatabaseService(Service):
    """Manages the SQLite database for operational telemetry.

    Handles PRAGMA user_version migrations, heartbeat updates, and retention cleanup
    of old execution records.
    """

    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=120,
        fatal_error_names=("SchemaVersionError",),
    )

    _db: aiosqlite.Connection | None
    """The aiosqlite write connection, set during on_initialize."""

    _read_db: aiosqlite.Connection | None
    """Dedicated read-only connection for TelemetryQueryService. Opened on a separate
    WAL snapshot so reads never block the write worker."""

    CONN_ATTRS = ("_read_db", "_db")
    """Connection attributes, in the order both teardown paths close them.

    Read first so the write connection closes last and performs the WAL checkpoint. Named once so
    a rename cannot leave one of the two reflection-based loops behind.
    """

    _db_path: Path
    """Resolved path to the SQLite database file."""

    _consecutive_heartbeat_failures: int
    """Counter for consecutive heartbeat failures; triggers RuntimeError after threshold."""

    _db_write_queue: asyncio.Queue[_WriteQueueItem] | None
    """Bounded queue of pending write coroutines; each paired with an optional Future for result delivery."""

    _db_worker_task: asyncio.Task[None] | None
    """Background task that drains _db_write_queue sequentially."""

    _write_queue_detached: bool
    """Whether a teardown path has taken ``_db_write_queue`` away — see ``detach_write_queue()``."""

    _consecutive_size_triggers: int
    """Counter for consecutive hourly size failsafe triggers; logged as a warning."""

    _consecutive_exhaustion_triggers: int
    """Counter for consecutive size failsafe runs that drained every retention tier and left
    the database still over the configured size limit; logged as a warning."""

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._db = None
        self._read_db = None
        self._db_path = Path()
        self._consecutive_heartbeat_failures = 0
        self._consecutive_size_triggers = 0
        self._consecutive_exhaustion_triggers = 0
        self._db_write_queue = None
        self._db_worker_task = None
        self._write_queue_detached = False

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.database_service

    @property
    def is_db_ready(self) -> bool:
        """Whether the write database connection is open and usable."""
        return self._db is not None

    @property
    def is_accepting_writes(self) -> bool:
        """Whether the write queue is live and accepting submissions.

        False before ``on_initialize()`` creates the queue and after shutdown drains it.
        """
        return self._db_write_queue is not None

    @property
    def db(self) -> aiosqlite.Connection:
        """Return the active write database connection.

        Raises:
            RuntimeError: If the database connection is not initialized.
        """
        if self._db is None:
            raise RuntimeError("Database connection is not initialized")
        return self._db

    @property
    def read_db(self) -> aiosqlite.Connection:
        """Return the dedicated read-only database connection.

        Uses a separate WAL snapshot so reads never block the write worker.

        Raises:
            RuntimeError: If the read connection is not initialized.
        """
        if self._read_db is None:
            raise RuntimeError("Read database connection is not initialized")
        return self._read_db

    async def on_initialize(self) -> None:
        """Set up the database: check schema version, run migrations and open connection."""
        self._consecutive_heartbeat_failures = 0
        self._consecutive_size_triggers = 0
        self._consecutive_exhaustion_triggers = 0
        # Cleared up front, not at queue-creation time below: a restart whose initialization
        # fails before it gets that far must still report the pre-init cause rather than a
        # stale post-teardown one left over from the previous lifecycle.
        self._write_queue_detached = False
        self._db_path = self.resolve_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        await self.handle_schema_version(self._db_path)

        self.logger.info("Running database migrations for %s", self._db_path)
        timeout = self.hassette.config.database.migration_timeout_seconds
        await asyncio.wait_for(asyncio.to_thread(self.run_migrations), timeout=timeout)

        self._db = await connect_daemon(self._db_path, isolation_level=None)
        self._db.row_factory = aiosqlite.Row

        # Open a dedicated read connection on a separate WAL snapshot (F1).
        # This ensures read queries never block the write worker.
        self._read_db = await connect_daemon(self._db_path, isolation_level=None)
        self._read_db.row_factory = aiosqlite.Row
        await self._read_db.execute("PRAGMA query_only = ON")
        await self._read_db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")

        await self.set_pragmas()
        # Bound the startup failsafe check at half the configured startup readiness budget. A
        # large first-run backlog (slow PRAGMA incremental_vacuum/wal_checkpoint on a big,
        # over-limit DB) could otherwise itself exhaust the readiness timeout that
        # wait_for_ready() enforces around this whole on_initialize() call — the exact scenario
        # this design exists to fix. A timeout here degrades to "startup skipped cleanup," not a
        # failed startup: per-batch commits mean whatever was already deleted stays deleted,
        # and the hourly run_size_failsafe() continues grinding the backlog down afterward.
        startup_failsafe_timeout = self.hassette.config.lifecycle.startup_timeout_seconds / 2
        try:
            await asyncio.wait_for(self._check_size_failsafe(), timeout=startup_failsafe_timeout)
        except Exception:
            self.logger.warning("Startup size failsafe check failed; continuing without cleanup", exc_info=True)

        self._db_write_queue = asyncio.Queue(maxsize=self.hassette.config.database.write_queue_max)
        # Bypass the loop's global task factory so the worker is not tracked by
        # any TaskBucket. A bare asyncio.create_task() falls through to the root
        # Hassette bucket via make_task_factory(); the root bucket's cancel_all()
        # runs before wave-based child shutdown begins, killing the worker before
        # on_shutdown() can drain the queue — producing two 10s stalls per test
        # (one in each downstream wave that tries to submit() a write to the dead
        # worker). The worker's lifecycle is managed by on_shutdown() (drain-and-close) and
        # _force_terminal() (hard cancel on the total-shutdown-timeout path).
        self._db_worker_task = create_lifecycle_task(self.db_write_worker(), name=f"db_write_worker:{self.unique_name}")
        self._db_worker_task.add_done_callback(self._log_worker_exit)

    def _log_worker_exit(self, task: asyncio.Task) -> None:
        """Log an unhandled exception from ``_db_worker_task``.

        ``_db_worker_task`` bypasses TaskBucket entirely (see ``on_initialize()``), so
        ``TaskBucket.add()``'s own done callback -- the only other place a worker crash gets
        logged and forwarded to the installed exception recorders -- never runs for it. Without
        this callback, a worker crash (e.g. the ``RuntimeError`` guard in ``db_write_worker()``
        when ``_db_write_queue`` is ``None``, or a ``ValueError`` from ``queue.task_done()``)
        would go completely unlogged, and every later ``submit()`` would hang awaiting a future
        no worker will ever resolve, since ``submit()`` has no timeout of its own.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self.logger.error("DB write worker for %s exited unexpectedly", self.unique_name, exc_info=exc)

    def _force_terminal(self) -> None:
        """Override to also cancel the untracked database write worker, drain its queue, and
        close connections.

        ``_db_worker_task`` bypasses TaskBucket entirely (see ``on_initialize()``), so
        ``Service._force_terminal()``'s ``TaskBucket.cancel_all_sync()`` never reaches it.
        Without cancelling it here, a total-shutdown-timeout force-terminal call (which skips
        ``on_shutdown()``, the only other place this task is cancelled) leaves the worker
        and its queue/connections running after the process has declared shutdown complete.

        Detaches ``_db_write_queue`` via ``detach_write_queue()`` (mirroring ``on_shutdown()``'s
        drain-and-close pattern, minus the graceful ``queue.join()`` this synchronous path can't
        await) before closing remaining items via ``close_remaining_queue_items()``. Without this,
        two things go wrong: any coroutine still queued when the worker is cancelled is never
        closed (GC eventually raises "coroutine was never awaited"), and ``submit()``/``enqueue()``
        only reject once ``_db_write_queue`` is ``None`` -- leaving it set would let a caller
        enqueue into a queue with a cancelled worker, hanging ``submit()``'s awaited future
        forever.

        Closing ``_db``/``_read_db`` here (via the same synchronous ``stop_connection_sync()``
        used by ``App._force_terminal()`` for its cache) matters for the same reason: this path
        intentionally skips ``on_shutdown()``/``cleanup()`` (see ``Resource._force_terminal()``'s
        docstring) because production assumes force-terminal is nearly always followed by process
        exit. In a long-lived process -- notably the test suite -- a connection left open here
        would otherwise sit until the garbage collector reclaims it, firing an unraisable-exception
        warning attributed to whichever test happens to be running at that moment.
        """
        if self._db_worker_task is not None and not self._db_worker_task.done():
            self._db_worker_task.cancel()
        self.close_remaining_queue_items(self.detach_write_queue())
        for attr in self.CONN_ATTRS:
            stop_connection_sync(getattr(self, attr))
            setattr(self, attr, None)
        super()._force_terminal()

    async def serve(self) -> None:
        """Run the heartbeat, retention, and size failsafe loop until shutdown."""
        mark_ready(self, reason="Database service started")

        last_retention_run = time.monotonic()
        last_size_failsafe_run = time.monotonic()

        while True:
            config = self.hassette.config.database
            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=config.heartbeat_interval_seconds)
                # shutdown_event was set — exit
                mark_not_ready(self, reason="Shutting down")
                return
            except TimeoutError:
                pass

            await self.update_heartbeat()

            if self._consecutive_heartbeat_failures >= config.max_consecutive_heartbeat_failures:
                raise RuntimeError(f"Heartbeat failed {self._consecutive_heartbeat_failures} consecutive times")

            time_since_retention = time.monotonic() - last_retention_run
            if time_since_retention >= config.retention_interval_seconds:
                await self.run_retention_cleanup()
                last_retention_run = time.monotonic()

            time_since_size_failsafe = time.monotonic() - last_size_failsafe_run
            if time_since_size_failsafe >= config.size_failsafe_interval_seconds:
                await self.run_size_failsafe()
                last_size_failsafe_run = time.monotonic()

    async def on_shutdown(self) -> None:
        """Drain the write queue, cancel the worker, then close the database connection."""
        queue: asyncio.Queue[_WriteQueueItem] | None = None
        try:
            if self._db_worker_task is not None:
                queue = self.detach_write_queue()
                if queue is not None:
                    await self.drain_write_queue(queue)
                self._db_worker_task.cancel()
                await asyncio.gather(self._db_worker_task, return_exceptions=True)
                self._db_worker_task = None
        except Exception:
            self.logger.exception("Error draining write queue during shutdown")
        finally:
            if self._db_worker_task is not None:
                self._db_worker_task.cancel()
                await asyncio.gather(self._db_worker_task, return_exceptions=True)
                self._db_worker_task = None
            self.close_remaining_queue_items(queue)
            await self.close_connections()

    async def drain_write_queue(self, queue: asyncio.Queue[_WriteQueueItem]) -> None:
        """Wait for already-queued writes to finish, bounded by the remaining hooks pool.

        A dead worker (nobody left to call task_done()) or a wedged one (stuck mid-write) never
        lets ``queue.join()`` complete on its own. Left unbounded it outlasts the hooks pool that
        ``run_hooks()`` bounds ``on_shutdown()`` with, which force-terminates the hook and skips
        the connection close entirely.

        Args:
            queue: The write queue to drain. Already detached from ``_db_write_queue``, so no new
                items can arrive while this waits.
        """
        timeout = min(_SHUTDOWN_DRAIN_TIMEOUT_SECONDS, hooks_pool_remaining(self) * _DRAIN_TIMEOUT_POOL_FRACTION)
        try:
            async with asyncio.timeout(timeout):
                await queue.join()
        except TimeoutError:
            # qsize() excludes the item the worker already dequeued, which the caller's cancel()
            # abandons too — so it is a floor, not the total.
            self.logger.warning(
                "Write queue did not drain within %.2fs — abandoning %d queued write(s) "
                "plus any write already in flight",
                timeout,
                queue.qsize(),
            )

    def close_remaining_queue_items(self, queue: asyncio.Queue[_WriteQueueItem] | None) -> None:
        """Close any coroutines left on the write queue without executing them.

        Called during shutdown to prevent unawaited-coroutine warnings from GC.
        """
        if queue is None:
            return
        closed = 0
        while True:
            try:
                coro, future = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            coro.close()
            if future is not None and not future.done():
                future.cancel()
            queue.task_done()
            closed += 1
        if closed:
            self.logger.debug("Closed %d remaining coroutine(s) from write queue during shutdown", closed)

    async def close_connections(self) -> None:
        """Close both database connections. Idempotent -- safe to call multiple times.

        aiosqlite's worker threads are set to daemon in on_initialize() as a safety net, but this
        method still does a best-effort close to avoid resource warnings and ensure clean WAL
        checkpoints.

        Propagates the first close failure rather than swallowing it: both call sites feed teardown
        accounting that has to tell a clean close from one that left a connection in an unknown
        state -- ``cleanup()`` records ``TeardownCause.CLEANUP_FAILED`` and ``on_shutdown()``
        records ``TeardownCause.SHUTDOWN_HOOK_FAILED`` on an escaping exception. See
        ``close_connection_pair()`` for the close and cancellation mechanics.
        """
        await close_connection_pair(self, self.CONN_ATTRS, self.logger)

    async def cleanup(self, timeout: float | None = None) -> None:
        """Close database connections if on_shutdown was interrupted or never ran."""
        await self.close_connections()
        await super().cleanup(timeout)

    async def db_write_worker(self) -> None:
        """Drain _db_write_queue sequentially.

        Each item is a (coroutine, future) pair. If future is not None, the
        coroutine's result (or exception) is delivered through it. If future is
        None, any exception is logged and the worker continues.

        The loop runs until cancelled by on_shutdown().
        """
        if self._db_write_queue is None:
            raise RuntimeError("db_write_worker() started before on_initialize() set _db_write_queue")
        queue = self._db_write_queue
        while True:
            coro, future = await queue.get()
            try:
                result = await coro
                if future is not None and not future.done():
                    future.set_result(result)
            except asyncio.CancelledError:
                # on_shutdown() bounds its drain, so the worker can be cancelled with an item
                # still executing. close_remaining_queue_items() only reaches items still on
                # the queue, so without this the submit() caller awaiting this future would
                # stay suspended forever.
                if future is not None and not future.done():
                    future.cancel()
                raise
            except Exception as exc:
                if future is not None and not future.done():
                    future.set_exception(exc)
                else:
                    self.logger.exception("Unhandled error in enqueued DB write")
            finally:
                queue.task_done()

    def detach_write_queue(self) -> asyncio.Queue[_WriteQueueItem] | None:
        """Take the write queue away so ``submit()``/``enqueue()`` start rejecting, and return it.

        Both teardown paths (``on_shutdown()``, ``_force_terminal()``) go through here so the
        detach and the ``_write_queue_detached`` flag that records it can never drift apart — see
        ``queue_unavailable_error()`` for what that flag buys. The flag is only raised when there
        was a queue to take, so tearing down a service whose ``on_initialize()`` never got far
        enough to create one still reports the pre-init cause.
        """
        queue, self._db_write_queue = self._db_write_queue, None
        if queue is not None:
            self._write_queue_detached = True
        return queue

    def queue_unavailable_error(self, method: str) -> RuntimeError:
        """Build the rejection raised when ``_db_write_queue`` is gone.

        The queue is ``None`` both before ``on_initialize()`` creates it and after a teardown
        path detaches it, so the message comes from ``_write_queue_detached`` -- the flag
        ``detach_write_queue()`` sets -- rather than from the resource's status. Status cannot
        answer this: an ``on_initialize()`` failure before the queue is created leaves the
        service in ``FAILED``/``CRASHED`` with no teardown having run, which would otherwise be
        reported as a post-shutdown call.
        """
        if self._write_queue_detached:
            return RuntimeError(f"DatabaseService.{method}() called after shutdown")
        return RuntimeError(f"DatabaseService.{method}() called before on_initialize()")

    async def submit(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Submit a coroutine for serialized execution and await its result.

        The coroutine is placed on the write queue and executed by the single-writer
        worker. The caller is suspended until the coroutine completes.

        Args:
            coro: The coroutine to execute.

        Returns:
            The return value of the coroutine.

        Raises:
            Exception: Whatever exception the coroutine raises.
        """
        if self._db_write_queue is None:
            coro.close()
            raise self.queue_unavailable_error("submit")
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        try:
            await self._db_write_queue.put((coro, future))
        except BaseException:
            coro.close()
            future.cancel()
            raise
        return await future

    def enqueue(self, coro: Coroutine[Any, Any, Any]) -> bool:
        """Submit a coroutine for fire-and-forget execution.

        Returns immediately. The coroutine is placed on the write queue and
        executed by the single-writer worker. Any exception is logged; the worker
        continues processing subsequent items.

        Args:
            coro: The coroutine to execute.

        Returns:
            True if enqueued successfully, False if dropped due to a full queue.
        """
        if self._db_write_queue is None:
            coro.close()
            raise self.queue_unavailable_error("enqueue")
        try:
            self._db_write_queue.put_nowait((coro, None))
        except asyncio.QueueFull:
            coro.close()
            self.logger.error(
                "DB write queue full (%d items) — dropping fire-and-forget task",
                self._db_write_queue.qsize(),
            )
            return False
        qsize = self._db_write_queue.qsize()
        if qsize > 0 and qsize % 100 == 0:
            self.logger.warning("DB write queue depth at %d items — potential backlog", qsize)
        return True

    def resolve_db_path(self) -> Path:
        """Resolve the database path from config or use default."""
        if self.hassette.config.database.path is not None:
            return self.hassette.config.database.path.resolve()
        return self.hassette.config.data_dir / "hassette.db"

    def get_expected_head_version(self) -> int:
        """Return the highest migration version number from migrations_sql/ (synchronous).

        Scans the migrations_sql/ directory for *.sql files with numeric stems
        and returns the largest version number found.
        """
        sql_files = _collect_migrations(None)
        if not sql_files:
            raise RuntimeError("No migration files found in migrations_sql/")
        return max(sql_files)

    def get_current_db_version(self, db_path: Path) -> int:
        """Return PRAGMA user_version from the on-disk DB (synchronous). Returns 0 for fresh databases."""
        return _read_user_version(db_path)

    async def handle_schema_version(self, db_path: Path) -> None:
        """Check schema version and handle mismatches.

        If the DB file does not exist yet, does nothing (migrations will create it).
        If the DB version matches the expected head, does nothing.
        If the DB version is behind head (0 < current < head), does nothing —
        run_migrations() will apply pending migrations incrementally, preserving data.
        If the DB version is 0 on an existing file (pre-PRAGMA-era or fresh DB with
        no migrations applied), deletes the file so migrations recreate it cleanly.
        If the DB version is *ahead* of head (newer DB on older binary), logs an ERROR
        and raises SchemaVersionError — auto-delete is refused in this case.

        Args:
            db_path: Path to the SQLite database file.

        Raises:
            SchemaVersionError: When the DB version is ahead of the expected head version.
            RuntimeError: When the DB file cannot be deleted due to permissions.
        """
        if not db_path.exists():
            return

        expected_head = await asyncio.to_thread(self.get_expected_head_version)
        current_version = await asyncio.to_thread(self.get_current_db_version, db_path)

        if current_version == expected_head:
            return

        if current_version > expected_head:
            self.logger.error(
                "Database schema version %d is ahead of the code's expected head %d. "
                "This usually means a newer binary created this database. "
                "Refusing to auto-delete — upgrade the binary or remove the database manually.",
                current_version,
                expected_head,
            )
            raise SchemaVersionError(
                f"Database schema version {current_version} is ahead of expected head "
                f"{expected_head}. Cannot start safely."
            )

        if current_version > 0:
            self.logger.info(
                "Database schema version %d is behind head %d — pending migrations will be applied.",
                current_version,
                expected_head,
            )
            return

        if current_version == 0:
            self.logger.warning(
                "Database has no schema version (expected %d) — recreating database (no production data to preserve).",
                expected_head,
            )
            try:
                db_path.unlink(missing_ok=True)
                for suffix in ("-wal", "-shm"):
                    Path(str(db_path) + suffix).unlink(missing_ok=True)
            except PermissionError as exc:
                raise RuntimeError(
                    f"Cannot delete stale database file {db_path}: {exc}. Please remove it manually and restart."
                ) from exc

    def run_migrations(self) -> None:
        """Run PRAGMA user_version migrations to the latest version (synchronous, called via to_thread).

        auto_vacuum = INCREMENTAL is set by the runner before any tables are created.
        """
        run_migrations(self._db_path)

    async def set_pragmas(self) -> None:
        """Configure SQLite PRAGMAs for performance and safety."""
        db = self.db
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA wal_autocheckpoint = 1000")
        # NORMAL is an intentional performance tradeoff: in WAL mode, the last committed
        # writes before an OS crash (not app crash) may be lost if not yet checkpointed.
        # This is acceptable for operational telemetry — the orphan-session mechanism
        # compensates for session rows but not for individual telemetry records.
        await db.execute("PRAGMA synchronous = NORMAL")
        await db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        await db.execute("PRAGMA foreign_keys = ON")
        # Intentionally a no-op — auto_vacuum is set by the migration runner before table creation.
        # This line documents intent only.
        await db.execute("PRAGMA auto_vacuum = INCREMENTAL")

    async def update_heartbeat(self) -> None:
        """Await a heartbeat update for the current session.

        Early-return guards run inline; the DB write is awaited via submit()
        so that _consecutive_heartbeat_failures is updated before returning.

        The submit() call is bounded by _HEARTBEAT_WRITE_TIMEOUT_SECONDS. A wedged write
        worker never raises — it just stops draining the queue — so without this bound
        serve() would park on submit() forever and never reach its failure-count
        escalation. A timeout counts as a heartbeat failure identically to a raised
        sqlite3.Error/OSError/ValueError, so three in a row still escalate to a restart.

        This method is the only place _consecutive_heartbeat_failures moves, so one attempt
        costs exactly one strike. Counting the timeout here and the raise inside the queued
        coroutine would let a single slow-then-failing write consume two of the three,
        restarting the service a full heartbeat interval early.
        """
        if self._db is None:
            return
        if self._db_write_queue is None:
            return
        try:
            _ = self.hassette.session_id
        except RuntimeError:
            return
        max_consecutive_heartbeat_failures = self.hassette.config.database.max_consecutive_heartbeat_failures
        try:
            async with asyncio.timeout(_HEARTBEAT_WRITE_TIMEOUT_SECONDS):
                await self.submit(self._do_update_heartbeat())
        except TimeoutError:
            self._consecutive_heartbeat_failures += 1
            self.logger.exception(
                "Heartbeat write timed out after %ds — write worker may be wedged (failure %d/%d)",
                _HEARTBEAT_WRITE_TIMEOUT_SECONDS,
                self._consecutive_heartbeat_failures,
                max_consecutive_heartbeat_failures,
            )
        except (sqlite3.Error, OSError, ValueError):
            self._consecutive_heartbeat_failures += 1
            self.logger.exception(
                "Failed to update heartbeat (failure %d/%d)",
                self._consecutive_heartbeat_failures,
                max_consecutive_heartbeat_failures,
            )
        else:
            if self._consecutive_heartbeat_failures > 0:
                self.logger.info("Heartbeat recovered after %d failure(s)", self._consecutive_heartbeat_failures)
                self._consecutive_heartbeat_failures = 0

    async def _do_update_heartbeat(self) -> None:
        """Execute the heartbeat DB write; called by the write-queue worker.

        Failures propagate to update_heartbeat() through submit()'s future rather than
        being counted here — see that method for why the count lives in one place.
        """
        session_id = self.hassette.session_id
        now = time.time()
        await self.db.execute(
            "UPDATE sessions SET last_heartbeat_at = ? WHERE id = ?",
            (now, session_id),
        )
        await self.db.commit()
        self.logger.debug("Heartbeat updated for session %d", session_id)

    async def run_retention_cleanup(self) -> None:
        """Enqueue a retention cleanup; fire-and-forget via enqueue()."""
        if self._db is None:
            return
        if self._db_write_queue is None:
            return
        self.enqueue(self._do_run_retention_cleanup())

    async def _delete_target_batched(
        self, target: RetentionTarget, now: float, config: "HassetteConfig"
    ) -> tuple[int, bool]:
        """Batched age-based delete for one retention target.

        ``exhausted`` is True when the per-cycle batch cap ran out with rows matching the
        cutoff still present. This is a normal return, not an exception, but the caller must
        treat it the same as a raised failure for parent-guard gating purposes: an exhausted
        target's cutoff window still has known-stale rows, the exact condition the
        parent-guard's own NOT EXISTS check assumes can't happen for any target it isn't told
        about. The remainder is picked up on the next hourly cycle either way.

        Returns:
            tuple[int, bool]: ``(total_deleted, exhausted)``.

        Raises:
            _RetentionBatchError: On failure, carrying the count of rows already committed by
                earlier batches — the caller is responsible for recording failed_labels and
                preserving that partial progress from the exception.
        """
        target_start = time.monotonic()
        cutoff = now - (target.retention_days_getter(config) * SECONDS_PER_DAY)
        batch_size = config.database.retention_delete_batch
        max_batches = config.database.retention_max_batches_per_target

        total_deleted = 0
        exhausted = False
        for _ in range(max_batches):
            try:
                await self.db.execute(_SQL_BEGIN)
                batch_count = await _execute_target_delete(self.db, target, cutoff=cutoff, batch_limit=batch_size)
                await self.db.commit()
            except Exception as exc:
                raise _RetentionBatchError(total_deleted, exc) from exc
            total_deleted += batch_count
            if batch_count < batch_size:
                break
        else:
            # Every batch ran full-sized, but that doesn't prove rows past the cutoff remain —
            # the final full batch may have removed the last one. Check before declaring the
            # target incomplete; an unnecessary "incomplete" here skips otherwise-safe
            # parent-guard cleanup and emits a false backlog warning for the next hour.
            where, params = _build_age_where(target, cutoff)
            try:
                stale_cursor = await self.db.execute(f"SELECT 1 FROM {target.table} WHERE {where} LIMIT 1", params)
                stale_row = await stale_cursor.fetchone()
            except Exception as exc:
                raise _RetentionBatchError(total_deleted, exc) from exc
            if stale_row is not None:
                exhausted = True
                self.logger.warning(
                    "Retention cleanup: %s hit the %d-batch cap for this cycle with records still past "
                    "cutoff — treating as incomplete and skipping parent-guard deletes this cycle; "
                    "remainder continues next cycle",
                    target.failsafe_label,
                    max_batches,
                )

        elapsed = time.monotonic() - target_start
        if total_deleted > 0:
            self.logger.info(
                "Retention cleanup: deleted %d %s in %.1fs",
                total_deleted,
                target.failsafe_label,
                elapsed,
            )
        return total_deleted, exhausted

    async def _run_parent_guard_deletes(self, cutoff: float) -> tuple[int, int]:
        """NOT EXISTS-guarded deletes for retired listeners/scheduled_jobs.

        Only delete retired listeners/scheduled_jobs when ALL their child executions have
        also aged out. This prevents orphaning recent executions whose parent row would be
        deleted because retired_at (set at restart time) diverges from last execution time.

        Returns:
            tuple[int, int]: ``(listeners_deleted, jobs_deleted)``.

        Raises:
            Exception: Propagates any DB error from the delete statements.
        """
        await self.db.execute(_SQL_BEGIN)
        cursor_rl = await self.db.execute(
            """
            DELETE FROM listeners
            WHERE retired_at IS NOT NULL AND retired_at < ?
              AND NOT EXISTS (
                  SELECT 1 FROM executions
                  WHERE listener_id = listeners.id
                    AND execution_start_ts >= ?
              )
            """,
            (cutoff, cutoff),
        )
        # Same guard for scheduled_jobs.
        cursor_rj = await self.db.execute(
            """
            DELETE FROM scheduled_jobs
            WHERE retired_at IS NOT NULL AND retired_at < ?
              AND NOT EXISTS (
                  SELECT 1 FROM executions
                  WHERE job_id = scheduled_jobs.id
                    AND execution_start_ts >= ?
              )
            """,
            (cutoff, cutoff),
        )
        await self.db.commit()
        return cursor_rl.rowcount or 0, cursor_rj.rowcount or 0

    async def _do_run_retention_cleanup(self) -> None:
        """Execute the retention DELETE queries; called by the write-queue worker.

        Iterates _RETENTION_TABLES for tier-aware, batched age-based deletes — each target
        gets its own per-batch transaction, bounding per-batch lock duration, and a failure
        on one target does not roll back deletes already committed for another.
        Parent-guard deletes for listeners/scheduled_jobs only run once every target has both
        succeeded AND fully cleared its cutoff window this cycle; a target that raised or hit
        the per-cycle batch cap (see ``_delete_target_batched``'s ``exhausted`` return) skips
        the guard for this cycle so it can never run against a state where an upstream delete
        is known to be incomplete. A parent-guard failure is rolled back, logged individually,
        and also folded into the "Retention cleanup summary" line below (as
        "parent-guard deletes failed") so it isn't only visible in a separate log line.
        """
        config = self.hassette.config
        now = time.time()
        deleted_by_label: dict[str, int] = {}
        failed_labels: set[str] = set()
        incomplete_labels: set[str] = set()

        for target in _RETENTION_TABLES:
            try:
                deleted, exhausted = await self._delete_target_batched(target, now, config)
            except _RetentionBatchError as exc:
                await _safe_rollback(self.db, self, target.failsafe_label)
                self.logger.exception("Retention cleanup failed for %s", target.failsafe_label)
                # Batches already committed before the failure are real, durable progress —
                # record them alongside the failure rather than reporting a false zero.
                deleted_by_label[target.failsafe_label] = exc.partial_deleted
                failed_labels.add(target.failsafe_label)
                continue
            deleted_by_label[target.failsafe_label] = deleted
            if exhausted:
                incomplete_labels.add(target.failsafe_label)

        listeners_deleted = 0
        jobs_deleted = 0
        parent_guard_failed = False

        if not failed_labels and not incomplete_labels:
            try:
                # Use the standard retention window for parent-guard deletes.
                cutoff = now - (config.database.retention_days * SECONDS_PER_DAY)
                listeners_deleted, jobs_deleted = await self._run_parent_guard_deletes(cutoff)
            except Exception:
                await _safe_rollback(self.db, self, "parent-guard deletes")
                self.logger.exception("Retention cleanup failed for parent-guard deletes")
                parent_guard_failed = True
        else:
            self.logger.warning(
                "Retention cleanup: skipping parent-guard deletes — target(s) %s",
                "; ".join(_target_failure_reasons(failed_labels, incomplete_labels)),
            )

        deleted_summary = {label: count for label, count in deleted_by_label.items() if count > 0}
        if deleted_summary or failed_labels or incomplete_labels or parent_guard_failed:
            parts = ", ".join(f"{count} {label}" for label, count in deleted_summary.items())
            tags = _target_failure_reasons(failed_labels, incomplete_labels)
            if parent_guard_failed:
                tags.append("parent-guard deletes failed")
            self.logger.info(
                "Retention cleanup summary: deleted %s%s",
                parts or "nothing",
                f" ({'; '.join(tags)})" if tags else "",
            )
        if listeners_deleted or jobs_deleted:
            self.logger.info(
                "Retention cleanup: deleted %d retired listeners, %d retired scheduled_jobs",
                listeners_deleted,
                jobs_deleted,
            )

    def get_db_size_mb(self) -> float:
        """Return total database size (main + WAL + SHM) in megabytes."""
        total = 0
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self._db_path) + suffix)
            if path.exists():
                total += path.stat().st_size
        return total / (1024 * 1024)

    async def _vacuum_and_checkpoint_with_retry(
        self, db: aiosqlite.Connection, vacuum_pages: int, group_label: str
    ) -> bool:
        """Run PRAGMA incremental_vacuum + wal_checkpoint(TRUNCATE), retrying on failure.

        Returns True if the vacuum/checkpoint pair succeeded on any attempt (up to
        ``_VACUUM_CHECKPOINT_RETRY_ATTEMPTS``), False if every attempt failed.
        """
        for attempt in range(_VACUUM_CHECKPOINT_RETRY_ATTEMPTS):
            try:
                vacuum_cursor = await db.execute(f"PRAGMA incremental_vacuum({vacuum_pages})")
                await vacuum_cursor.close()
                checkpoint_cursor = await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                checkpoint_row = await checkpoint_cursor.fetchone()
                await checkpoint_cursor.close()
                # wal_checkpoint(TRUNCATE) doesn't raise when it's blocked (SQLITE_BUSY) -- it
                # returns a row whose first column is nonzero instead. Treat a missing row or a
                # nonzero busy value as a failed attempt so it's caught below and retried like
                # any other vacuum/checkpoint failure.
                if checkpoint_row is None or checkpoint_row[0] != 0:
                    raise sqlite3.OperationalError(f"wal_checkpoint(TRUNCATE) busy or failed: {checkpoint_row}")
                return True
            except Exception:
                attempts_left = _VACUUM_CHECKPOINT_RETRY_ATTEMPTS - attempt - 1
                if attempts_left > 0:
                    self.logger.warning(
                        "Size failsafe: vacuum/checkpoint failed for %s, %d attempt(s) left",
                        group_label,
                        attempts_left,
                    )
                else:
                    self.logger.exception(
                        "Size failsafe: vacuum/checkpoint failed after %d attempts for %s, moving to next tier",
                        _VACUUM_CHECKPOINT_RETRY_ATTEMPTS,
                        group_label,
                    )
        return False

    async def _check_size_failsafe(self) -> None:
        """Delete oldest records if database exceeds the configured size limit.

        Iterates _RETENTION_TABLES grouped by priority (lower priority number = deleted
        first). Within each priority tier, all tables in the group are deleted together
        per iteration; a target's ``source_tier`` filter (when set) is applied inside the
        inner SELECT so each tier's own oldest-N rows are deleted, not the globally-oldest
        N rows filtered down afterward. After each iteration a vacuum+checkpoint (with a
        single bounded retry — see ``_vacuum_and_checkpoint_with_retry()``) reclaims disk
        space. The process stops as soon as the database falls within the size limit.

        ``max_iterations`` is a single budget shared across the whole run, not a per-tier
        allowance — each tier only gets whatever iterations remain after higher-priority
        tiers have spent theirs, so a run never deletes more than ``max_iterations`` batches
        total regardless of how many priority tiers it touches.

        If a tier's iteration loop runs out of its share of the budget without naturally draining
        (every iteration deletes a full batch), the tier is only treated as capped after
        probing whether it still has matching rows — the same stale-row check
        ``_delete_target_batched()`` uses. An exact-boundary final batch can drain the tier's
        own rows while the database stays oversized purely because of other, lower-priority
        tiers; probing avoids stopping there and skipping those tiers unnecessarily. When the
        probe confirms rows remain, the run stops instead of advancing to the next,
        lower-priority tier — a capped tier still has a large backlog of higher-value data of
        its own, and deleting app/log data while that backlog remains would defeat the priority
        ordering. The next hourly cycle retries the capped tier first.

        A DELETE failure on one priority tier is logged with the target's ``failsafe_label``,
        current size, and limit, then skipped — subsequent, lower-priority tiers still run
        rather than the whole failsafe run silently aborting. The failed tier retries on the
        next hourly cycle. The stale-row probe above is isolated the same way: a probe failure
        is logged and skips the rest of that tier rather than propagating out of this method.
        A vacuum/checkpoint failure that exhausts its retry is treated the same way — the tier
        is marked incomplete and the run moves on to the next tier.

        ``_consecutive_exhaustion_triggers`` is only incremented when every tier genuinely
        drained (no capped tier, no DELETE/vacuum failure) and the database is still over the
        limit — a cycle that stopped early on a capped tier or skipped a tier after a failure
        does not count as "exhausted," since the overage there is attributable to the
        stop/skip rather than to unmanaged data across every tier. Such a cycle also resets the
        counter to 0, so a later genuinely-exhausted cycle reports a fresh streak rather than
        one that silently spans the interruption. A WARNING is logged for every over-limit
        cycle, naming every cause that applied — a capped tier, one or more skipped/failed
        tiers, or (when neither applied) that every tier drained without resolving the
        overage — rather than only the first cause checked.
        """
        config = self.hassette.config.database
        max_size_mb = config.max_size_mb
        if max_size_mb == 0:
            return

        current_size = self.get_db_size_mb()
        if current_size <= max_size_mb:
            self._consecutive_size_triggers = 0
            self._consecutive_exhaustion_triggers = 0
            return

        self._consecutive_size_triggers += 1
        if self._consecutive_size_triggers > 1:
            self.logger.warning(
                "Size failsafe triggered %d consecutive times (%.1f MB > %.1f MB limit)",
                self._consecutive_size_triggers,
                current_size,
                max_size_mb,
            )

        db = self.db
        total_deleted_by_label: dict[str, int] = {t.failsafe_label: 0 for t in _RETENTION_TABLES}
        batch_limit = config.size_failsafe_delete_batch
        max_iterations = config.size_failsafe_max_iterations
        vacuum_pages = config.size_failsafe_vacuum_pages

        priorities = sorted({t.priority for t in _RETENTION_TABLES})
        capped_tier_label: str | None = None
        any_tier_incomplete = False
        iterations_used = 0
        for priority in priorities:
            group = [t for t in _RETENTION_TABLES if t.priority == priority]
            group_label = ", ".join(t.failsafe_label for t in group)
            capped_early = False

            # max_iterations is a shared per-run budget, not a per-tier one -- each tier
            # only gets whatever's left after higher-priority tiers already spent theirs.
            remaining_iterations = max_iterations - iterations_used
            for _iteration in range(remaining_iterations):
                iterations_used += 1
                group_deleted = 0
                group_failed = False
                for target in group:
                    try:
                        n = await _execute_failsafe_delete(db, target, batch_limit=batch_limit)
                    except Exception:
                        # No rollback here — this connection is opened with isolation_level=None
                        # (autocommit), and unlike the age-based retention path, this loop never
                        # issues an explicit BEGIN, so there is no open transaction to roll back.
                        # Any earlier deletes in this iteration already committed on execute.
                        self.logger.exception(
                            "Size failsafe failed for %s (%.1f MB > %.1f MB limit)",
                            target.failsafe_label,
                            current_size,
                            max_size_mb,
                        )
                        group_failed = True
                        continue
                    total_deleted_by_label[target.failsafe_label] += n
                    group_deleted += n

                # Commit whatever succeeded this iteration before vacuuming. PRAGMA
                # wal_checkpoint(TRUNCATE) below cannot run while the delete statements hold a
                # write lock — without this commit it fails with "database table is locked".
                await db.commit()

                if group_failed:
                    # This priority tier had a DELETE raise — stop retrying it and move on to
                    # the next tier instead of aborting the whole failsafe run. The next hourly
                    # cycle retries this tier from scratch.
                    any_tier_incomplete = True
                    break

                if group_deleted == 0:
                    break

                # A single bounded retry: a transient vacuum/checkpoint failure (e.g. a
                # momentary lock) shouldn't push the failsafe into deleting from a more
                # valuable tier based on a size reading that's stale only because the WAL
                # wasn't truncated -- the deletes already happened.
                vacuum_ok = await self._vacuum_and_checkpoint_with_retry(db, vacuum_pages, group_label)
                if not vacuum_ok:
                    any_tier_incomplete = True
                    break

                current_size = self.get_db_size_mb()
                if current_size <= max_size_mb:
                    break
            else:
                # Every iteration this tier got ran full-sized (or the shared budget was
                # already spent by a higher-priority tier, leaving remaining_iterations at 0),
                # but that doesn't prove this tier's own rows remain — the final full batch may
                # have drained this tier's last row while the database stays oversized only
                # because of other, lower-priority tiers. Probe before declaring this tier
                # capped; an unnecessary cap here would skip those other tiers unnecessarily.
                for target in group:
                    where_clause, stale_params = _build_tier_where(target)
                    try:
                        stale_cursor = await db.execute(
                            f"SELECT 1 FROM {target.table} {where_clause}LIMIT 1", stale_params
                        )
                        stale_row = await stale_cursor.fetchone()
                    except Exception:
                        # No rollback here either — the probe is a plain SELECT, and (as above)
                        # this loop never opens a transaction to roll back in the first place.
                        self.logger.exception(
                            "Size failsafe stale-row probe failed for %s (%.1f MB > %.1f MB limit)",
                            target.failsafe_label,
                            current_size,
                            max_size_mb,
                        )
                        any_tier_incomplete = True
                        continue
                    if stale_row is not None:
                        capped_early = True
                        self.logger.warning(
                            "Size failsafe %s capped at %d iterations; database still %.1f MB (limit %.1f MB) — "
                            "stopping this cycle without touching lower-priority tiers",
                            group_label,
                            max_iterations,
                            current_size,
                            max_size_mb,
                        )
                        break

            current_size = self.get_db_size_mb()
            if current_size <= max_size_mb:
                break

            if capped_early:
                # This tier is still over its per-cycle iteration cap with the database still
                # over the limit — stop here rather than advancing to a lower-priority (more
                # valuable) tier. Advancing would let app/log data get deleted while this
                # higher-priority tier still has a large backlog of its own, defeating the
                # priority ordering for exactly the high-volume scenario it exists to handle.
                # The next hourly cycle starts again from the lowest priority number, so this
                # tier is retried first.
                capped_tier_label = group_label
                break

        deleted_summary = {label: count for label, count in total_deleted_by_label.items() if count > 0}
        if deleted_summary:
            parts = ", ".join(f"{count} {label}" for label, count in deleted_summary.items())
            self.logger.info("Size failsafe: deleted %s (%.1f MB remaining)", parts, current_size)

        if current_size > max_size_mb:
            if capped_tier_label is not None or any_tier_incomplete:
                # Either cause breaks any exhaustion streak in progress — the next
                # genuinely-exhausted cycle must not report a count that spans across this
                # interruption. Both causes can occur in the same cycle (an earlier tier's
                # DELETE/vacuum failure, followed by a later tier hitting its iteration cap) —
                # report every cause that applied instead of only the one checked first, so a
                # capped tier discovered after an earlier failure doesn't hide that failure from
                # the aggregate warning.
                self._consecutive_exhaustion_triggers = 0
                causes = []
                if any_tier_incomplete:
                    causes.append("one or more tiers failed and were skipped this cycle")
                if capped_tier_label is not None:
                    causes.append(
                        f"{capped_tier_label} hit the {max_iterations}-iteration cap "
                        "(lower-priority tiers were not touched this cycle)"
                    )
                self.logger.warning(
                    "Size failsafe stopped early: %s; database still %.1f MB (limit %.1f MB) — retrying next cycle",
                    "; ".join(causes),
                    current_size,
                    max_size_mb,
                )
            else:
                self._consecutive_exhaustion_triggers += 1
                self.logger.warning(
                    "Size failsafe exhausted all retention tiers %d consecutive time(s); "
                    "database still %.1f MB (limit %.1f MB)",
                    self._consecutive_exhaustion_triggers,
                    current_size,
                    max_size_mb,
                )
        else:
            self._consecutive_exhaustion_triggers = 0

    async def run_size_failsafe(self) -> None:
        """Enqueue a size failsafe check; fire-and-forget via enqueue()."""
        if self._db is None:
            return
        if self._db_write_queue is None:
            return
        self.enqueue(self._check_size_failsafe())

    async def _insert_log_records(self, records: list[dict]) -> None:
        """Batch-insert log records into the log_records table.

        Must only be called via enqueue() — never await directly.
        """
        if not records:
            return
        db = self.db
        try:
            await db.execute(_SQL_BEGIN)
            await db.executemany(_LOG_INSERT_SQL, records)
            await db.commit()
        except Exception:
            await _safe_rollback(db, self, "log record insert")
            raise
