---
task_id: "T05"
title: "Surface job mode and live counts in the API and CLI"
status: "planned"
depends_on: ["T01", "T02", "T03"]
implements: ["FR#11", "AC#11"]
---

## Summary

Expose each job's persisted `mode` and live `suppressed`/`dropped` counts through the jobs API and
the `hassette job` CLI. Add the fields to `JobSummary`, read the live counts from the per-job guard
in `enrich_jobs_with_heap`, ensure both jobs routes carry them, surface `mode` in the CLI job table,
and regenerate the OpenAPI/TS schemas. Frontend display is T06.

## Prompt

Implement design.md "Architecture §6 (Web + UI surfacing)" — the backend half plus CLI. Mirror the
listener fields on `ListenerWithSummary` (`web/models.py:331`).

1. **`src/hassette/core/telemetry_models.py` — `JobSummary`** (line 145): add `mode: str = "single"`,
   `suppressed_count: int = 0`, `dropped_count: int = 0`. (The DB `mode` column is selected in T03;
   confirm the query maps it onto the model.)

2. **`src/hassette/web/utils.py` — `enrich_jobs_with_heap`** (NEW logic): the function today enriches
   only `next_run`/`fire_at`/`jitter` from the live-heap `ScheduledJob` snapshot keyed by `db_id`.
   Add reading of `job.guard.suppressed`/`job.guard.dropped` from the same snapshot, mapping onto
   `suppressed_count`/`dropped_count`, defaulting to `(0, 0)` when no heap entry exists. This depends
   on the `guard` field added in T01.

3. **Both jobs routes** carry the enriched fields (GAP — design named only `scheduler.py`):
   - `src/hassette/web/routes/scheduler.py` `GET /scheduler/jobs` (already calls `enrich_jobs_with_heap`).
   - `src/hassette/web/routes/telemetry.py` `GET /app/{app_key}/jobs` (line 220, also returns
     `JobSummary` and imports `enrich_jobs_with_heap`). Confirm both flow `mode` + counts.

4. **`src/hassette/cli/commands/job.py`** (GAP — CLI job table): add a `mode` column to
   `JOB_LIST_COLUMNS` so `hassette job` shows each job's mode, mirroring the existing `trigger_type`
   column (line 15). (Counts are optional for the CLI — at minimum surface `mode`.)

5. **Regenerate schemas/types**: run `uv run python scripts/export_schemas.py --types` (regenerates
   `openapi.json`, `ws-schema.json`, `generated-types.ts`, `ws-types.ts`). In a worktree, run
   `cd frontend && npm install` first (see `.claude/rules/frontend-worktree.md`). Commit the
   regenerated artifacts — CI checks freshness.

6. **Tests (same task).**
   - JobSummary model tests (GAP): `tests/unit/test_telemetry_models.py` and
     `tests/unit/core/test_telemetry_models.py` — assert the new fields and defaults.
   - Backend route test: `GET /scheduler/jobs` (and the per-app route) returns `mode` and live
     counts; a job with guard activity reports non-zero suppressed/dropped, a fresh job reports `(0,0)`.

Do NOT implement the frontend display (T06) — but DO regenerate the types it consumes.

## Focus

- Listener parity reference: `ListenerWithSummary` (`web/models.py:331`: `mode`, `suppressed_count`,
  `dropped_count`), the listener mapper (`web/mappers.py:177-225`), and the live-count source
  `bus_service.live_execution_counts()` (`bus_service.py:194`). NOTE: jobs do NOT use a mapper —
  they enrich directly in `enrich_jobs_with_heap`, so the live counts come from the heap snapshot's
  `ScheduledJob.guard`, not a separate `live_execution_counts` method. Do not add a job mapper.
- `enrich_jobs_with_heap` is in `src/hassette/web/utils.py` (today enriches `next_run`/`fire_at`/
  `jitter` only); it receives the DB `JobSummary` rows and the live-heap `ScheduledJob` list and
  joins by `db_id`.
- Both routes import `enrich_jobs_with_heap`; `web/routes/telemetry.py:220` is the second one the
  design's Impact missed.
- CLI: `cli/commands/job.py` builds `JOB_LIST_COLUMNS` (line ~11) and renders via `render_table`;
  add a `Column("mode", "Mode", ...)`. `JobSummary.model_validate` is used at line 77 — extra fields
  flow automatically once on the model.
- Schema regen + worktree npm: `.claude/rules/frontend-worktree.md` and CLAUDE.md "Schema
  regeneration". The pre-push hook (`tools/check_schemas_fresh.py`) and CI check freshness — commit
  regenerated files.
- Web conventions: `src/hassette/web/CLAUDE.md` (response_model on every route, DB_ERRORS catch).

## Verify

- [ ] FR#11: `JobSummary` exposes `mode`, `suppressed_count`, `dropped_count`; live counts come from the per-job guard via `enrich_jobs_with_heap`, defaulting to `(0,0)`.
- [ ] AC#11: `GET /api/scheduler/jobs` (and `GET /api/app/{app_key}/jobs`) return each job's `mode` and live suppressed/dropped counts; `hassette job` shows the mode column; OpenAPI/TS types regenerated.
