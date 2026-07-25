---
task_id: "T04"
title: "Add tests for untested UNION methods"
status: "done"
depends_on: ["T03"]
implements: ["FR#12", "AC#8"]
---

## Summary

Write integration tests for `get_per_app_activity_buckets` and `get_per_app_last_errors` — two UNION methods that currently have no dedicated test coverage. These tests validate the UNION arm builder introduced in T03 and serve as the regression safety net for the query extraction. Tests go in `tests/integration/telemetry/` using the existing `conftest.py` and `helpers.py` fixtures.

## Target Files

- create: `tests/integration/telemetry/test_union_queries.py`
- read: `src/hassette/core/telemetry/execution_queries.py`
- read: `tests/integration/telemetry/conftest.py`
- read: `tests/integration/telemetry/helpers.py`
- read: `tests/integration/telemetry/test_telemetry_query_service_misc.py`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

Create `tests/integration/telemetry/test_union_queries.py` with integration tests for the two untested UNION methods.

**`get_per_app_activity_buckets` tests:**
- Basic: insert executions across 2 apps, verify bucketed ok/err counts match
- Edge case: empty time range (`now <= since`) returns empty dict
- Edge case: single bucket covers entire range
- Cross-app: verify per-app isolation (app A's errors don't appear in app B's buckets)
- Source tier filtering: verify `source_tier="app"` excludes framework executions

**`get_per_app_last_errors` tests:**
- Basic: insert multiple errors for 2 apps, verify most recent error per app is returned
- Since-window filtering: errors outside the window are excluded
- Source tier filtering: verify `source_tier="app"` excludes framework-tier errors
- No errors: apps with only successful executions are excluded from the result

Use the existing `insert_execution`, `insert_listener`, `insert_job` helpers from `tests/integration/telemetry/helpers.py`. Follow the same patterns as `test_telemetry_query_service_misc.py` (which tests `get_app_recent_activity`, the third UNION method).

Also move the existing `get_app_recent_activity` tests from `test_telemetry_query_service_misc.py` into this file to consolidate all UNION method tests in one place. This is prep for T05 (backend test reorg).

## Focus

- These tests must pass against the refactored UNION methods (post-T03). If any test fails, it indicates the UNION arm builder has a bug.
- The `conftest.py` provides `query_service` (typed `TelemetryQueryService`) and `db` fixtures. `helpers.py` provides `insert_execution(db_svc, ...)`, `insert_listener(db_svc, ...)`, `insert_job(db_svc, ...)` where `db_svc` is a `DatabaseService`.
- `get_per_app_activity_buckets` returns `dict[str, list[tuple[int, int]]]` — key is app_key, value is list of (ok, err) tuples per bucket.
- `get_per_app_last_errors` returns `dict[str, AppLastError]` — key is app_key, value is a NamedTuple with `error_message`, `error_type`, `timestamp`.

## Verify

- [ ] FR#12: `get_per_app_activity_buckets` has at least 4 test cases covering basic, edge, cross-app, and source_tier
- [ ] FR#12: `get_per_app_last_errors` has at least 3 test cases covering basic, since-window, and source_tier
- [ ] AC#8: `ptest -- tests/integration/telemetry/test_union_queries.py -v` passes
