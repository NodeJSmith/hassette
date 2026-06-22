---
task_id: "T05"
title: "Consolidate summary queries 4→2 + guard + test audit (#1095)"
status: "planned"
depends_on: ["T04"]
implements: ["FR#11", "FR#12", "FR#13", "AC#8", "AC#9"]
---

## Summary
Collapse the two pairs of near-identical CTE query methods into one parameterized method each,
delete the `get_all_*` variants, migrate all production and test callers, tighten the `bus.py`
dispatch guard against an empty-string `app_key` data-escalation, and migrate
`bus.py:get_listener_metrics` to `db_degrades_to` (deferred from T03). The production change and
the test migration land together so the suite is never red.

## Target Files
- modify: `src/hassette/core/telemetry/registration_queries.py` (merge the two pairs; delete
  `get_all_listeners_summary`, `get_all_jobs_summary`)
- modify: `src/hassette/web/routes/bus.py` (`if not app_key:` → `if app_key is None:`; collapse the
  if/else dispatch to one unified call; migrate `get_listener_metrics` to `db_degrades_to`)
- modify: `src/hassette/web/routes/telemetry.py`, `src/hassette/web/routes/scheduler.py` (callers of
  the retiring methods)
- modify: `src/hassette/test_utils/web_mocks.py` (mock setup for the four methods)
- modify: `tests/e2e/mock_fixtures.py` (direct `AsyncMock` attribute assignment by retiring name,
  ~line 629)
- modify: the ~25 test call sites across `tests/integration/telemetry/` and
  `tests/integration/web_api/` (see Focus for the list; includes
  `tests/integration/telemetry/test_telemetry_timed_out.py`, which calls all four retiring methods)
- read: `design/specs/082-web-telemetry-dedup/design.md` (`## Architecture → #1095`)

## Prompt
1. **Consolidate the queries.** In `core/telemetry/registration_queries.py`:
   - Change `get_listener_summary` to `get_listener_summary(app_key=None, instance_index=None,
     since=None, source_tier="app")`. When `app_key is None`, omit the
     `WHERE app_key = :app_key AND instance_index = :instance_index` filter (and don't bind those
     params); `instance_index` is ignored in that case. When `app_key` is provided, behavior is
     identical to today.
   - Delete `get_all_listeners_summary` (its body becomes the `app_key is None` branch).
   - Apply the same change to `get_job_summary`, deleting `get_all_jobs_summary`.
   - The CTE body, SELECT list, JOINs, GROUP BY, and tier/since handling are identical between the
     pairs — only the WHERE filter and bound params differ. Keep them byte-identical.

2. **Migrate production callers.** `bus.py` (both listener variants), `telemetry.py`
   (`get_listener_summary`, `get_job_summary`), `scheduler.py` (`get_all_jobs_summary` →
   `get_job_summary()` with no `app_key`). Every former `get_all_*` call becomes the unified method
   with no `app_key` argument.

3. **Tighten the guard + migrate the handler.** In `bus.py`, change the dispatch guard from
   `if not app_key:` to `if app_key is None:` so an empty-string `?app_key=` cannot fall through to
   the all-apps path. Collapse the if/else into a single
   `get_listener_summary(app_key=app_key, instance_index=...)` call. Migrate
   `get_listener_metrics` to `db_degrades_to` in this same step (it was deferred from T03 to avoid
   double-touching). Add a test that `?app_key=` returns empty/422, not all-apps data.

4. **Migrate + audit tests.** Mechanical call-site changes (call changes, assertion identical) for
   most sites. The exception — a **dispatch-assertion audit**: grep all test files for
   `assert_called_once`, `assert_not_called`, `assert_called_with`, and `call_count` on
   `get_all_listeners_summary`, `get_all_jobs_summary`, `get_listener_summary`, `get_job_summary`.
   Rewrite these as **argument-based** assertions on the unified method (e.g.
   `get_listener_summary.assert_called_once_with(app_key=None, ...)` instead of asserting which
   method was dispatched). The known case is `tests/integration/web_api/test_telemetry.py:427-430`
   (`get_all_listeners_summary.assert_called_once()` + `get_listener_summary.assert_not_called()`).
   Also update `src/hassette/test_utils/web_mocks.py` (it stubs all four as attributes) and
   `tests/e2e/mock_fixtures.py:629` (direct `AsyncMock` attribute assignment by retiring name) —
   these are attribute assignments a call-site codemod will not catch.

## Focus
- A scripted rewrite (codemod/`sed` over the grep list) handles the mechanical call-site changes,
  but the dispatch-assertion rewrites and the `AsyncMock`/`web_mocks` attribute assignments are
  semantic and must be done by hand. Run the grep audit explicitly; do not assume the codemod found
  everything.
- Data-escalation guard: after consolidation, `get_listener_summary(app_key=None)` is a full-table
  scan. `if not app_key:` is falsy, so `?app_key=` (empty string) would route there. `if app_key
  is None:` closes that. This is a behavior tightening, not preservation — pin it with the new test.
- A deleted method on a `MagicMock`/`AsyncMock` auto-creates as a non-async attribute, so a missed
  `web_mocks.py`/`mock_fixtures.py` entry produces a confusing `await` failure, not a clean
  `AttributeError`. Update them explicitly.
- The four methods have heavy integration coverage (`test_telemetry_query_service.py`,
  `test_global_jobs_and_service_info.py`, `test_health_aggregates_and_global_listeners.py`,
  `test_telemetry_timed_out.py`, the `web_api` route tests). Run all of them.
- Run `uv run pyright`; at this point run `uv run nox -s system` and `uv run nox -s e2e`; confirm
  zero `scripts/export_schemas.py --types` diff. Use explicit `-n N`, never `-n auto`.

## Verify
- [ ] FR#11: two methods (`get_listener_summary`, `get_job_summary`) with optional `app_key`/
      `instance_index` replace four; `get_all_listeners_summary` and `get_all_jobs_summary` deleted;
      `app_key is None` omits the filter.
- [ ] FR#12: `bus.py` guard is `if app_key is None:`; `get_listener_metrics` migrated to
      `db_degrades_to`.
- [ ] FR#13: all production + ~25 test call sites updated; dispatch-assertion tests rewritten as
      argument-based; `web_mocks.py` and `tests/e2e/mock_fixtures.py` attribute assignments updated.
- [ ] AC#8: full suite green after consolidation; no reference to the deleted method names remains.
- [ ] AC#9: a test asserts `?app_key=` (empty string) returns empty/422, not all-apps data.
