---
task_id: "T03"
title: "Migrate category-A/B handlers to db_degrades_to + docs (#1108a)"
status: "planned"
depends_on: ["T02"]
implements: ["FR#5", "FR#6", "AC#2", "AC#4", "AC#5"]
---

## Summary
Adopt `db_degrades_to` at every category-A and category-B site from T02's classification table.
Category-A sites become a one-line wrap; category-B sites move their post-query work inside the
`with` block. Category-C and category-D sites are left untouched (their 200/partial status must not
change). Then document the pattern in `web/CLAUDE.md`. Behavior byte-for-byte identical.

## Target Files
- modify: `src/hassette/web/routes/telemetry.py` (category-A/B sites; NOT the 3 `dashboard_app_grid`
  sub-queries, NOT `app_jobs`'s already-handled fetch)
- modify: `src/hassette/web/routes/bus.py` (`get_listener_metrics` is category B but **deferred** —
  do NOT migrate here)
- modify: `src/hassette/web/routes/logs.py` (category A)
- modify: `src/hassette/web/routes/scheduler.py` (category A)
- modify: `src/hassette/web/CLAUDE.md` ("DB_ERRORS Catch Pattern" section)
- read: `design/specs/082-web-telemetry-dedup/design.md` (`## Architecture → #1108a`)
- read: the classification table committed in T02
- read: `tests/integration/web_api/test_telemetry_route.py`, `tests/integration/web_api/test_telemetry.py`

## Prompt
Using T02's classification table, migrate every **category-A** and **category-B** site to
`db_degrades_to` (imported from `hassette.web.dependencies`):

- **Category A** — replace `try: result = await q() except DB_ERRORS: log; status=503; return d`
  with:
  ```python
  result = <default>
  with db_degrades_to(response):
      result = await q()
  return result
  ```
- **Category B** — additionally move the post-query work **inside** the `with` block so it is
  skipped when the query raises. For `app_health` (`telemetry.py:128`), the `compute_error_rate`
  computation and `AppHealthResponse` construction go inside the block. For `telemetry_status`
  (`telemetry.py:66`), the success-path drop-counter reads and the `degraded=False` response go
  inside the block; the `degraded=True` default is returned at the tail. For `app_listeners`
  (`telemetry.py:app_listeners`), the `live_execution_counts()` call and the result mapping go
  inside the block.

**Do NOT touch:**
- Category C: `apps.py:get_app_manifests`, the three `dashboard_app_grid` sub-queries
  (`telemetry.py:319,334,338`) — they return 200, leave their `try/except` as-is.
- Category D: `executions.py:get_execution_logs` — leave as-is.
- `bus.py:get_listener_metrics` — deferred to #1095 (T05). Leave its explicit `try/except`.
- `app_jobs`/`all_jobs` heap-fetch handling already refactored in T01.

Then update the **"DB_ERRORS Catch Pattern"** section of `src/hassette/web/CLAUDE.md` to document:
(1) the minimal one-line-wrap shape; (2) the post-query-work shape (work inside the block); (3) an
explicit warning that any code between the `with` block and the tail return runs on **both**
success and failure paths against the pre-initialized default; (4) that the category-C/D sites are
intentional exceptions that do NOT use `db_degrades_to`.

## Focus
- The category-B restructure is the only non-mechanical part. For each B site, verify that nothing
  left outside the block reads the query result or assumes success. The criterion is "would this
  line run incorrectly against the default?"
- Each migrated site has an existing degradation test (503 + default). Run the affected test files
  and confirm they stay green — they are the pin. Category-C sites keep their existing 200-partial
  tests unchanged; do not modify those tests.
- Preserve the exact default object each handler returned (e.g. `AppHealthResponse(error_rate=0.0,
  ..., health_status=classify_health_bar(100.0))`) — pre-initialize it identically.
- Run `uv run pyright` after migration. At this unit boundary (#1108a complete) run
  `uv run nox -s system` and `uv run nox -s e2e`; confirm `scripts/export_schemas.py --types`
  produces zero diff.

## Verify
- [ ] FR#5: all category-A/B sites use `db_degrades_to`; category-B post-query work is inside the
      block; category-C/D and `get_listener_metrics` are untouched.
- [ ] FR#6: `web/CLAUDE.md` documents the minimal shape, post-query-work shape, the both-paths
      warning, and the category-C/D exceptions.
- [ ] AC#2: the classification table exists and no category-C/D site's HTTP status code changed.
- [ ] AC#4: existing per-route 503/default and 200/partial degradation tests stay green.
- [ ] AC#5: the "DB_ERRORS Catch Pattern" section reflects the four documented points.
