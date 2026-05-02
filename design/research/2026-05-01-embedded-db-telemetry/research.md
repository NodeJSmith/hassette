---
topic: "Embedded Database and Telemetry Storage"
date: 2026-05-01
status: Draft
---

# Prior Art: Embedded Database and Telemetry Storage

## The Problem

Long-running automation services generate operational telemetry — handler invocations, job executions, session history, error traces — that must survive restarts and power the monitoring UI. The storage layer faces competing demands: writes must be fast and non-blocking (the event bus can't wait for disk), queries must support dashboard aggregation without scanning months of raw data, the database must grow gracefully without filling the disk, and schema changes must apply automatically without manual intervention.

For embedded services (no external database infrastructure), SQLite is the natural choice — but SQLite's concurrency model (single writer, readers-don't-block-writers in WAL mode) requires careful design. The cross-cutting nature of telemetry recording — every handler invocation and job execution needs timing, error classification, and persistence — also raises an architectural question: should recording be embedded in the executor, implemented as middleware, or consumed as events?

## How We Do It Today

Hassette uses **aiosqlite with a single-writer queue pattern** and Alembic migrations. `DatabaseService` manages dual connections — one write connection (accessed by CommandExecutor via a bounded queue) and a dedicated read-only connection for `TelemetryQueryService`. WAL mode is enabled with `synchronous=NORMAL` and `auto_vacuum=INCREMENTAL`. The schema has five core tables: sessions, listeners, scheduled_jobs, handler_invocations, and job_executions — all with `retired_at` timestamps and `source_tier` (app/framework) discrimination. `CommandExecutor` handles cross-cutting execution concerns (timing, error classification, status codes, DI failure detection) and enqueues invocation/execution records fire-and-forget into the write queue, which drains in batches of up to 100 with executemany and row-by-row FK-fallback on integrity errors. Retention runs hourly (age-based deletion) with a size failsafe (batch deletion + incremental vacuum when DB exceeds configured max). Six Alembic migrations track schema evolution with auto-recreation on version mismatch.

## Patterns Found

### Pattern 1: Dedicated Writer Thread with Queue (Single-Writer Pattern)

**Used by**: Home Assistant Recorder, aiosqlite (internally), Huey, SQLite Worker pattern

**How it works**: A single dedicated thread owns the database write connection. All write operations are submitted to an in-memory queue and executed sequentially. Read operations may use separate connections (WAL allows concurrent readers with a single writer). HA's recorder runs in its own thread, consuming `Event` objects from a queue and committing at configurable intervals. aiosqlite implements this internally — each connection has a background thread and request queue.

**Strengths**: Eliminates SQLITE_BUSY errors entirely. Provides predictable write ordering. Decouples producers from the persistence layer. Works naturally with asyncio (the queue bridges async callers to the sync writer thread).

**Weaknesses**: Write throughput limited to single-thread commit speed. Queue depth becomes a concern under sustained bursts. Requires careful shutdown to drain pending writes.

**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/ / https://github.com/omnilib/aiosqlite

### Pattern 2: WAL Mode with Tuned PRAGMAs

**Used by**: Nearly all production SQLite deployments (Home Assistant, Huey, Datasette, Litestream)

**How it works**: WAL mode changes SQLite from "exclusive lock on any write" to "readers never block writers, writers never block readers." Combined with tuned PRAGMAs — `synchronous=NORMAL` (crash-safe with WAL), `busy_timeout=5000`, `cache_size=-64000` (64MB), `mmap_size=268435456` (256MB), `foreign_keys=ON` — SQLite handles significant concurrent read/write workloads.

The key insight from Charles Leifer: WAL + `synchronous=NORMAL` is safe because the WAL file provides the durability guarantee. `synchronous=NORMAL` can lose the most recent transaction on OS crash (not process crash) — acceptable for telemetry, not financial data.

**Strengths**: Massive performance improvement with minimal configuration. Memory-mapped I/O reduces system call overhead for reads. Crash-safe for process crashes.

**Weaknesses**: WAL file can grow large without checkpointing. Increased memory usage from reader snapshots. OS-crash (not process-crash) can lose most recent transaction under `synchronous=NORMAL`.

**Example**: https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/ / https://cj.rs/blog/sqlite-pragma-cheatsheet-for-performance-and-consistency/

### Pattern 3: Tiered Retention with Aggregation

**Used by**: Home Assistant Recorder, Prometheus/Thanos, RRDtool, InfluxDB

