---
task_id: "T14"
title: "Final cleanup and verification"
status: "planned"
depends_on: ["T07", "T08", "T12", "T13"]
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
- CSS lint tools if applicable

**Step 3: Verify no stale references:**
- `grep -r "handler_invocations\|job_executions" src/hassette/ --include="*.py"` — should return zero (except maybe comments)
- `grep -r "registration_task" src/hassette/ --include="*.py"` — zero
- `grep -r "_listener_id_seq\|JOB_ID_SEQ" src/hassette/ --include="*.py"` — zero
- `grep -r "RegistrationTracker" src/hassette/ --include="*.py"` — zero
- `grep -r "mark_registered" src/hassette/ --include="*.py"` — zero
- `grep -r "dropped_no_session\|droppedNoSession" src/hassette/ frontend/src/` — zero

**Step 4: Verify schema:**
- Run migrations on fresh DB, inspect with `sqlite3` — confirm `executions` table exists with correct columns, indexes, CHECK constraints
- Confirm `PRAGMA user_version` is set correctly
- Confirm no `alembic_version` table exists

**Step 5: Verify `listeners` and `scheduled_jobs` tables** are separate with distinct schemas (FR#2).

## Focus
- This task should NOT write new code unless fixing issues found during verification.
- If any verification step fails, the fix belongs in the originating task — re-open that task rather than patching here.
- The `registration.py` dataclass fields should be `owner_key` (from T01) — verify.

## Verify
- [ ] FR#2: `listeners` and `scheduled_jobs` tables exist as separate tables with distinct schemas
- [ ] FR#19: New columns (trigger_mode, retry_count, attempt_number, args_json, kwargs_json) present in `executions` table
- [ ] AC#1: Full test suite passes (`uv run nox -s dev -- -n 2`)
- [ ] AC#4: Fresh DB has correct structure (unified executions, PRAGMA user_version, no alembic_version)
- [ ] AC#5: `uv run pyright` passes with zero errors
