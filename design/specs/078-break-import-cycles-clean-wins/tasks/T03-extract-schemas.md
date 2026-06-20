---
task_id: "T03"
title: "Extract web data types to schemas package, add web->core RULE"
status: "planned"
depends_on: ["T02"]
implements: ["FR#3", "FR#4", "FR#7", "FR#9", "AC#3", "AC#5", "AC#6"]
---

## Summary
Create a new `src/hassette/schemas/` package and move the web-facing data types out of `core` into it: the whole `domain_models` and `telemetry_models` modules, the four snapshot dataclasses split out of `app_registry.py` (leaving `AppRegistry` in core), `LiveCounts` extracted from `bus_service.py`, and the two query-limit constants extracted from `core/telemetry/helpers.py`. Repoint every consumer — web routes, two `core` modules, `test_utils`, and ~8 test files — to the new `schemas` paths. This retires the `web → core` runtime cycle. Add the `web → core` boundary RULE. This is the riskiest unit: it must produce byte-identical OpenAPI and generated TypeScript output (the websocket payload models feed `ws-schema.json`). Ordered last among the structural moves and gated on a zero schema diff.

## Target Files
- create: `src/hassette/schemas/__init__.py`
- create: `src/hassette/schemas/domain_models.py` (moved from `core/domain_models.py`)
- create: `src/hassette/schemas/telemetry_models.py` (moved from `core/telemetry_models.py`)
- create: `src/hassette/schemas/app_snapshots.py` (the four snapshot dataclasses split from `core/app_registry.py`)
- delete: `src/hassette/core/domain_models.py`
- delete: `src/hassette/core/telemetry_models.py`
- modify: `src/hassette/core/app_registry.py` (remove the 4 snapshot dataclasses; `AppRegistry` imports them from `schemas`)
- modify: `src/hassette/core/bus_service.py` (extract `LiveCounts` — a `NamedTuple`, line 46 — to `schemas`; import it back)
- modify: `src/hassette/core/telemetry/helpers.py` (move the 2 query-constant DEFINITIONS at lines 16,28 to `schemas`; re-import them from `schemas` so internal core users still resolve)
- modify: `src/hassette/core/telemetry/query_service.py` (re-exports the 2 constants via `helpers` — confirm the chain still resolves after helpers re-imports from `schemas`; likely no edit, since it imports from `helpers`, not from the definitions)
- modify: `src/hassette/core/runtime_query_service.py` (imports domain_models + snapshots — repoint to `schemas`)
- modify: `src/hassette/core/app_handler.py` (imports `AppStatusSnapshot` — repoint to `schemas`; keep `AppRegistry` from core)
- modify: `src/hassette/web/mappers.py` (lines 18-21: snapshots, LiveCounts, SystemStatus, AND `ListenerSummary` from telemetry_models)
- modify: `src/hassette/web/models.py` (line 7: domain_models)
- modify: `src/hassette/web/routes/scheduler.py` (line 10: telemetry_models)
- modify: `src/hassette/web/routes/telemetry.py` (line 15: query constants → `schemas`; line 16: telemetry_models → `schemas`)
- modify: `src/hassette/web/utils.py` (line 6: telemetry_models)
- modify: `src/hassette/test_utils/web_helpers.py` (line 23: snapshots → `schemas`)
- modify: `src/hassette/test_utils/web_mocks.py` (line 14: snapshots → `schemas`; lines 15-16 import `RuntimeQueryService`/`AppHealthAggregates` from core — these stay, see Focus)
- modify: `tools/check_module_boundaries.py` (append the web->core Rule)
- modify: `tests/unit/web/test_mappers.py`, `tests/unit/test_ws_models.py`, `tests/unit/core/test_runtime_query_service.py`, `tests/integration/web_api/test_dashboard_api.py`, `tests/integration/telemetry/test_global_jobs_and_service_info.py`, `tests/integration/test_app_factory_lifecycle.py`, `tests/integration/web_api/test_ws_endpoint.py`, `tests/integration/web_api/conftest.py`, `tests/integration/web_api/test_telemetry.py`, `tests/integration/bus/test_execution_modes.py`, `tests/e2e/mock_fixtures.py` (import paths for moved symbols)
- read: `scripts/export_schemas.py`, `scripts/generate-ws-types.cjs`
- read: `design/specs/078-break-import-cycles-clean-wins/design.md` (Architecture → Change 2; Edge Cases; Migration-free note)
- read: `design/specs/078-break-import-cycles-clean-wins/tasks/context.md`

