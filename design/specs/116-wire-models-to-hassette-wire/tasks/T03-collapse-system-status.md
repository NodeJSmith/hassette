---
task_id: "T03"
title: "Collapse SystemStatus into the wire response models"
status: "done"
depends_on: ["T02"]
implements: ["FR#3", "AC#6", "AC#2"]
---

## Summary
`SystemStatus`, `ServiceInfo`, and `BootIssue` in `schemas/domain_models.py` are near field-for-field copies of `SystemStatusResponse`, `ServiceInfoResponse`, and `BootIssueResponse`, and a mapper copies one into the other. This task deletes the copies: `RuntimeQueryService.get_system_status()` builds the wire models directly and sets `version` explicitly, the mapper goes away, and with nothing left in it, `domain_models.py` is deleted. It also adds the removed-name absence test (AC#2), which covers everything T01 through T03 removed.

## Target Files
- delete: `src/hassette/schemas/domain_models.py`
- modify: `src/hassette/schemas/__init__.py`
- modify: `src/hassette/schemas/summary_models.py`
- modify: `src/hassette/core/runtime_query_service.py`
- modify: `src/hassette/web/mappers.py`
- modify: `src/hassette/web/routes/health.py`
- modify: `tests/unit/web/test_mappers.py`
- modify: `tests/unit/core/test_runtime_query_service.py`
- modify: `tests/integration/telemetry/test_global_jobs_and_service_info.py`
- modify: `tests/integration/test_dashboard_without_ha.py`
- modify: `tests/integration/web_api/test_dashboard_api.py`
- modify: `tests/integration/web_api/test_ws_endpoint.py`
- modify: `tests/unit/test_wire_public_paths.py`
- modify: `.claude/rules/core-startup.md`
- read: `src/hassette/web/routes/ws.py`
- read: `src/hassette/utils/__init__.py`
- read: `wire/src/hassette_wire/health.py`
- read: `design/specs/116-wire-models-to-hassette-wire/design.md`

## Prompt
Read `tasks/context.md` and these design sections: `### SystemStatus collapse`, `## Edge Cases` ("`version` becomes explicit", "`ServiceInfo.status` was a `str`"), `## Replacement Targets`, and `## Test Strategy` → `### Existing Tests to Adapt` (the paragraph on the `SystemStatus` collapse).

1. In `src/hassette/core/runtime_query_service.py` (`get_system_status` ~line 300, `collect_boot_issues` ~line 354): `get_system_status()` returns `hassette_wire.SystemStatusResponse`. It builds `ServiceInfoResponse(name=…, status=child.status, role=child.role.value, ready_phase=…, retry_at=…)`, passing `status` as the `ResourceStatus` member rather than `child.status.value`, and passes `version=get_version()` (from `hassette.utils`). `collect_boot_issues()` returns `list[BootIssueResponse]`. Keep every other field computed exactly as today.
2. In `src/hassette/web/mappers.py`: delete `system_status_response_from`. `readiness_response_from` and `connected_payload_from` take a `SystemStatusResponse`; their bodies don't change. Remove the `SystemStatus` import, and in the module docstring remove the `SystemStatus` mapping and the enum-coercion note.
3. `src/hassette/web/routes/health.py`: `/health` returns `runtime.get_system_status()` directly. `routes/ws.py` keeps calling `connected_payload_from`; read it to confirm it compiles against the new type.
4. Delete `src/hassette/schemas/domain_models.py` (`git rm`). `schemas/__init__.py` drops the `SystemStatus`, `ServiceInfo`, `BootIssue` imports and `__all__` entries, and its docstring loses the `domain_models.py` entry and points to `hassette_wire` for served types. `schemas/summary_models.py:6` has a docstring saying "see domain_models.py": point it at `hassette.schemas.app_snapshots` for live runtime state instead.
5. Adapt the tests. In `tests/unit/web/test_mappers.py`, remove the `system_status_response_from` tests, and have the `readiness_response_from`/`connected_payload_from` tests build a `SystemStatusResponse`. The other listed tests switch from asserting the `SystemStatus`/`ServiceInfo`/`BootIssue` type or shape to the `*Response` types. In `tests/unit/core/test_runtime_query_service.py`, add an assertion that `get_system_status()` returns a `SystemStatusResponse` whose `version == get_version()` and whose `services[*].status` are `ResourceStatus` members (`isinstance`).
6. Extend `tests/unit/test_wire_public_paths.py` with AC#2:
   - `importlib.util.find_spec("hassette.web.models") is None`
   - `importlib.util.find_spec("hassette.schemas.domain_models") is None`
   - `not hasattr(module, name)` for each moved or deleted name against its surviving old module:
     - `AppStatusChangedData`, `ServiceStatusData`, `ConnectivityData`, `SystemStatus`, `ServiceInfo`, `BootIssue` on `hassette.schemas`
     - `Execution`, `ActivityFeedEntry` on `hassette.schemas.execution_models`
     - `JobSummary` on `hassette.schemas.job_models`
     - `CliFormat`, `CliFormatStyle` on `hassette.types.types`
7. `.claude/rules/core-startup.md` (~lines 34 and 58) describes `get_system_status()`. Update any wording that names the `SystemStatus`/`ServiceInfo` types or the mapper; leave the readiness semantics as they are.

## Focus
- `ServiceInfoResponse.status` is typed `ResourceStatus`; `ServiceInfo.status` was a `str`, and the mapper cast it back. Passing the enum directly removes the round-trip. The `/health` JSON body must not change: the existing `GET /api/health` tests are the pin, so run them unchanged.
- `SystemStatusResponse.version` defaults to `""`. If `get_version()` isn't passed, `/health` would silently report an empty version, so AC#6's assertion is the guard.
- `tests/integration/test_dashboard_without_ha.py:206` calls `hassette.runtime_query_service.get_system_status()` directly and may assert on attribute types.
- `runtime_query_service.py` is also edited by T04 (`on_execution_completed` / `flush_completions`). Keep this task's edits to `get_system_status` / `collect_boot_issues` and imports so T04 applies cleanly.
- `tests/integration/web_api/test_ws_endpoint.py` asserts on the `connected` payload that `connected_payload_from` builds from the system status.

## Verify
- [ ] FR#3: `grep -rnE "\b(SystemStatus|ServiceInfo|BootIssue)\b" src tests scripts` finds only the `*Response` names (no bare `SystemStatus`/`ServiceInfo`/`BootIssue`), and `grep -rn system_status_response_from src tests` returns nothing.
- [ ] AC#6: `uv run pytest tests/unit/core/test_runtime_query_service.py -n 4` passes, including the new assertion (`SystemStatusResponse`, `version == get_version()`, `ResourceStatus` statuses), and `uv run pytest tests/integration/web_api -n 4 -k health` passes with the health tests unchanged.
- [ ] AC#2: `uv run pytest tests/unit/test_wire_public_paths.py -n 4` passes, including the `find_spec(...) is None` checks for `hassette.web.models` and `hassette.schemas.domain_models` and every `not hasattr` case listed in the Prompt.
