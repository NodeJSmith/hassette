# Prereq 6: Open Questions (Decisions Batch)

**Status**: All decisions made

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- **None** — standalone decisions

## Dependents

- [Prereq 5: Schema design](./prereq-05-schema-design.md) — DB file location, retention policy
- [Prereq 7: Alembic setup](./prereq-07-alembic-setup.md) — aiosqlite choice affects DatabaseService design

## Resolved by other prereqs

### ~~Decision 4: ListenerMetrics — keep in parallel or compute from DB?~~

**Resolved in [prereq 4](./prereq-04-frontend-query-requirements.md)**: DB-only, no parallel in-memory path. Single source of truth. `ListenerMetrics` retired.

### ~~Decision 6: DependencyError classification in the schema~~

**Resolved in [prereq 1](./prereq-01-data-model.md)**: `status="error"` with `error_type="DependencyError"`. No distinct status value.

---

## Decision 1: aiosqlite vs `run_in_thread`

**Question**: Should the async SQLite bridge be `aiosqlite` (new dependency) or `asyncio.to_thread()` / `TaskBucket.run_in_thread()` wrapping stdlib `sqlite3`?

| Factor                 | `aiosqlite`                                                     | `run_in_thread`                                    |
| ---------------------- | --------------------------------------------------------------- | -------------------------------------------------- |
| Idiom                  | Purpose-built async wrapper, used by most async Python projects | Reuses existing pattern from `diskcache` usage     |
| Connection management  | Manages its own thread + connection lifecycle                   | Manual — you manage the thread pool and connection  |
| Cursor/transaction API | Natural `async with db.execute(...)`                            | Wrap every call in `await to_thread(lambda: ...)`   |
| Dependency cost        | ~200 lines, pure Python, well-maintained                        | Zero new deps                                      |
| Batched writes         | Works naturally with `async with db.executemany(...)`           | Awkward — batch logic lives outside the thread      |

**Recommendation**: `aiosqlite`. The connection/cursor API is substantially cleaner for sustained database access (dozens of different queries), not just one-off calls. The dependency is tiny and well-maintained.

**Decision**: Accepted

---

## Decision 2: DB file location and naming

**Question**: `data_dir/hassette.db` or `data_dir/telemetry.db`?

**Recommendation**: `hassette.db`. The framework will likely want more persistent storage over time (config, UI preferences, entity history). One DB file with multiple tables is simpler than multiple DBs. The name matches the project.

**Config field**: `db_path: Path = Field(default=None)` — defaults to `data_dir / "hassette.db"` when `None`. Allows override for testing or custom deployment.

**Decision**: Accepted

---

## Decision 3: Retention policy

**Question**: Time-based, size-based, or hybrid? What default?

**Recommendation**: Time-based with a size failsafe.

- **Primary**: `db_retention_days: int = 7` — hourly cleanup deletes records older than this. Configurable.
- **Failsafe**: `db_max_size_mb: int = 500` — if DB exceeds this, delete oldest records until under the limit. Runs at startup and daily. Configurable.

Both values are configurable via `HassetteConfig`. For most installations (10-50 handlers, firing on HA state changes), 7 days of data will be well under 100MB. Users with high-frequency handlers or long retention needs can adjust both thresholds.

Sessions are exempt from retention — one row per restart, valuable for long-term analytics.

**Decision**: Accepted

---

## Decision 5: diskcache overlap

**Question**: Should `diskcache.Cache` on `Resource` be replaced by the new DB, or kept separate?

**Recommendation**: Keep separate. Different purposes, different access patterns:

|                | `diskcache.Cache`                           | New SQLite DB                |
| -------------- | ------------------------------------------- | ---------------------------- |
| Scope          | Per-resource key/value store                | Framework-wide telemetry     |
| Users          | User app code (`self.cache["key"] = value`) | Framework core services      |
| Lifecycle      | Lazy, per-resource-class                    | Managed by `DatabaseService` |
| Access pattern | Key/value get/set                           | Relational queries           |

No action needed — the two coexist under `data_dir` in separate files.

**Decision**: Accepted

---

## Deliverable

This file with all decisions resolved. Feeds into [prereq 5](./prereq-05-schema-design.md) and [prereq 7](./prereq-07-alembic-setup.md).