**How it works**: Raw telemetry at full resolution for a short retention period (e.g., 10 days). A background process periodically aggregates raw data into summary statistics at lower resolution (e.g., hourly) in a separate long-term table. Raw data is purged after the short-term window; aggregates are kept indefinitely.

HA implements this with `statistics_short_term` (5-minute snapshots, purged after 10 days) and `statistics` (hourly aggregates, kept forever). The nightly purge deletes expired records in batches to avoid long lock holds, cleans up orphaned data, and optionally runs VACUUM.

**Strengths**: Keeps active database small and queries fast while preserving historical trends. Aggregation reduces long-term storage by 100x+. Batch purging avoids lock contention.

**Weaknesses**: Aggregation is lossy — individual data points are unrecoverable after the short-term window. VACUUM is expensive (temporary space equal to DB size). Schema must support both raw and aggregated query patterns.

**Example**: https://www.home-assistant.io/integrations/recorder/ / https://deepwiki.com/home-assistant/core/3.1-recorder-and-statistics

### Pattern 4: Middleware Pipeline for Cross-Cutting Execution Concerns

**Used by**: Dramatiq, ASGI/WSGI frameworks, Express.js

**How it works**: Instead of embedding timing, recording, error handling, and retry logic directly in the executor, these are implemented as composable middleware. Each middleware wraps the next, forming an onion-like call stack with before/after hooks. Dramatiq's Results middleware stores return values/exceptions via `after_process_message()`. Retries, time limits, and rate limiting are all separate middleware.

The alternative is the **Command/Executor pattern** where a single class wraps execution with explicit hooks. Simpler but less composable — adding a concern means modifying the executor. Context managers offer a middle ground: `async with timing(), recording(), error_handling(): await execute()`.

**Strengths**: Each concern isolated, testable, independently toggleable. New concerns added without modifying existing code. Per-task opt-in/out straightforward.

**Weaknesses**: Debugging through a middleware stack requires understanding the full pipeline. Error ownership across middleware boundaries is subtle. Can be over-engineered for simple cases.

**Example**: https://github.com/Bogdanp/dramatiq/blob/master/dramatiq/results/middleware.py / https://dramatiq.io/advanced.html

### Pattern 5: PRAGMA user_version for Self-Migrating Schemas

**Used by**: Many embedded/desktop applications, Android SQLite databases

**How it works**: SQLite's `PRAGMA user_version` stores a single integer for schema versioning. At startup, read the version, compare against expected, run pending migration scripts sequentially. Each migration increments the version. The entire system fits in ~20 lines of Python. HA uses a similar integer-version approach with Python functions instead of SQL files.

**Strengths**: Zero dependencies. `user_version` is atomic with the transaction — if a migration fails, the version doesn't advance. Trivial to test.