## Prompt
Read `context.md` and the design doc's `## Architecture` → "Change 2", `## Edge Cases`, and `## Key Constraints`.

**This is a pure code move. Do not redesign, rename, or change any field, type, default, or Pydantic config. Serialized output must be byte-identical (FR#9).**

1. **Create the package.** `src/hassette/schemas/__init__.py`. `schemas` may import ONLY `types`, `const`, and `utils`. If any moved type needs something higher, stop — the extraction is wrong; surface it rather than adding a lazy import.
2. **Move whole modules:**
   - `core/domain_models.py` → `schemas/domain_models.py`. (It contains more than the 5 classes the design named — e.g. `BootIssue`, `ServiceInfo` appear in tests. Move the whole module; do not cherry-pick.) It imports nothing internal, so the move is clean.
   - `core/telemetry_models.py` → `schemas/telemetry_models.py`. It imports only `types.enums` + `types.types` — clean.
3. **Split `core/app_registry.py`.** Move the four `@dataclass` snapshots — `AppInstanceInfo`, `AppStatusSnapshot`, `AppManifestInfo`, `AppFullSnapshot` (`app_registry.py:17-97`) — into `schemas/app_snapshots.py`. Leave the `AppRegistry` class (`app_registry.py:98+`, logic) in `core/app_registry.py`, and have it import the snapshots from `schemas`. The snapshots use `utils.exception_utils.get_traceback_string` and `types.enums` — both below `schemas`, so the split is clean.
4. **Extract `LiveCounts`** from `core/bus_service.py:46` into `schemas`. It is a `NamedTuple` (`class LiveCounts(NamedTuple)`), NOT a dataclass — preserve the exact `NamedTuple` definition; converting it to a dataclass would change its semantics (positional indexing, `isinstance` as `tuple`) and could alter serialized output (FR#9). `BusService` imports it back from `schemas` (downward — fine).
5. **Extract the query constants.** `DEFAULT_QUERY_LIMIT` (=50) and `DEFAULT_SPARKLINE_BUCKETS` (=12) are DEFINED in `core/telemetry/helpers.py:16,28` (NOT in `query_service.py`, which only re-exports them via `__all__`). Move the two definitions into `schemas`. Then update `helpers.py` to import them back from `schemas`, and keep `query_service.py`'s re-export working (it imports them from `helpers`). The goal is that `web/routes/telemetry.py` imports the constants from `schemas`, not from `core`.
6. **Repoint all consumers** to `schemas`:
   - **web:** `web/mappers.py:18-21` (all four lines — `app_registry` snapshots, `bus_service.LiveCounts`, `domain_models.SystemStatus`, AND `telemetry_models.ListenerSummary` on line 21 — do not stop at line 20), `web/models.py:7`, `web/routes/scheduler.py:10`, `web/routes/telemetry.py:15-16`, `web/utils.py:6`.
   - **core callers:** `core/runtime_query_service.py:14,16` (snapshots + domain_models), `core/app_handler.py:14` (`AppStatusSnapshot` → schemas; `AppRegistry` stays from core).
   - **test_utils:** `test_utils/web_helpers.py:23`, `test_utils/web_mocks.py:14`.
   - **tests** (import path only, no assertion changes): `tests/unit/web/test_mappers.py`, `tests/unit/test_ws_models.py`, `tests/unit/core/test_runtime_query_service.py`, `tests/integration/web_api/test_dashboard_api.py`, `tests/integration/telemetry/test_global_jobs_and_service_info.py`, `tests/integration/test_app_factory_lifecycle.py`, `tests/integration/web_api/test_ws_endpoint.py`, `tests/integration/web_api/conftest.py`, `tests/integration/web_api/test_telemetry.py`, `tests/integration/bus/test_execution_modes.py`, `tests/e2e/mock_fixtures.py`.
   - Grep before finishing: `grep -rn "core.domain_models\|core.telemetry_models\|core.app_registry import.*Snapshot\|core.app_registry import.*Info\|core.bus_service import.*LiveCounts" src tests` should show snapshots/LiveCounts only from `schemas` (and `AppRegistry` still from `core`).
7. **Add the boundary RULE.** Append to `RULES` in `tools/check_module_boundaries.py` (all four fields):
   - `name`: e.g. `"web-no-core"`
   - `applies=lambda layer: layer == "web"`
   - `forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core.")`
   - `reason`: one line — `web` must not runtime-import `core`; web-facing data types live in `hassette.schemas`.
   Note: `web`'s remaining `core` imports (`web/dependencies.py`, `web/routes/executions.py`, `web/telemetry_helpers.py`) are `TYPE_CHECKING`-guarded service-class imports — the checker exempts them, so the RULE passes. `core → web` (`core/web_api_service.py:16`) is untouched and one-directional.
8. **Regenerate and diff schemas (the gate).** Run `cd frontend && npm install` (once), then `uv run python scripts/export_schemas.py --types`, then `git diff --stat openapi.json ws-schema.json frontend/src/api/generated-types.ts frontend/src/api/ws-types.ts`. The diff MUST be empty. If anything changed, the move altered a serialized shape — fix it; do not regenerate-and-commit the drift.

## Focus
- **Highest blast radius in the PR.** `domain_models` holds the websocket payload models (`StateChangedData`, `AppStatusChangedData`, `ServiceStatusData`) consumed by `test_ws_models.py` and fed into `ws-schema.json` via `scripts/generate-ws-types.cjs`. A field-order or import-path change that alters `__module__` in a schema title would surface as a `ws-types.ts` diff — the gate (step 8) catches it.
- `core/runtime_query_service.py` PRODUCES these types (it builds `SystemStatus`, snapshots) — confirms they are used by `core` too. After the move it imports them downward from `schemas` (`core → schemas` is fine).
- `web/models.py` and `cli/commands/status.py` / `web/routes/health.py` use response wrappers from `web.models` (e.g. `SystemStatusResponse`) — those wrappers stay in `web.models`; only the underlying `domain_models` import inside `web/models.py` repoints to `schemas`. Do not move the `web.models` response wrappers.
- Keep `app_registry.py`'s `AppRegistry` and its snapshot imports in the right direction: `core/app_registry.py` imports snapshots from `schemas`, never the reverse.
- **`test_utils/web_mocks.py` keeps two `core` imports on purpose.** Lines 15-16 import `RuntimeQueryService` and `AppHealthAggregates` from `core` — these are NOT web-facing data types and stay in `core`. `test_utils` is L9 and may import anything, so leave them. Only the snapshot import (`web_mocks.py:14`) repoints to `schemas`. The FR#4 grep scopes to `web/` only, so these `test_utils` imports do not affect it — don't be alarmed when they remain.
- Do NOT add a `bus`/`scheduler`/`state_manager` → core rule here.
- Pyright strict: a moved module must keep its exact public names so `__all__` and importers resolve.

## Verify
- [ ] FR#3: `from hassette.schemas.domain_models import SystemStatus`, `from hassette.schemas.telemetry_models import ListenerSummary, JobSummary`, `from hassette.schemas.app_snapshots import AppFullSnapshot`, `from hassette.schemas import LiveCounts` (or its chosen module), and the two query constants all import from `schemas`.
- [ ] FR#4: `grep -rn "from hassette.core" src/hassette/web` returns only `TYPE_CHECKING`-guarded lines.
- [ ] FR#7: `tools/check_module_boundaries.py` `RULES` contains a `web`-layer rule forbidding `hassette.core[.*]`, all four fields populated; `python tools/check_module_boundaries.py` exits zero on the clean tree.
- [ ] AC#3: inserting a throwaway top-level `from hassette.core.core import Hassette` into any `web/` file makes `python tools/check_module_boundaries.py` exit non-zero; the clean tree exits zero.
- [ ] FR#9: `uv run python scripts/export_schemas.py --types` followed by `git diff --quiet openapi.json ws-schema.json frontend/src/api/generated-types.ts frontend/src/api/ws-types.ts` exits zero (no diff).
- [ ] AC#5: the pre-push schema-freshness check `uv run python tools/check_schemas_fresh.py` passes after the extraction.
- [ ] AC#6: `uv run pyright` reports zero new errors; the adapted web/telemetry/app-registry test files pass (`uv run pytest tests/unit/web tests/integration/web_api -q`).
