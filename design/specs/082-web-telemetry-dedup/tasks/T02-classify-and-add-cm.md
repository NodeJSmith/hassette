---
task_id: "T02"
title: "Classify 17 DB_ERRORS sites and add db_degrades_to (#1108a)"
status: "done"
depends_on: ["T01"]
implements: ["FR#3", "FR#4", "AC#3"]
---

## Summary
Foundation for #1108a. First produce the per-site classification table for all 17 `except
DB_ERRORS` sites (this drives the migration in T03), then add the `db_degrades_to(response)`
context manager to `web/dependencies.py` with a unit test. The CM is added but not yet adopted by
handlers — that is T03 — so the suite stays green (an unused CM changes nothing).

## Target Files
- modify: `src/hassette/web/CLAUDE.md` — add the 17-site classification table as a section; this is
  the planning artifact T03 reads (commit it here, not a scratch note)
- modify: `src/hassette/web/dependencies.py` (add `db_degrades_to`)
- read: `design/specs/082-web-telemetry-dedup/design.md` (`## Architecture → #1108a`)
- read: all 6 route files (`apps.py`, `bus.py`, `executions.py`, `logs.py`, `scheduler.py`,
  `telemetry.py`) under `src/hassette/web/routes/` to classify every site
- create/modify: a unit test for `db_degrades_to`

## Prompt
**Step 1 — classification table (before any handler code).** Read every `except DB_ERRORS` site
across `src/hassette/web/routes/*.py` (17 occurrences across 6 files: `telemetry.py` x11,
`executions.py` x2, `apps.py`/`bus.py`/`logs.py`/`scheduler.py` x1). For each, record: file:line,
endpoint, the status code it sets on failure (503 or none/200), the default it returns, and its
category:
- **A** — query is the whole handler, failure default equals the return value, nothing after the
  query. One-line wrap.
- **B** — code after the query must be skipped on failure (criterion: *would it run incorrectly
  against the default?*). Known: `telemetry_status` (`telemetry.py:66`), `app_health`
  (`telemetry.py:128`), `bus.py:get_listener_metrics`, `telemetry.py:app_listeners` (the last two
  call `live_execution_counts()` outside the current try).
- **C — EXCLUDED** — catches `DB_ERRORS`, logs, returns HTTP 200 with partial/empty data, never
  sets 503. Known: `apps.py:get_app_manifests`, the three `dashboard_app_grid` sub-queries
  (`telemetry.py:319,334,338`). These have a non-DB "spine" from `runtime.get_all_manifests_snapshot()`.
- **D — EXCLUDED** — multi-failure-mode: `executions.py:get_execution_logs` (503 for the record
  fetch; silent `retention_expired=False` for the retention check via `check_retention_expired_uuid4`).

Commit the table into the "DB_ERRORS Catch Pattern" area of `web/CLAUDE.md` (T03 reads it there).
Note that `bus.py:get_listener_metrics` is category B but is intentionally **deferred to #1095**
(T05), not migrated in #1108a.

**Step 2 — add the CM.** Add `db_degrades_to(response)` to `src/hassette/web/dependencies.py`
(next to `DB_ERRORS` at line 43). It is a `@contextmanager` that yields, and on `except DB_ERRORS`
logs a warning (`exc_info=True`) and sets `response.status_code = 503`. It does NOT swallow-and-
return; callers pre-initialize their default and return at the tail. Match the design's
`## Architecture → #1108a` sketch. Do NOT migrate any handler in this task.

**Step 3 — unit test.** Add a unit test that, given a fake `Response`, confirms `db_degrades_to`:
catches a `DB_ERRORS` member and sets `status_code = 503`; lets a success path through without
touching status; does not suppress non-`DB_ERRORS` exceptions.

## Focus
- `DB_ERRORS = (sqlite3.Error, OSError, ValueError, TimeoutError)` at `dependencies.py:43`. In
  T02 the CM still catches `DB_ERRORS` — the swap to `TelemetryUnavailableError` is T04.
- `Response` is FastAPI's `starlette.responses.Response`; the CM takes it and mutates
  `status_code`. Use the existing import style in `dependencies.py`.
- Keep the warning message generic but informative; the handler-specific message can stay at the
  call site if needed, but the design centralizes the log into the CM — prefer one message in the CM.
- Adding an unused CM must not change any test outcome; do not touch handlers here.

## Verify
- [ ] FR#3: a committed classification table sorts all 17 sites into A/B/C/D with file:line,
      status, and default per site; `get_listener_metrics` is marked deferred to #1095.
- [ ] FR#4: `db_degrades_to(response)` exists in `dependencies.py`, catches `DB_ERRORS`, logs with
      `exc_info`, sets 503, and does not force a return.
- [ ] AC#3: a unit test confirms the CM sets 503 on a `DB_ERRORS` member, passes success through
      untouched, and does not suppress unrelated exceptions.
