# Edge-Case Bug Fixes — Design Doc

## Problem

An edge-case audit targeting multiple handlers on the same entity, duplicate scheduled jobs, dynamic registration, and API/UI representation uncovered 7 bugs across the telemetry DB, API routes, scheduler, and web layer. Two are high-severity data-correctness issues; the rest are medium/low robustness gaps.

### Bug inventory

| # | Title | Severity | Root cause |
|---|-------|----------|------------|
| 1 | DB telemetry collapse for same-method multi-predicate listeners | HIGH | Unique constraint `(app_key, instance_index, handler_method, topic)` lacks predicate info; two listeners with different predicates share one DB row |
| 2 | Dashboard errors return wrong listener_id/job_id/execution_start_ts | HIGH | SQL doesn't SELECT `listener_id`/`job_id`; route reads `timestamp` but column is `execution_start_ts`; test mocks hide the bug |
| 3 | SPA catch-all path check fails under editable installs | MEDIUM | `_SPA_DIR` not resolved but `candidate.resolve()` is; symlinked installs break containment check |
| 4 | Scheduler auto-generated name collision | MEDIUM | `__post_init__` uses only `callable.__name__` for job names; two `run_every` calls with same method but different intervals collide |
| 5 | Bus metrics endpoint is a dead stub | LOW | `GET /bus/metrics` returns hardcoded zeros; nothing calls it; superseded by `/api/telemetry/dashboard/kpis` |
| 6 | `GET /apps/{app_key}` is unused and broken | LOW | Returns only first instance for multi-instance apps; no frontend or known consumer calls this endpoint |
| 7 | Dashboard endpoints lack graceful degradation | LOW | `dashboard_kpis` and `dashboard_errors` propagate DB exceptions as raw 500s; `dashboard_app_grid` already has try/except but catches bare `Exception` |

### Related issue actions

- **#236** (total_jobs double-count) — closed as stale; referenced code was removed during Preact migration
- **#418** (SPA catch-all + web cleanup) — bugs 3, 5, 6 overlap; this PR addresses them
- **#443** (filed) — future: aggregate dashboard telemetry across instances
- **#444** (filed) — future: remove deprecated `/api/healthz`

## Architecture

### Fix 1: Drop upserts and dead columns from both registration tables

**Problem:** The `listeners` unique constraint `(app_key, instance_index, handler_method, topic)` cannot distinguish two listeners with the same handler method and topic but different predicates (e.g., `changed_to="on"` vs `changed_to="off"` on the same entity). The `ON CONFLICT` upsert silently merges them into one DB row, corrupting telemetry.

**Root cause (broader):** Both the `listeners` and `scheduled_jobs` tables use an upsert pattern (`ON CONFLICT ... DO UPDATE SET last_registered_at = ...`) to preserve `first_registered_at` across re-registrations. But `clear_registrations(app_key)` (`app_lifecycle_service.py:303-305`) deletes all rows for an app at startup before re-registration — so the upsert path is dead code. The `first_registered_at` and `last_registered_at` columns are write-only: nothing in `telemetry_query_service.py` or any route ever SELECTs them.

**Approach:** Clean up both tables:
1. Remove the upsert from both registration methods — use plain INSERT.
2. Drop `first_registered_at` and `last_registered_at` from both tables (dead columns).
3. Drop the UNIQUE constraints from both tables (served the upsert, now unnecessary).

**Changes:**
- New migration `004_drop_upsert_columns.py`: Uses the SQLite table-rebuild pattern from migration 003. For both tables:
  - Drop `first_registered_at` and `last_registered_at` columns
  - Drop `UNIQUE` constraints
- `command_executor.py` `_do_register_listener()`: Replace `INSERT ... ON CONFLICT ... DO UPDATE` with plain `INSERT INTO listeners (...) VALUES (...) RETURNING id`. Remove `first_registered_at`/`last_registered_at` from column list.
- `command_executor.py` `_do_register_job()`: Same — plain INSERT, remove timestamp columns.
- `registration.py` `ListenerRegistration`: Remove `first_registered_at` and `last_registered_at`.
- `registration.py` `ScheduledJobRegistration`: Remove `first_registered_at` and `last_registered_at`.
- `bus_service.py:107-122`: Stop passing timestamp fields.
- `scheduler_service.py:199-200`: Stop passing timestamp fields.

