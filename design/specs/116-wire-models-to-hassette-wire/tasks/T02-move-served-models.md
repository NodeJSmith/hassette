---
task_id: "T02"
title: "Move served models and WS payloads into hassette_wire"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#4", "FR#9", "FR#10", "AC#1", "AC#4", "AC#5"]
---

## Summary
Moves every served model out of `hassette`: the whole of `src/hassette/web/models.py` (response models, WS messages, the `WsServerMessage` union, and its Literal aliases), the four WS payloads in `schemas/domain_models.py`, and the served telemetry models `Execution`, `ActivityFeedEntry`, `JobSummary`. They go into `hassette_wire`'s domain submodules, re-exported from the package root. `web/models.py` is deleted, and the unreferenced `EntityStateResponse`/`EntityListResponse` are dropped. Every import site is rewritten to `from hassette_wire import …`. The generated schemas and TS types must come out byte-identical, which proves the move was mechanical. `SystemStatus`/`ServiceInfo`/`BootIssue` stay in `domain_models.py` for now; T03 collapses them and deletes the file.

## Target Files
- create: `wire/src/hassette_wire/health.py`
- create: `wire/src/hassette_wire/apps.py`
- create: `wire/src/hassette_wire/telemetry.py`
- create: `wire/src/hassette_wire/logs.py`
- create: `wire/src/hassette_wire/auth.py`
- create: `wire/src/hassette_wire/config.py`
- create: `wire/src/hassette_wire/ws.py`
- modify: `wire/src/hassette_wire/literals.py`
- modify: `wire/src/hassette_wire/__init__.py`
- modify: `wire/tests/test_import.py`
- delete: `src/hassette/web/models.py`
- modify: `src/hassette/schemas/domain_models.py`
- modify: `src/hassette/schemas/execution_models.py`
- modify: `src/hassette/schemas/job_models.py`
- modify: `src/hassette/schemas/__init__.py`
- modify: `pyproject.toml`
- modify: `.github/codecov.yml`
- modify: `frontend/src/REVIEW.md`
- modify: `scripts/schema_helpers.py` (import rewrite)
- modify: `src/hassette/cli/client.py` (import rewrite)
- modify: `src/hassette/cli/commands/app.py` (import rewrite)
- modify: `src/hassette/cli/commands/job.py` (import rewrite)
- modify: `src/hassette/cli/commands/listener.py` (import rewrite)
- modify: `src/hassette/cli/commands/log.py` (import rewrite)
- modify: `src/hassette/cli/commands/misc.py` (import rewrite)
- modify: `src/hassette/cli/commands/status.py` (import rewrite)
- modify: `src/hassette/core/runtime_query_service.py` (import rewrite)
- modify: `src/hassette/core/telemetry/execution_queries.py` (import rewrite)
- modify: `src/hassette/core/telemetry/registration_queries.py` (import rewrite)
- modify: `src/hassette/web/mappers.py` (import rewrite)
- modify: `src/hassette/web/routes/apps.py` (import rewrite)
- modify: `src/hassette/web/routes/auth.py` (import rewrite)
- modify: `src/hassette/web/routes/bus.py` (import rewrite)
- modify: `src/hassette/web/routes/config.py` (import rewrite)
- modify: `src/hassette/web/routes/executions.py` (import rewrite)
- modify: `src/hassette/web/routes/health.py` (import rewrite)
- modify: `src/hassette/web/routes/logs.py` (import rewrite)
- modify: `src/hassette/web/routes/scheduler.py` (import rewrite)
- modify: `src/hassette/web/routes/telemetry.py` (import rewrite)
- modify: `src/hassette/web/telemetry_helpers.py` (import rewrite)
- modify: `src/hassette/web/utils.py` (import rewrite)
- modify: `tests/e2e/mock_fixtures/telemetry.py` (import rewrite)
- modify: `tests/integration/telemetry/helpers.py` (import rewrite)
- modify: `tests/integration/telemetry/test_execution_queries.py` (import rewrite)
- modify: `tests/integration/telemetry/test_global_jobs_and_service_info.py` (import rewrite)
- modify: `tests/integration/telemetry/test_job_queries.py` (import rewrite)
- modify: `tests/integration/telemetry/test_union_queries.py` (import rewrite)
- modify: `tests/integration/web_api/test_body_limit.py` (import rewrite)
- modify: `tests/integration/web_api/test_dashboard_api.py` (import rewrite)
- modify: `tests/integration/web_api/test_telemetry_route.py` (import rewrite)
- modify: `tests/support/web_job_helpers.py` (import rewrite)
- modify: `tests/support/web_manifest_helpers.py` (import rewrite)
- modify: `tests/support/web_response_helpers.py` (import rewrite)
- modify: `tests/support/web_telemetry_helpers.py` (import rewrite)
- modify: `tests/system/test_cli_smoke.py` (import rewrite)
- modify: `tests/unit/cli/test_client.py` (import rewrite)
- modify: `tests/unit/cli/test_commands_app.py` (import rewrite)
- modify: `tests/unit/core/test_runtime_query_service.py` (import rewrite)
- modify: `tests/unit/core/test_telemetry_models.py` (import rewrite)
- modify: `tests/unit/core/test_unified_execution.py` (import rewrite)
- modify: `tests/unit/test_logging_capture_handler.py` (import rewrite)
- modify: `tests/unit/test_model_types.py` (import rewrite)
- modify: `tests/unit/test_telemetry_models.py` (import rewrite)
- modify: `tests/unit/test_ws_models.py` (import rewrite)
- modify: `tests/unit/web/test_mappers.py` (import rewrite)
- read: `design/specs/116-wire-models-to-hassette-wire/design.md`
- read: `scripts/export_schemas.py`
- read: `noxfile.py`

