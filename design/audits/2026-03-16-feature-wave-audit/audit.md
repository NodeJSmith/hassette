# Codebase Audit: Feature Wave (8b9390d..3c40430)

**Date:** 2026-03-16
**Scope:** 20 commits adding DatabaseService, CommandExecutor, DataSyncService decomposition, SQLite write queue, session lifecycle migration, startup race fixes
**Files changed:** 181 (+13,551 / -1,856 lines)

## Methodology

Four parallel deep-dives (database layer, service lifecycle, owner/identity model, dead code & test gaps) followed by cross-scope verification of findings.

## Critical (runtime bugs)

### 1. Scheduler API ignores `instance_index` filter

**Location:** `src/hassette/web/routes/scheduler.py:42-44`

The `/scheduler/jobs` endpoint accepts `instance_index` as a query param but never uses it in filtering. Multi-instance apps return jobs from all instances. The bus equivalent (`/bus/listeners`) handles this correctly via `telemetry.get_listener_summary(app_key=app_key, instance_index=instance_index)`.

**Impact:** Incorrect data returned for multi-instance apps in the scheduler API.

### 2. Hardcoded `instance_index=0` in app detail partials

**Location:** `src/hassette/web/ui/partials.py:136,147`

`app_detail_listeners_partial` and `app_detail_jobs_partial` hardcode `instance_index=0`. Cross-check confirmed these ARE referenced in `app_instance_detail.html` templates (lines 121, 130) for initial page loads. Live HTMX updates use the correct instance-aware endpoints, so this only affects the first render.

**Impact:** Initial page load shows wrong data for non-zero instance indexes.

## High (open bugs confirmed)

### 3. Polling-based `wait_for_ready` race window (bug #314)

**Location:** `src/hassette/utils/service_utils.py:8-39`

100ms polling loop instead of event-based waits. Creates timing-dependent race windows and up to 100ms startup latency per dependency chain. 5 call sites across CommandExecutor, StateProxy, WebApiService.

### 4. ServiceWatcher doesn't validate readiness after restart (bug #315)

**Location:** `src/hassette/core/service_watcher.py:177-189`

Listens for RUNNING status but never checks `mark_ready()`. A service that crashes between RUNNING and ready appears recovered but is actually stuck.

### 5. No coordination for cascading service failures during shutdown (bug #318)

CommandExecutor correctly flushes before DatabaseService shuts down in the normal path. But if a service crashes mid-shutdown (not clean ordering), `submit()` raises RuntimeError. The risk is real but narrow — only triggered by abnormal shutdown sequences.

## Medium (test & documentation gaps)

### 6. No migration downgrade test

**Location:** `src/hassette/migrations/versions/001_initial_schema.py`

Upgrade path tested; downgrade never exercised. Schema is correct but untested reverse path.

### 7. Sentinel ID filtering untested

**Location:** `src/hassette/core/command_executor.py:503-518`

Records with `listener_id=0` or `session_id=0` are silently dropped (correct behavior), but no test verifies this filtering under startup race conditions.

### 8. Inconsistent `mark_ready` timing across services

Some services mark ready in `on_initialize()` (early), others in `serve()` (late). No documented convention for when to use which approach.

## Clean areas (verified, no action needed)

- **Database write queue:** solid single-writer serialization via `asyncio.Queue`, no production bypass paths
- **DataSyncService decomposition:** completely clean — no dead code, orphaned imports, or stale references
- **Test coverage for new services:** all 8 new source files have corresponding unit and/or integration tests
- **Migration schema:** correct FK ordering, proper WAL/pragma config, safe downgrade SQL
- **Owner/identity model (core):** PR #336 correctly fixed the `owner_id`/`app_key` mismatch in scheduler and bus services

## Audit details

### Database layer

- WriteQueue architecture is sound — single-writer via `asyncio.Queue`, drained by `_db_write_worker()`
- Only 4 files import aiosqlite; all production writes go through the queue
- Session lifecycle (`_create_session`, `_finalize_session`, `_mark_orphaned_sessions`) all use `submit()`/`enqueue()`
- SQLite pragmas (WAL, busy_timeout=5000, foreign_keys=ON) are appropriate

### Service lifecycle

- 15 services started concurrently via `_start_resources()`
- Shutdown is LIFO (reversed registration order) — correct for dependency ordering
- CommandExecutor startup races (PR #330) properly fixed with `_safe_session_id()` sentinel pattern
- `wait_for_ready()` guards added at all critical dependency points

### Owner/identity model

- Two separate identity schemes: `owner_id` (runtime lifecycle) vs `app_key + instance_index` (database/API)
- PR #336 fixed mismatches where `owner` was used instead of `owner_id` in filters, and `owner` instead of `app_key` in DB registrations
- Remaining issues are in the web/API layer (findings #1 and #2 above)

### Dead code & test gaps

- DataSyncService completely removed — no references remain in source
- All new services have test files with integration and/or unit coverage
- Test utilities properly updated to reference new service classes
