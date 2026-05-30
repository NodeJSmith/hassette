---
task_id: "T16"
title: "Final cleanup and verification"
status: "done"
depends_on: ["T09", "T10", "T14", "T15a", "T15b", "T15c", "T15d", "T15e", "T15f", "T15g", "T15h", "T15i", "T15j", "T15k", "T17"]
implements: ["FR#2", "FR#19", "AC#1", "AC#4", "AC#5"]
---

## Summary
Final pass — verify all behavioral invariants, run the full test suite, confirm no stale references, and ensure the schema matches expectations. This is the integration verification task, not a code-writing task.

## Prompt
**Step 1: Verify behavioral invariants** (from design doc):
- Write queue single-writer contract: all DB writes still flow through `database_service.submit()`
- Retention cleanup: hourly cleanup works with new table references
- Router dispatch: `Router.add_route()`/`dispatch()` unchanged
- CLI commands: `hassette status`, `hassette listener`, `hassette log` still work
- `source_tier` filtering: framework listeners filtered from user-facing views
- Session heartbeat and crash recording: `sessions` table lifecycle unchanged

**Step 2: Run full test suite:**
- `timeout 300 uv run nox -s dev -- -n 2` (unit + integration)
- `uv run pyright` (type checking)
- `cd frontend && npm run build` (frontend types)
- `uv run nox -s system` (Docker — full system suite; collection-only was verified in T15i, the GREEN run is owned here)
- `uv run nox -s e2e` (Playwright — full e2e suite; collection-only was verified in T15j, the GREEN run is owned here. AC#2)
- AC#3 manual verification: handlers page shows unified list, detail pages load, activity feed updates
- CSS lint tools if applicable

**Step 5b: Resolve deferred review observations** (from [[deferred-items]]):
- `summary_queries.get_log_records` uses `SELECT *` — switch to an explicit column list so a future `log_records` column can't silently leak into API responses (T10→T16 robustness nit; not a current leak).
- `executions` FK columns are `ON DELETE SET NULL` but the FK-mutex CHECK requires exactly one of `listener_id`/`job_id` non-null — deleting a listener/job that still has executions would `SET NULL` → CHECK violation. Benign (reconciliation only deletes childless registrations) but document the invariant or reconsider ON DELETE behavior (T09→T16).
- **AppSync review** (user-flagged): async-everywhere on the bus/scheduler public API breaks synchronous apps — they cannot `await self.bus.on_*`. Surface a plan (sync facades over async registration, or async-only app requirement + `AppSync` deprecation). This is a heads-up to the user, not necessarily an in-scope fix for this spec — flag it explicitly in the final summary.

**Step 3: Verify no stale references:**
- `grep -r "handler_invocations\|job_executions" src/hassette/ --include="*.py"` — zero (except comments)
- `grep -r "registration_task" src/hassette/ --include="*.py"` — zero
- `grep -r "_listener_id_seq\|JOB_ID_SEQ" src/hassette/ --include="*.py"` — zero
- `grep -r "RegistrationTracker" src/hassette/ --include="*.py"` — zero
- `grep -r "mark_registered" src/hassette/ --include="*.py"` — zero
- `grep -r "dropped_no_session\|droppedNoSession" src/hassette/ frontend/src/` — zero
- `grep -rn "HandlerInvocation\|JobExecution" src/hassette/cli/ --include="*.py"` — zero (CLI migrated to unified `Execution` in T17)

**Step 4: Verify schema:**
- Run migrations on fresh DB, inspect with `sqlite3` — confirm `executions` table with correct columns, indexes, CHECK constraints
- Confirm `PRAGMA user_version` is set correctly
- Confirm no `alembic_version` table exists

**Step 5: Verify `listeners` and `scheduled_jobs` tables** are separate with distinct schemas (FR#2).

## Focus
- This task should NOT write new code unless fixing issues found during verification.
- If any verification step fails, the fix belongs in the originating task — re-open that task rather than patching here.

## Verify
- [ ] FR#2: `listeners` and `scheduled_jobs` tables exist as separate tables with distinct schemas
- [ ] FR#19: New columns (trigger_mode, retry_count, attempt_number, args_json, kwargs_json) present in `executions` table
- [ ] AC#1: Full test suite passes (`uv run nox -s dev -- -n 2`)
- [ ] AC#4: Fresh DB has correct structure (unified executions, PRAGMA user_version, no alembic_version)
- [ ] AC#5: `uv run pyright` passes with zero errors