**Weaknesses**: No downgrade support. No branch/merge (unlike Alembic's DAG). Sequential only. Complex data migrations awkward in pure SQL. No autogeneration.

**Example**: https://levlaz.org/sqlite-db-migrations-with-pragma-user_version/

### Pattern 6: Task Instance Schema with State Machine

**Used by**: Airflow, Prefect, Celery, Temporal

**How it works**: Each task execution is recorded with identity (task_id, run_id), timing (queued_at, started_at, finished_at, duration), state enum (PENDING, RUNNING, SUCCESS, FAILED, CANCELLED, RETRYING), error fields (error_type, error_message, traceback), and metadata (retry_count, attempt_number, trigger_type). Failures often go to a separate table for faster querying.

Airflow's `task_instance` table is the canonical example. Prefect takes an event-driven approach: state transitions are events consumed asynchronously by a `TaskRunRecorder` service, decoupling recording from execution.

**Strengths**: State machine enables "what's running / what failed / what's retried" queries. Separate timing columns enable duration analysis without computation. Parent_run_id enables hierarchical grouping.

**Weaknesses**: State machine complexity grows with edge cases (timeouts during retries, zombie detection). Full tracebacks are expensive — most truncate or separate. Schema must evolve as new states are added.

**Example**: https://deepwiki.com/apache/airflow/5.1-database-schema-and-erd

### Pattern 7: Repository Pattern with Domain-Specific Query Methods

**Used by**: Cosmic Python architecture, DDD practitioners, many Python web frameworks

**How it works**: A repository class encapsulates all data access for a domain concept. The interface exposes domain-meaningful methods (`get_recent_failures(hours=24)`, `get_slowest_tasks(limit=10)`) rather than generic CRUD. For telemetry, queries are often complex aggregations (average duration by type, failure rate over time, P95 execution time) — better as named methods than ad-hoc SQL.

A key design decision: return projections (TypedDicts/Pydantic) not ORM entities, since telemetry query results are projections, not entities with identity. Testing uses a `FakeRepository` returning canned data.

**Strengths**: Centralizes queries — optimization and indexing straightforward. Testing easy with fake implementations. Self-documenting API. Backend-swappable.

**Weaknesses**: Can become a "god class" for large surfaces. Adds indirection. Abstraction leaks if query performance differs across backends.

**Example**: https://www.cosmicpython.com/book/chapter_02_repository.html

## Anti-Patterns

- **Multiple write connections to SQLite concurrently**: Even in WAL mode, SQLite supports one writer at a time. Multiple connections writing without coordination causes SQLITE_BUSY errors, silent data loss from retry logic, and unpredictable ordering. The correct approach is a single write connection or queue feeding a single writer. ([source](https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/))

- **Running VACUUM during active operation**: VACUUM rebuilds the entire file, requiring temporary space equal to DB size. All operations block during VACUUM. HA runs it only during nightly purge and makes it optional. ([source](https://www.home-assistant.io/integrations/recorder/))

- **Unlimited execution history without retention**: Without pruning, telemetry tables grow indefinitely — degrading queries, bloating backups, eventually filling disk. The n8n community documented multi-gigabyte databases causing severe slowdowns. Retention policies from day one, even generous ones. ([source](https://community.n8n.io/t/sqlite-cleanup-prune-vacuum/50496))

- **Migrations without transaction safety**: DDL outside a transaction means crash mid-migration leaves an inconsistent schema with no recovery. SQLite supports transactional DDL (unlike MySQL) — always wrap migrations in explicit transactions with version increment as the last statement. ([source](https://levlaz.org/sqlite-db-migrations-with-pragma-user_version/))

## Emerging Trends

**Event-driven recording decoupled from execution**: Prefect's `TaskRunRecorder` and HA's queue-based recorder point toward emitting state-change events consumed by a separate recorder service. This keeps execution latency unaffected by DB performance, allows efficient batching, and supports multiple consumers (DB, metrics, logs) without modifying the executor. ([source](https://deepwiki.com/home-assistant/core/3.1-recorder-and-statistics))

**SQLite as a serious production database**: WAL mode, better tooling (sqlite-utils, Litestream for replication, Litefs for distributed access), and frustration with database infrastructure complexity have led to a SQLite resurgence. Frameworks like Huey, Datasette, and various Rails gems now treat SQLite as first-class production. ([source](https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/))

## Relevance to Us

Hassette's database layer is **well-aligned with industry patterns** and in several areas matches or exceeds what comparable frameworks do:

**What we're doing well:**

- **Single-writer queue pattern** (Pattern 1) — the bounded write queue with fire-and-forget enqueue and batch drain matches exactly the pattern HA's recorder uses. The dual-connection approach (write + read-only) is correct for WAL mode.

- **WAL + tuned PRAGMAs** (Pattern 2) — `journal_mode=WAL`, `synchronous=NORMAL`, `auto_vacuum=INCREMENTAL` are the standard production configuration. The auto-checkpoint at 1000 pages prevents WAL growth.

- **Task instance schema** (Pattern 6) — handler_invocations and job_executions tables capture identity, timing, state (success/error/cancelled/timed_out), error details, and session grouping. The `source_tier` discrimination and `retired_at` lifecycle tracking go beyond what most frameworks offer.

- **Repository pattern** (Pattern 7) — `TelemetryRepository` for writes and `TelemetryQueryService` for reads cleanly separate persistence from querying. The query service returns projections (summaries) not raw entities.

- **Retention + size failsafe** — hourly age-based pruning plus a size-based failsafe with incremental vacuum. This is more robust than HA's nightly-only approach — hassette catches growth mid-day.

- **Command Executor for cross-cutting concerns** — timing, error classification, status codes, DI failure detection, and persistence all handled in one place rather than scattered across BusService and SchedulerService. This matches the intent of the middleware pattern (Pattern 4) with a simpler structure appropriate for hassette's scale.

**Gaps worth examining:**

1. **No tiered aggregation** (Pattern 3): Hassette stores raw invocation/execution records and prunes by age. There's no aggregation tier — when raw data is deleted, historical trends are lost. For a monitoring UI that shows "average handler duration over the past month," this means the answer disappears once retention expires. Whether this matters depends on how users use the dashboard — if they only look at recent data, raw + pruning is sufficient. If trend analysis is valuable, a lightweight hourly aggregation table (avg/p95/count per handler per hour) would preserve trends at minimal storage cost.

2. **Alembic may be heavier than needed**: Six migrations managed by Alembic with auto-recreation on version mismatch. The `PRAGMA user_version` pattern (Pattern 5) is dramatically simpler for an embedded database — ~20 lines of Python, no dependencies, no revision DAG. However, Alembic provides autogeneration and complex data migration support that `user_version` doesn't. The current approach of deleting and recreating the DB on schema mismatch sidesteps most of Alembic's complexity — which raises the question of whether Alembic's weight is justified when the fallback is "start fresh."

3. **CommandExecutor vs middleware**: The CommandExecutor centralizes all cross-cutting concerns in a single class (840 lines). Dramatiq's middleware pattern (Pattern 4) would decompose this into independent, composable pieces (timing middleware, recording middleware, error-handling middleware). The tradeoff: middleware is more composable and testable per-concern, but adds indirection. At hassette's current scale, the executor pattern is simpler and sufficient. If the executor continues growing (new concerns like circuit breakers, rate limiting, metrics emission), decomposition into middleware would reduce its complexity.

## Recommendation

Hassette's database layer is production-quality and well-aligned with patterns from HA's recorder, Airflow's metadata DB, and the SQLite best-practices community. The single-writer queue, WAL configuration, retention policies, and repository separation are all the right choices.

The most impactful improvement would be **lightweight statistics aggregation** — a background task that computes hourly summaries (avg duration, p95, count, error rate per handler/job) before raw data is pruned. This preserves trend visibility at minimal cost and is the pattern HA's recorder uses for exactly this reason. It's an additive feature that doesn't require changing the existing write path.

The Alembic-vs-user_version question is worth revisiting if migration complexity stays low. If the pattern remains "delete and recreate on mismatch," the Alembic dependency provides less value than a simple sequential migration runner.

## Sources

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/ — HA Recorder
- https://github.com/omnilib/aiosqlite — aiosqlite architecture
- https://github.com/coleifer/huey/blob/master/huey/storage.py — Huey SQLite storage
- https://github.com/Bogdanp/dramatiq/blob/master/dramatiq/results/middleware.py — Dramatiq results middleware
- https://sqlite-utils.datasette.io/en/stable/python-api.html — sqlite-utils library

### Blog posts & writeups
- https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/ — SQLite performance in Python
- https://cj.rs/blog/sqlite-pragma-cheatsheet-for-performance-and-consistency/ — PRAGMA cheatsheet
- https://levlaz.org/sqlite-db-migrations-with-pragma-user_version/ — user_version migrations
- https://david.rothlis.net/declarative-schema-migration-for-sqlite/ — Declarative migrations
- https://medium.com/@roshanlamichhane/sqlite-worker-supercharge-your-sqlite-performance-in-multi-threaded-python-applications-01e2e43cc406 — SQLite worker pattern
- https://pybit.es/articles/repository-pattern-in-python/ — Repository pattern with SQLite
- https://pythonroadmap.com/blog/celery-result-backends-options-and-best-practices — Celery result backends
- https://mujtabaalmas.me/blog/background-tasks-workers — Task framework comparison

### Documentation & standards
- https://www.home-assistant.io/integrations/recorder/ — HA Recorder documentation
- https://deepwiki.com/home-assistant/core/3.1-recorder-and-statistics — HA Recorder architecture
- https://www.astronomer.io/docs/learn/airflow-database — Airflow metadata DB
- https://deepwiki.com/apache/airflow/5.1-database-schema-and-erd — Airflow schema ERD
- https://apscheduler.readthedocs.io/en/3.x/modules/jobstores/sqlalchemy.html — APScheduler job store
- https://dramatiq.io/advanced.html — Dramatiq middleware
- https://nodered.org/docs/api/context/ — Node-RED context stores
- https://www.cosmicpython.com/book/chapter_02_repository.html — Repository pattern (Cosmic Python)
- https://www.sqliteforum.com/p/sqlite-versioning-and-migration-strategies — Migration strategies discussion
