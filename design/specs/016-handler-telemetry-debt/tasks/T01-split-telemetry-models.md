---
task_id: "T01"
title: "Split telemetry_models.py into domain files"
status: "done"
depends_on: []
implements: ["FR#7", "AC#4"]
---

## Summary

Split `src/hassette/schemas/telemetry_models.py` (420 lines, 16 model classes) into 5 domain-grouped sibling files in `schemas/`. Create the new files with the correct classes, update all 31 importers (15 source + 16 test files) to point at the specific submodule, remove the vestigial telemetry re-exports from `schemas/__init__.py`, and delete the original file. This is the highest blast-radius task — 31 import-path updates — but entirely mechanical.

## Target Files

- create: `src/hassette/schemas/listener_models.py`
- create: `src/hassette/schemas/job_models.py`
- create: `src/hassette/schemas/execution_models.py`
- create: `src/hassette/schemas/summary_models.py`
- create: `src/hassette/schemas/log_models.py`
- delete: `src/hassette/schemas/telemetry_models.py`
- modify: `src/hassette/schemas/__init__.py`
- read: `design/specs/016-handler-telemetry-debt/design.md`
- modify: `src/hassette/core/telemetry/execution_queries.py`
- modify: `src/hassette/core/telemetry/helpers.py`
- modify: `src/hassette/core/telemetry/registration_queries.py`
- modify: `src/hassette/core/telemetry/summary_queries.py`
- modify: `src/hassette/core/telemetry/repository.py`
- modify: `src/hassette/core/command_executor.py`
- modify: `src/hassette/cli/commands/app.py`
- modify: `src/hassette/cli/commands/job.py`
- modify: `src/hassette/cli/commands/listener.py`
- modify: `src/hassette/web/routes/telemetry.py`
- modify: `src/hassette/web/routes/scheduler.py`
- modify: `src/hassette/web/mappers.py`
- modify: `src/hassette/web/utils.py`
- modify: `src/hassette/test_utils/web_helpers.py`
- modify: `tests/unit/test_telemetry_models.py`
- modify: `tests/unit/test_source_tier_models.py`
- modify: `tests/unit/test_model_types.py`
- modify: `tests/unit/core/test_telemetry_models.py`
- modify: `tests/unit/core/test_log_records.py`
- modify: `tests/unit/core/test_unified_execution.py`
- modify: `tests/unit/web/test_mappers.py`
- modify: `tests/integration/telemetry/test_telemetry_query_service.py`
- modify: `tests/integration/telemetry/test_telemetry_query_service_misc.py`
- modify: `tests/integration/telemetry/test_telemetry_query_service_aggregates.py`
- modify: `tests/integration/telemetry/test_health_aggregates_and_global_listeners.py`
- modify: `tests/integration/telemetry/test_global_jobs_and_service_info.py`
- modify: `tests/integration/web_api/test_endpoints.py`
- modify: `tests/integration/web_api/test_telemetry.py`
- modify: `tests/e2e/mock_fixtures.py`
- modify: `tests/system/test_cli_smoke.py`
- modify: `src/hassette/schemas/domain_models.py`

## Prompt

Split `src/hassette/schemas/telemetry_models.py` into 5 flat sibling files in the same directory. See the design doc's "Backend: telemetry_models split (AC#4)" section for the exact class-to-file mapping:

| New file | Classes |
|---|---|
| `listener_models.py` | ListenerSummary, ListenerGlobalStats, HandlerErrorRecord, SlowHandlerRecord |
| `job_models.py` | JobSummary, JobGlobalStats, JobErrorRecord |
| `execution_models.py` | Execution, ActivityFeedEntry, AppLastError |
| `summary_models.py` | AppHealthSummary, GlobalSummary, SessionRecord, SessionSummary |
| `log_models.py` | LogRecord, BlockingEvent |

Each new file gets the module docstring, imports, and type aliases it needs. `_BlockingTier` moves to `log_models.py`. `summary_models.py` imports `ListenerGlobalStats` from `listener_models` and `JobGlobalStats` from `job_models`.

Update all 31 importers to use the new paths (e.g., `from hassette.schemas.telemetry_models import ListenerSummary` → `from hassette.schemas.listener_models import ListenerSummary`).

Remove the telemetry model re-exports from `schemas/__init__.py` (lines 25-42 and corresponding `__all__` entries). Keep re-exports for `app_snapshots`, `domain_models`, `live_counts`, and `query_constants`.

Delete `telemetry_models.py` after all imports are updated.

Update the module docstring in `src/hassette/schemas/domain_models.py` — it references `telemetry_models.py` by name. Update to list the new submodule files.

Do NOT introduce a package directory — use flat sibling files.

## Focus

- This is a mechanical task but has the highest blast radius (31 files). Use pyright to catch any missed imports.
- `summary_models.py` has a cross-import: `GlobalSummary` embeds `ListenerGlobalStats` and `JobGlobalStats`. This is one-directional — no cycle risk.
- Zero consumers use `from hassette.schemas import` (verified) — removing the re-exports is safe.
- Preserve all docstrings, comments, and type annotations verbatim.

## Verify

- [ ] FR#7: `telemetry_models.py` no longer exists; 5 new files contain all 16 classes
- [ ] AC#4: `prek -a` passes (pyright catches any broken imports); `ptest -- tests/unit tests/integration -n 4` passes
