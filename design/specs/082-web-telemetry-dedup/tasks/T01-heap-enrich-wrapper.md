---
task_id: "T01"
title: "Extract enrich_jobs_with_live_heap wrapper (#1107)"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "AC#1"]
---

## Summary
Collapse the duplicated "snapshot live scheduler heap → enrich DB rows → fall back to DB rows on
snapshot failure" block shared by the `all_jobs` and `app_jobs` routes into one helper in
`web/utils.py`. The underlying `enrich_jobs_with_heap` is already shared; only the wrapper around
it is duplicated. Behavior-preserving — the fallback exception set and warning are lifted verbatim.

## Target Files
- modify: `src/hassette/web/utils.py` (add `enrich_jobs_with_live_heap`)
- modify: `src/hassette/web/routes/scheduler.py` (`all_jobs`, ~lines 36-52)
- modify: `src/hassette/web/routes/telemetry.py` (`app_jobs`, ~lines 228-247)
- read: `design/specs/082-web-telemetry-dedup/design.md` (`## Architecture → #1107`)
- read: `tests/integration/web_api/test_telemetry_route.py` (existing heap-failure coverage)
- create/modify: a unit test for `enrich_jobs_with_live_heap` (co-located with web util tests)

## Prompt
Add `enrich_jobs_with_live_heap(db_jobs, scheduler_service)` to `src/hassette/web/utils.py`,
next to the existing `enrich_jobs_with_heap` (currently at `web/utils.py:16`). It must:
1. Call `scheduler_service.get_all_jobs()` once to snapshot the live heap.
2. On `OSError | RuntimeError | ValueError` from that call, log a warning (`exc_info=True`) and
   return `db_jobs` unchanged (the unenriched DB rows).
3. Otherwise return `enrich_jobs_with_heap(db_jobs, live_jobs)`.

Lift the exact exception tuple and warning text from the current inline blocks so behavior is
identical. Then replace the inline snapshot/enrich/fallback blocks in `all_jobs`
(`web/routes/scheduler.py`, ~lines 44-52) and `app_jobs` (`web/routes/telemetry.py`, ~lines
239-247) with a call to the helper. **Leave the DB fetch and its `except DB_ERRORS` handling in
each route** — that is #1108a's concern, and the two handlers fetch from different query methods
(`get_all_jobs_summary` vs `get_job_summary`).

Add a unit test that drives `enrich_jobs_with_live_heap` directly: one case where the snapshot
succeeds (rows enriched) and one where `get_all_jobs()` raises (returns the unenriched `db_jobs`).
Follow the design's `## Architecture → #1107` section.

## Focus
- `enrich_jobs_with_heap` signature: `(db_jobs: list[JobSummary], live_jobs: list[ScheduledJob]) -> list[JobSummary]`.
- `scheduler_service` is reachable via `SchedulerDep` in the routes; pass the service into the
  helper, not the snapshot — the helper owns the snapshot + fallback so the policy lives in one
  place.
- The existing tests in `tests/integration/web_api/test_telemetry_route.py` (e.g.
  `TestAppJobsEnrichmentHeapFailureDegrades`) already assert the heap-failure-degrades-to-DB-rows
  behavior for both endpoints. They must stay green unchanged — they are the pin.
- Do not alter the DB-fetch try/except in either route in this task.

## Verify
- [ ] FR#1: `enrich_jobs_with_live_heap` exists in `web/utils.py`, snapshots once, and returns
      unenriched `db_jobs` (with a warning log) on `OSError|RuntimeError|ValueError`.
- [ ] FR#2: `all_jobs` and `app_jobs` call the helper; no inline snapshot/enrich/fallback block
      remains; their DB-fetch `except DB_ERRORS` is untouched.
- [ ] AC#1: existing heap-failure route tests stay green; a new unit test exercises the helper's
      success and fallback paths.
