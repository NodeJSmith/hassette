---
task_id: "T02"
title: "Split web_helpers.py into domain files"
status: "done"
depends_on: ["T01"]
implements: ["FR#8", "AC#5"]
---

## Summary

Split `src/hassette/test_utils/web_helpers.py` (626 lines, 20 public factories) into 4 domain-grouped sibling files in `test_utils/`. Update all 16 importers, update `test_utils/__init__.py` re-exports, update the `check_test_factories.py` registry, and delete the original file. Depends on T01 because `web_helpers.py` imports from `telemetry_models` — those imports must already point at the new submodules.

## Target Files

- create: `src/hassette/test_utils/web_manifest_helpers.py`
- create: `src/hassette/test_utils/web_job_helpers.py`
- create: `src/hassette/test_utils/web_response_helpers.py`
- create: `src/hassette/test_utils/web_telemetry_helpers.py`
- delete: `src/hassette/test_utils/web_helpers.py`
- modify: `src/hassette/test_utils/__init__.py`
- modify: `src/hassette/test_utils/web_mocks.py`
- modify: `tools/check_test_factories.py`
- modify: `tests/e2e/mock_fixtures.py`
- modify: `tests/integration/telemetry/test_global_jobs_and_service_info.py`
- modify: `tests/integration/web_api/test_endpoints.py`
- modify: `tests/integration/web_api/test_telemetry_route.py`
- modify: `tests/integration/web_api/test_trigger_job.py`
- modify: `tests/unit/cli/test_client.py`
- modify: `tests/unit/cli/test_commands_app.py`
- modify: `tests/unit/cli/test_commands_job.py`
- modify: `tests/unit/cli/test_commands_listener.py`
- modify: `tests/unit/cli/test_commands_log.py`
- modify: `tests/unit/cli/test_commands_misc.py`
- modify: `tests/unit/cli/test_commands_status.py`
- modify: `tests/unit/core/test_scheduler_service_trigger.py`
- modify: `tests/unit/test_web_utils.py`
- modify: `tests/unit/web/test_mappers.py`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

Split `src/hassette/test_utils/web_helpers.py` into 4 flat sibling files. See the design doc's "Backend: web_helpers split (AC#5)" section for the exact factory-to-file mapping:

| New file | Factories |
|---|---|
| `web_manifest_helpers.py` | `make_full_snapshot`, `make_manifest`, `make_manifest_response`, `make_manifest_list_response` |
| `web_job_helpers.py` | `make_job`, `make_real_job`, `make_job_summary` |
| `web_response_helpers.py` | `make_system_status_response`, `make_telemetry_status_response`, `make_dashboard_app_grid_entry`, `make_dashboard_app_grid_response`, `make_config_schema_response`, `make_app_health_response`, `make_app_config_response`, `make_app_source_response` |
| `web_telemetry_helpers.py` | `make_activity_feed_entry`, `make_listener_with_summary`, `make_execution`, `make_log_entry_response`, `make_logs_by_execution_response` |

Private helpers (`_tally_statuses`, `_strip_none`, `_config_to_toml`) move to the file that uses them. `SYNTHETIC_TIMESTAMP` moves to whichever file imports it most.

Update `test_utils/__init__.py` re-exports:
- `make_full_snapshot` → from `.web_manifest_helpers`
- `make_job` → from `.web_job_helpers`
- `make_manifest` → from `.web_manifest_helpers`
- `make_real_job` → from `.web_job_helpers`

Update `tools/check_test_factories.py` registry: `make_manifest` path changes from `hassette.test_utils.web_helpers` to `hassette.test_utils.web_manifest_helpers`.

Update `src/hassette/test_utils/web_mocks.py` line 16: `from hassette.test_utils.web_helpers import make_full_snapshot` → `from hassette.test_utils.web_manifest_helpers import make_full_snapshot`.

Update all 15 test file importers to point at the new submodule paths.

Delete `web_helpers.py` after all imports are updated.

## Focus

- The 4 `test_utils/__init__.py` re-exports are load-bearing — some test files import via `from hassette.test_utils import make_manifest`. Verify these still work after the re-export update.
- `web_mocks.py` is a source file (not a test), easily missed.
- The new files' imports from `telemetry_models` must use the post-T01 paths (e.g., `from hassette.schemas.execution_models import ...`).
- `_tally_statuses` is used by `make_full_snapshot` and `make_manifest_list_response` — both go to `web_manifest_helpers.py`, so the helper stays with them.

## Verify

- [ ] FR#8: `web_helpers.py` no longer exists; 4 new files contain all 20 public factories
- [ ] AC#5: `prek -a` passes; `ptest -- tests/unit tests/integration -n 4` passes; `from hassette.test_utils import make_manifest` works