## Prompt
Read `tasks/context.md` and these design sections first: `### Package layout (wire/src/hassette_wire/)` (the table says which name goes in which submodule), `### Literal wire fields`, `### Import rewrite`, `## Edge Cases` (attribute docstrings, defaults), `## Replacement Targets`, `## Key Constraints`.

1. **Move code mechanically.** Cut the exact line ranges from `src/hassette/web/models.py` (520 lines; top-level names in order: `MAX_SESSION_TOKEN_LENGTH`, `ErrorRateClass`, `HealthStatus`, `ListenerKind`, `SystemHealthStatus`, `BootIssueResponse` … `AppSourceResponse`) into the submodules the layout table names. Never retype a class: docstrings, field order, defaults, and `model_config` must stay byte-exact (`ListenerWithSummary` uses `use_attribute_docstrings=True`, so its field docstrings are schema descriptions). The four Literal aliases go into `literals.py`. `EntityStateResponse` and `EntityListResponse` are deleted, not moved. Then `git rm src/hassette/web/models.py`.
2. From `src/hassette/schemas/domain_models.py`, move `AppStatusChangedData`, `ServiceStatusData`, `ConnectivityData`, `AppManifestsChangedData` into `ws.py`. Leave `SystemStatus`, `ServiceInfo`, and `BootIssue` in place (T03 removes them). From `schemas/execution_models.py`, move `Execution` and `ActivityFeedEntry` into `telemetry.py`; `AppLastError` stays. From `schemas/job_models.py`, move `JobSummary` into `telemetry.py`; `JobGlobalStats`/`JobErrorRecord` stay. `schemas/__init__.py` drops `AppStatusChangedData`, `ServiceStatusData`, `ConnectivityData` from its imports and `__all__`.
3. **Defaults.** `hassette_wire` can't import `hassette`. A moved field defaulting to `DEFAULT_OVERLAP_MODE` / `DEFAULT_BACKPRESSURE_POLICY` uses `ExecutionMode.SINGLE` / `BackpressurePolicy.BLOCK` directly. Confirm first that those are the constants' current values, and that the schema `default` value doesn't change.
4. **Root exports.** `wire/src/hassette_wire/__init__.py` re-exports every public class, alias, and constant from every submodule, all listed in `__all__`.
5. **Import rewrite.** Using the same kind of one-off `ast`-based script as T01 (uncommitted), rewrite every file marked "import rewrite" so names from `hassette.web.models`, and the moved names from `hassette.schemas`, `hassette.schemas.domain_models`, `hassette.schemas.execution_models`, `hassette.schemas.job_models`, come `from hassette_wire import …`. Names that stay (`SystemStatus`, `ServiceInfo`, `BootIssue`, `AppLastError`, `JobGlobalStats`, …) keep their original import line. Run `prek -a` to normalize.
6. **Config and prose pointing at the deleted file:** `pyproject.toml` coverage `omit` entry `"*/web/models.py"` and `.github/codecov.yml` ignore entry `"src/hassette/web/models.py"` are removed, since those models no longer live in `src/hassette`. In `frontend/src/REVIEW.md` (lines ~7, ~16), replace `src/hassette/web/models.py` with `wire/src/hassette_wire/`.
7. **Wire tests (`wire/tests/test_import.py`, extend).** (a) Run `import hassette_wire` in a fresh interpreter (`subprocess.run([sys.executable, "-c", ...])`) and assert no module named `hassette` or starting with `hassette.` is in `sys.modules`. `hassette_wire` itself is fine. (b) For every submodule of `hassette_wire`, every public top-level class, alias, and constant it defines (not imported names, i.e. check `obj.__module__` for classes and parse the module for aliases) is in `hassette_wire.__all__` and `getattr(hassette_wire, name)` is that object.
8. **Pin.** `cd frontend && npm install` (once per worktree), then `uv run python scripts/export_schemas.py --types`, then `git diff --exit-code frontend/openapi.json frontend/ws-schema.json frontend/src/api/generated-types.ts frontend/src/api/ws-types.ts frontend/src/api/ws-validator.generated.ts`. It must be clean. If not, find the cause and fix it (usually a retyped docstring or a reordered field).

