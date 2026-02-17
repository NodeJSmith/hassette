# Prereq 6: Open Questions (Decisions Batch)

**Status**: Not started

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- **None** — standalone decisions, can start immediately

## Dependents

- [Prereq 5: Schema design](./prereq-05-schema-design.md) — DB file location, retention policy
- [Prereq 7: Alembic setup](./prereq-07-alembic-setup.md) — aiosqlite choice affects DatabaseService design

## Problem

Several open questions from the research brief need decisions before implementation. They're lightweight enough to batch into one doc rather than separate prereqs.

## Decision 1: aiosqlite vs `run_in_thread`

**Question**: Should the async SQLite bridge be `aiosqlite` (new dependency) or `asyncio.to_thread()` / `TaskBucket.run_in_thread()` wrapping stdlib `sqlite3`?

| Factor                 | `aiosqlite`                                                     | `run_in_thread`                                    |
| ---------------------- | --------------------------------------------------------------- | -------------------------------------------------- |
| Idiom                  | Purpose-built async wrapper, used by most async Python projects | Reuses existing pattern from `diskcache` usage     |
| Connection management  | Manages its own thread + connection lifecycle                   | Manual — you manage the thread pool and connection |
| Cursor/transaction API | Natural `async with db.execute(...)`                            | Wrap every call in `await to_thread(lambda: ...)`  |
| Dependency cost        | ~200 lines, pure Python, well-maintained                        | Zero new deps                                      |
| Batched writes         | Works naturally with `async with db.executemany(...)`           | Awkward — batch logic lives outside the thread     |
| `pytest` integration   | Works with `pytest-asyncio` out of the box                      | Same                                               |

**Recommendation**: `aiosqlite`. The connection/cursor API is substantially cleaner for sustained database access (dozens of different queries), not just one-off calls. The dependency is tiny and well-maintained. `run_in_thread` is right for wrapping a single blocking call; `aiosqlite` is right for a database service.

**Decision**: [ ] Pending

---

## Decision 2: DB file location and naming

**Question**: `data_dir/hassette.db` (single file, room for future tables) or `data_dir/telemetry.db` (scoped to this concern)?

| Option         | Pros                                                                                             | Cons                                                                             |
| -------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `hassette.db`  | Room for future tables (config persistence, UI state, app settings) without adding more DB files | Name is generic                                                                  |
| `telemetry.db` | Clear scope, easy to reason about what's in it                                                   | Need a new file for each new concern, migration coordination across multiple DBs |

**Recommendation**: `hassette.db`. The framework will likely want more persistent storage over time (config, UI preferences, entity history). One DB file with multiple tables is simpler than multiple DBs. The name matches the project.

**Config field**: `db_path: Path = Field(default=None)` — defaults to `data_dir / "hassette.db"` when `None`. Allows override for testing or custom deployment.

**Decision**: [ ] Pending

---

## Decision 3: Retention policy

**Question**: Time-based, size-based, or configurable? What default?

| Approach                 | Pros                              | Cons                                                       |
| ------------------------ | --------------------------------- | ---------------------------------------------------------- |
| Time-based (7 days)      | Easy to reason about, predictable | Doesn't account for high-frequency handlers filling the DB |
| Size-based (1M rows)     | Bounds DB size directly           | Hard to predict what "1M rows" means in practice           |
| Hybrid (time + size cap) | Best of both                      | More complex                                               |
| Configurable             | Flexible                          | More config surface                                        |

**Recommendation**: Time-based, 7 days default, configurable via `db_retention_days: int = 7`.

Rationale: At 100 handler invocations/second (high estimate), 7 days ≈ 60M rows. With ~100 bytes per row (excluding tracebacks), that's ~6GB. That's too much — so also add a size-based failsafe: if the DB exceeds `db_max_size_mb: int = 500` (500MB), delete oldest records until under the limit. The time-based cleanup runs hourly; the size check runs at startup and daily.

For most installations (10-50 handlers, firing on HA state changes), 7 days of data will be well under 100MB.

**Decision**: [ ] Pending

---

## Decision 4: ListenerMetrics — keep in parallel or compute from DB?

**Question**: Should aggregate `ListenerMetrics` objects be maintained in memory alongside per-invocation DB records, or should the dashboard compute aggregates from DB queries?

| Approach                                         | Dashboard latency     | Consistency               | Complexity      |
| ------------------------------------------------ | --------------------- | ------------------------- | --------------- |
| **Parallel** (in-memory aggregates + DB history) | Fast (dict lookup)    | Two sources — could drift | Two write paths |
| **DB-only** (compute aggregates on read)         | Depends on query perf | Single source of truth    | One write path  |

**Recommendation**: Start with parallel. The dashboard currently reads `ListenerMetrics` with zero query cost (dict lookup). Switching to DB aggregate queries risks making the dashboard feel slower if query performance is poor. Keep `ListenerMetrics` for the live dashboard, use DB for history/drill-down.

Migrate to DB-only once we can benchmark aggregate queries with realistic data volumes (~10k-100k rows). If `SELECT ... GROUP BY stable_key` on 100k rows returns in <50ms, drop the parallel `ListenerMetrics`.

**Decision**: [ ] Pending

---

## Decision 5: diskcache overlap

**Question**: Should the `diskcache.Cache` on `Resource` be replaced by the new DB, or kept as a separate concern?

**Recommendation**: Keep separate. They serve completely different purposes:

|                | `diskcache.Cache`                           | New SQLite DB                |
| -------------- | ------------------------------------------- | ---------------------------- |
| Scope          | Per-resource key/value store                | Framework-wide telemetry     |
| Users          | User app code (`self.cache["key"] = value`) | Framework core services      |
| Lifecycle      | Lazy, per-resource-class                    | Managed by `DatabaseService` |
| Access pattern | Key/value get/set                           | Relational queries           |

No action needed — the two coexist under `data_dir` in separate files.

**Decision**: [ ] Pending (or just confirm and close)

---

## Decision 6: DependencyError classification in the schema

**Question**: Should DI failures be a distinct `status` value (`"di_failure"`) or just `status="error"` with `error_type="DependencyError"`?

**Recommendation**: `status="error"` with `error_type="DependencyError"`. See [prereq 1](./prereq-01-handler-invocation-record.md) for full rationale. Keeps the status enum simple and shared between handler invocations and job executions.

Queryable via: `WHERE status = 'error' AND error_type = 'DependencyError'`

**Decision**: [ ] Pending

---

## Deliverable

This file with all `[ ] Pending` checkboxes resolved to `[x] Decided: <choice>`. Each decision should have a one-line rationale. Feeds into [prereq 5](./prereq-05-schema-design.md) and [prereq 7](./prereq-07-alembic-setup.md).
