---
task_id: "T05"
title: "Reorganize backend telemetry test files"
status: "done"
depends_on: ["T01", "T04"]
implements: ["FR#10", "AC#7"]
---

## Summary

Reorganize `test_telemetry_query_service.py` (870 lines) and `test_telemetry_query_service_misc.py` (520 lines) into smaller files grouped by concern. The UNION method tests were already moved to `test_union_queries.py` in T04. This task splits the remaining tests into domain-focused files. `test_telemetry_query_service_aggregates.py` is out of scope — already well-organized.

## Target Files

- create: `tests/integration/telemetry/test_listener_queries.py`
- create: `tests/integration/telemetry/test_job_queries.py`
- create: `tests/integration/telemetry/test_execution_queries.py`
- create: `tests/integration/telemetry/test_session_queries.py`
- create: `tests/integration/telemetry/test_query_helpers.py`
- delete: `tests/integration/telemetry/test_telemetry_query_service.py`
- delete: `tests/integration/telemetry/test_telemetry_query_service_misc.py`
- read: `tests/integration/telemetry/conftest.py`
- read: `tests/integration/telemetry/helpers.py`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

Split the two large test files into concern-grouped files. Read each file fully first to understand the test class organization.

**From `test_telemetry_query_service.py`** (870 lines):
- `test_listener_queries.py` — `TestGetListenerSummary` and any listener-specific tests
- `test_job_queries.py` — `TestGetJobSummary` and job-specific tests
- `test_execution_queries.py` — `TestGetExecutions*`, coherence checks, execution-by-id tests
- `test_session_queries.py` — session list, session summary, health check tests

**From `test_telemetry_query_service_misc.py`** (520 lines):
- `test_query_helpers.py` — `TestSourceTierClause` and other helper unit tests
- Remaining tests distribute to the domain files above based on which query method they test
- UNION method tests (`get_app_recent_activity`) were already moved to `test_union_queries.py` in T04

All files share `conftest.py` and `helpers.py` — do not duplicate fixtures.

Delete the two original files after all tests are distributed.

Run the full telemetry test suite to verify no tests were lost: `ptest -- tests/integration/telemetry -v -n 4`. Compare the test count before and after.

## Focus

- Count tests before splitting: `ptest -- tests/integration/telemetry -v --collect-only 2>&1 | tail -5`. Do the same after. The counts must match.
- Do NOT touch `test_telemetry_query_service_aggregates.py` — it's out of scope.
- Some test classes in `misc` are grab-bag — inspect each to determine the right destination file.
- Preserve all test markers, decorators, and parametrize calls verbatim.

## Verify

- [ ] FR#10: `test_telemetry_query_service.py` and `test_telemetry_query_service_misc.py` no longer exist; tests are distributed across domain files
- [ ] AC#7: `ptest -- tests/integration/telemetry -v -n 4` passes with the same test count as before the split