**Why drop the upsert instead of fixing the constraint:** The upsert only existed to preserve `first_registered_at` across re-registrations. Since `clear_registrations` deletes all rows before re-registration, and the timestamp columns are never read, both the upsert and the columns it serves are dead code.

### Fix 2: Dashboard errors — fix SQL columns and rename `timestamp` to `execution_start_ts` across all layers

**Problem:** Two independent bugs in `get_recent_errors()`:
1. SQL doesn't SELECT `listener_id` or `job_id` columns — the route falls back to `0` for both.
2. Route reads `err.get("timestamp", 0.0)` but the SQL column is `execution_start_ts` — always returns `0.0`.

The existing test mocks `get_recent_errors` with hand-crafted dicts containing the "correct" keys, hiding both bugs.

**Approach:** Fix both bugs. Rename the Pydantic model field from `timestamp` to `execution_start_ts` for consistency with the DB schema, and propagate the rename to the frontend TypeScript type. No backwards-compatibility shim needed.

**Changes:**
- `telemetry_query_service.py` `get_recent_errors()` — **both branches** (session-scoped and all-sessions):
  - Handler query: Add `hi.listener_id` to SELECT list
  - Job query: Add `je.job_id` to SELECT list
  - Session-scoped handler query: Add `AND hi.listener_id IS NOT NULL` filter (consistency with all-sessions branch, which already has this filter from migration 003's nullable FK)
- `web/models.py`: Rename `HandlerErrorEntry.timestamp` → `execution_start_ts` and `JobErrorEntry.timestamp` → `execution_start_ts`
- `routes/telemetry.py` `dashboard_errors()`: Change `err.get("timestamp", 0.0)` → `err.get("execution_start_ts", 0.0)` in both handler and job branches
- `frontend/src/api/endpoints.ts`: Rename `DashboardErrorEntry.timestamp` → `execution_start_ts`
- `frontend/src/components/dashboard/error-feed.tsx`: Update references from `.timestamp` to `.execution_start_ts`
- `tests/integration/test_web_api.py`: Replace mock-based test with real-SQL integration test. Assert independently: (a) `listener_id`/`job_id` > 0, (b) `execution_start_ts` is a realistic epoch-seconds value

### Fix 3: SPA catch-all path check — use `is_relative_to` with resolved paths

**Problem:** `_SPA_DIR` is not resolved. When the package is installed via editable install (symlink), `candidate.resolve()` produces a path outside `_SPA_DIR`'s unresolved parents, so the containment check always fails and static files fall through to `index.html`.

**Approach:** Resolve both sides and use `Path.is_relative_to()` (available since Python 3.9, project requires 3.11+).

**Changes:**
- `web/app.py`: Replace `_SPA_DIR in candidate.resolve().parents` with `candidate.resolve().is_relative_to(_SPA_DIR.resolve())`

### Fix 4: Scheduler auto-generated names — add trigger `__str__` and include in name

**Problem:** `ScheduledJob.__post_init__` generates names using only `callable.__name__`. Two jobs with the same callable but different triggers collide with `ValueError`.

**Prerequisite:** `IntervalTrigger` and `CronTrigger` are plain classes with no `__str__` method. The default `object.__repr__` produces memory addresses, which are non-deterministic and unreadable. Must add `__str__` to both trigger classes before using them in name generation.

**Approach:** Add `__str__` to trigger classes, then include the trigger string in auto-generated names.

**Changes:**
- `scheduler/classes.py` `IntervalTrigger`: Add `__str__` returning `f"interval:{self.interval.in_seconds()}s"`
- `scheduler/classes.py` `CronTrigger`: Add `__str__` returning `f"cron:{self.cron_expression}"`
- `scheduler/classes.py` `ScheduledJob.__post_init__`: When `name` is empty, generate as `f"{callable_name}:{self.trigger}"` instead of just `callable_name`

**Edge case:** If trigger is also identical (same callable, same trigger), the collision is correct — it truly is the same logical job. The existing `if_exists="skip"` + `matches()` check handles this correctly.

### Fix 5: Remove dead bus metrics endpoint

**Problem:** `GET /bus/metrics` returns hardcoded zeros. Nothing calls it. The dashboard uses `/api/telemetry/dashboard/kpis` instead.

**Approach:** Remove the endpoint and its response model.

**Changes:**
- `routes/bus.py`: Remove `get_bus_metrics_summary()` function
- `web/models.py`: Remove `BusMetricsSummaryResponse` class
- Remove any tests that assert the hardcoded zeros

### Fix 6: Remove unused `GET /apps/{app_key}` endpoint

**Problem:** The endpoint returns only the first instance for multi-instance apps. Investigation confirmed no frontend component calls it — the app detail page uses `/apps/manifests` and telemetry endpoints instead.

**Approach:** Remove the dead endpoint rather than fixing it. If a multi-instance lookup is needed later, it can be designed properly at that point.

**Changes:**
- `routes/apps.py`: Remove `get_app()` function
- `web/models.py`: Remove `AppInstanceResponse` if no other route uses it (check `get_apps()` response model first — `AppStatusResponse.apps` uses `list[AppInstanceResponse]`, so the model stays)
- Remove any tests for this endpoint

### Fix 7: Dashboard graceful degradation with specific exception handling

**Problem:** `dashboard_kpis` and `dashboard_errors` propagate DB exceptions as raw 500s. `dashboard_app_grid` already has try/except but catches bare `Exception`, which swallows programming errors (`TypeError`, `AttributeError`) that should crash loudly during development.

**Approach:** Add graceful degradation to `dashboard_kpis` and `dashboard_errors`, and narrow the exception type across all three dashboard endpoints to `sqlite3.Error` (the actual failure mode: DB locked, corrupted, I/O errors).

**Changes:**
- `routes/telemetry.py` `dashboard_kpis()`: Wrap `get_global_summary()` in `try/except sqlite3.Error`; on failure, return zeroed `DashboardKpisResponse` and log warning.
- `routes/telemetry.py` `dashboard_errors()`: Wrap `get_recent_errors()` in `try/except sqlite3.Error`; on failure, return empty `DashboardRecentErrorsResponse` and log warning.
- `routes/telemetry.py` `dashboard_app_grid()`: Narrow existing `except Exception` to `except sqlite3.Error` for consistency.

## Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Fix 1 migration drops constraints + columns from both tables | Could allow duplicate rows during a session; loses registration timestamps | `clear_registrations` wipes rows at startup; within a session, each `Listener`/`ScheduledJob` has a unique in-memory ID preventing logical duplicates. Timestamps were write-only — nothing reads them |
| Fix 2 field rename (`timestamp` → `execution_start_ts`) | Frontend type change | Updated in same PR; no external consumers |
| Fix 4 name format change | Existing `if_exists="skip"` callers match on name | Only affects auto-generated names; explicit `name=` callers unaffected. Cross-restart name stability ensured by deterministic trigger `__str__` |

## Test plan

Each fix includes a regression test:

1. **Fix 1:** Register two listeners with same handler+topic but different predicates → verify two distinct DB rows with separate invocation counts. Verify both tables lack `first_registered_at`/`last_registered_at` columns. Verify job registration also uses plain INSERT.
2. **Fix 2:** Two independent assertions in a real-SQL integration test (no mocking): (a) `listener_id`/`job_id` > 0, (b) `execution_start_ts` is a realistic epoch-seconds value (not 0.0)
3. **Fix 3:** Unit test for editable-install symlink case + path-traversal test (`GET /../../../etc/passwd` → 404)
4. **Fix 4:** Register same callable twice with different triggers → verify both succeed with distinct auto-generated names; verify `if_exists="skip"` still works for truly identical jobs
5. **Fix 5:** Verify `GET /bus/metrics` returns 404 (or is not in router)
6. **Fix 6:** Verify `GET /apps/{app_key}` returns 404 (or is not in router)
7. **Fix 7:** Mock `sqlite3.Error` from telemetry service → verify all three dashboard endpoints return zeroed/empty responses with 200; verify `TypeError` still propagates as 500