## Focus
- `scripts/schema_helpers.py` imports `WsServerMessage` from `hassette.web.models`; `export_schemas.py` goes through it, so the pin depends on this rewrite.
- `src/hassette/core/runtime_query_service.py` imports both WS payloads and `SystemStatus`/`ServiceInfo`/`BootIssue` from `domain_models`. Split that import: the payloads come from `hassette_wire`, and the trio stays on `domain_models` until T03.
- `tests/unit/test_ws_models.py` imports payloads from `hassette.schemas.domain_models` on separate lines (`:9`, `:10`). Make sure both are rewritten.
- `src/hassette/schemas/summary_models.py:6` has a docstring pointing at `domain_models.py`. Leave it; T03 updates it once the file is gone.
- If a moved model's module needs a name that lives in another wire submodule, import it from that sibling submodule inside the package (e.g. `from hassette_wire.enums import ResourceStatus`), not from the root, to avoid root-import cycles.
- Watch the 800-line cap. No single wire submodule should exceed ~400 lines, per the layout table.
- `uv run nox -s wire` runs `pytest` inside `wire/` in isolation. Its environment has only `hassette-wire` and `pydantic`, which is exactly what makes AC#4 meaningful.

## Verify
- [ ] FR#1: `test ! -e src/hassette/web/models.py`, and `grep -rn "EntityStateResponse\|EntityListResponse" src wire tests scripts` returns nothing.
- [ ] FR#2: `AppStatusChangedData`, `ServiceStatusData`, `ConnectivityData`, `AppManifestsChangedData` are defined in `wire/src/hassette_wire/ws.py` and nowhere under `src/`.
- [ ] FR#4: `Execution`, `ActivityFeedEntry`, `JobSummary` are defined in `wire/src/hassette_wire/telemetry.py` and nowhere under `src/`, and `AppLastError`, `JobGlobalStats`, `JobErrorRecord` still live in `hassette.schemas`.
- [ ] FR#9: `uv run nox -s wire` passes the `__all__`-completeness test.
- [ ] FR#10: `uv run nox -s wire` passes the fresh-interpreter isolation test.
- [ ] AC#1: after `uv run python scripts/export_schemas.py --types`, `git diff --exit-code frontend/openapi.json frontend/ws-schema.json frontend/src/api/generated-types.ts frontend/src/api/ws-types.ts frontend/src/api/ws-validator.generated.ts` exits 0.
- [ ] AC#4: `uv run nox -s wire` passes, including the test asserting `import hassette_wire` in a fresh interpreter loads no `hassette`/`hassette.*` module.
- [ ] AC#5: `wire/tests/test_import.py` contains the test asserting every public class/alias defined in `hassette_wire`'s submodules is in `__all__` and importable from the root, and it passes.
