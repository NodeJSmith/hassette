# Design: Decouple Core from Web Layer, Extract Telemetry Persistence, and Formalize API Contracts

**Date:** 2026-03-30
**Status:** archived
**Issues:** #415, #388
**Research:** /tmp/claude-mine-design-research-TAWApW/brief.md
**Challenge findings:** /tmp/claude-mine-design-challenge-r2-phFKtr/findings.md

## Problem

Core services have a reverse dependency on the web presentation layer, `CommandExecutor` mixes execution logic with database persistence, and there is no formalized contract between backend models and frontend TypeScript interfaces.

Specifically:

1. **`RuntimeQueryService`** imports 9 Pydantic response models from `hassette.web.models` (`AppInstanceResponse`, `AppStatusResponse`, `SystemStatusResponse`, WS payload models, etc.). This means the core framework cannot run without the web layer, and changes to API response shapes force changes in core services.

2. **`CommandExecutor._execute_handler()` and `_execute_job()`** share ~170 lines of near-identical timing/error-handling/record-creation code. A purpose-built `track_execution()` context manager exists in `utils/execution.py` but is unused.

3. **`CommandExecutor`** contains 6 inline SQL statements across 5 `_do_*` methods, coupling execution logic directly to the database schema and aiosqlite API.

4. **Frontend TypeScript interfaces** for API endpoints (`JobData`, `HandlerInvocationData`, etc.) are hand-mirrored from backend Pydantic models. Backend changes silently drift from frontend types with no build-time validation.

## Non-Goals

- Consolidating all existing domain models into a single module (follow-up if desired)
- Introducing a formal ORM or query builder — the repository uses raw SQL like the rest of the codebase
- Refactoring `TelemetryQueryService` (the read-side counterpart) — it's out of scope

## Architecture

The refactoring has four parts, ordered by risk:

### Part 1: Extract SQL to TelemetryRepository

**What changes:** The 6 inline SQL statements in `CommandExecutor`'s `_do_*` methods move to a new `TelemetryRepository` class.

**New file:** `src/hassette/core/telemetry_repository.py`

`TelemetryRepository` holds a `DatabaseService` reference and accesses `db` internally (lazy, at execution time). This matches the current `_do_*` pattern where `db` is fetched inside the coroutine body, not captured eagerly at the call site — avoiding stale-connection risks if `DatabaseService` ever restarts.

Methods:
- `register_listener(...) -> int` — INSERT INTO listeners
- `register_job(...) -> int` — INSERT INTO scheduled_jobs
- `clear_registrations(app_key) -> None` — DELETE FROM listeners + scheduled_jobs
- `persist_batch(invocations, job_executions) -> None` — executemany INSERTs for handler_invocations and job_executions

**Calling convention:** `DatabaseService.submit()` takes a pre-called `Coroutine` object. Call sites become:

```python
# Before
await self.hassette.database_service.submit(self._do_register_listener(registration))

# After
await self.hassette.database_service.submit(self.repository.register_listener(registration))
```

Unit tests inject a mock `DatabaseService` (or a thin wrapper around an in-memory SQLite connection) into the repository constructor.

**Sentinel filter:** The `listener_id == 0` / `session_id == 0` drop logic (regression guard) remains in `CommandExecutor._drain_and_persist()` before the repository call. It is not part of `TelemetryRepository.persist_batch()`.

**Why this order:** Lowest risk. The methods are already isolated. This is a move-and-rename operation with no behavioral change. Existing integration tests validate correctness.

### Part 2: Deduplicate Execution Logic via `track_execution()`

**What changes:** `_execute_handler()` (88 lines) and `_execute_job()` (83 lines) are simplified using `track_execution()`.

**Extending `track_execution()`:** Add a `known_errors` parameter (tuple of exception types). When a caught exception is an instance of a known error type, `ExecutionResult.error_traceback` is set to `None`. This preserves the existing contract where `DependencyError` and `HassetteError` are logged without tracebacks, while generic `Exception` includes full tracebacks. The `isinstance` semantics mean subclasses of listed types are also suppressed — document this in the docstring.

**Control flow:** `track_execution()` unconditionally re-raises all exceptions (`execution.py:57-64`). This means code after the `async with` block is unreachable on error paths. The unified method must wrap `track_execution()` in its own try/except:

```python
async def _execute(self, callable, cmd) -> ExecutionResult:
    result = ExecutionResult()  # safe default if CancelledError fires before yield
    try:
        async with track_execution(known_errors=(DependencyError, HassetteError)) as result:
            await callable()
    except asyncio.CancelledError:
        self._queue_record(cmd, result)  # queue before re-raising
        raise
    except Exception:
        pass  # track_execution() already re-raised; result is populated. Swallowing is intentional.
    # result is available for both success and error paths
    self._queue_record(cmd, result)
    return result
```

**No record factory:** Instead of a generic factory callable, `_execute_handler()` and `_execute_job()` remain as thin wrappers (~10 lines each) that call `_execute()` and build their own record type from the returned `ExecutionResult`. This keeps types explicit and Pyright-friendly — the dedup target is the try/except flow, not record construction.

**Why this order:** Medium risk. The exception contract is nuanced (5 branches with different traceback/logging behavior). The integration tests in `test_command_executor.py` (17 tests) cover this thoroughly, including assertions on `record.error_traceback is None` for known errors.

### Part 3: Decouple RuntimeQueryService from Web Models

**What changes:** `RuntimeQueryService` stops importing from `hassette.web.models`. Its methods return domain objects instead of web response models. The web layer gains a mapping module.

**All new domain types use Pydantic `BaseModel`**, not plain dataclasses. Rationale:
- Core already depends on Pydantic (`telemetry_models.py`) — the dependency exists regardless
- WS payload types must stay Pydantic to preserve the `ws-schema.json` pre-push guard (`tools/check_schemas_fresh.py` validates `WsServerMessage` via `TypeAdapter.json_schema()`)
- Using a single model convention avoids the confusing split of dataclasses-for-some and Pydantic-for-others in the same layer
- `model_dump()` handles enum coercion, field serialization, and validation consistently — eliminating the `dataclasses.asdict()` divergence risks

**Domain objects — existing:** `AppStatusSnapshot`, `AppFullSnapshot`, `AppInstanceInfo`, `AppManifestInfo` already exist as dataclasses in `core/app_registry.py`. These are internal snapshot types used by `AppRegistry` — they stay as-is. `RuntimeQueryService` returns them directly for app status/manifest queries.

**Domain objects — new:** `src/hassette/core/domain_models.py` will contain Pydantic `BaseModel` classes:

- `SystemStatus` — replaces `SystemStatusResponse` as the return type of `get_system_status()`
  - Fields: `status: Literal["ok", "degraded", "starting"]`, `websocket_connected: bool`, `uptime_seconds: float | None`, `entity_count: int`, `app_count: int`, `services_running: list[str]`
- `StateChangedData` — replaces `StateChangedPayload` (WS broadcast)
- `AppStatusChangedData` — replaces `AppStatusChangedPayload` (WS broadcast)
- `ConnectivityData` — replaces `ConnectivityPayload` (WS broadcast)
- `ServiceStatusData` — replaces `WsServiceStatusPayload` (WS broadcast)

**WS payload construction:** The event handlers (`_on_app_state_changed`, `_on_service_status`) currently use a triple roundtrip: `_serialize_payload()` → `model_validate()` → `model_dump()`. This is replaced with direct construction from `event.payload.data` fields:

```python
async def _on_app_state_changed(self, event: Event) -> None:
    if not hasattr(event, "payload"):
        return
    data = event.payload.data  # AppStateChangePayload dataclass
    payload = AppStatusChangedData(
        app_key=data.app_key,
        status=data.status.value,  # explicit enum → str coercion
        previous_status=data.previous_status.value if data.previous_status else None,
        # ... remaining fields
    )
    entry = {"type": "app_status_changed", "data": payload.model_dump(), ...}
```

`_serialize_payload()` is deleted entirely.

**WS discriminated union:** `WsServerMessage` in `web/models.py` references the WS payload types. After Part 3, these types move from `web/models.py` to `core/domain_models.py`. The `WsServerMessage` union and its wrapper message types (`AppStatusChangedWsMessage`, etc.) stay in `web/models.py` and import from `core/domain_models`. This preserves the `check_schemas_fresh.py` pre-push guard — `TypeAdapter(WsServerMessage).json_schema()` still captures all payload shapes.

**Web mapping layer:** `src/hassette/web/mappers.py` — a dedicated module with `from_*` functions:
- `app_status_response_from(snapshot: AppStatusSnapshot) -> AppStatusResponse` — merges `snapshot.running` and `snapshot.failed` into a single `apps` list
- `app_manifest_list_response_from(full: AppFullSnapshot) -> AppManifestListResponse` — builds nested `AppInstanceResponse` objects from `AppManifestInfo.instances`. Note: `AppInstanceInfo.status` is `ResourceStatus` (use `.value`); `AppManifestInfo.status` is already a plain `str`.
- `system_status_response_from(status: SystemStatus) -> SystemStatusResponse`
- `connected_payload_from(status: SystemStatus, session_id: int | None) -> ConnectedPayload` — `session_id` is not part of `SystemStatus`; it is obtained by the caller via `safe_session_id()` and passed separately

Web routes (`apps.py`, `health.py`, `telemetry.py`, `ws.py`) call these mappers instead of receiving pre-mapped response models from RuntimeQueryService.

### Part 4: OpenAPI Codegen for Frontend TypeScript Interfaces

**What changes:** Backend Pydantic response models become the single source of truth for both the Python web layer and generated TypeScript types. Hand-mirrored interfaces in `frontend/src/api/endpoints.ts` are replaced with generated imports.

**Existing infrastructure:** `scripts/export_schemas.py` already generates `frontend/openapi.json` and `frontend/ws-schema.json`. `frontend/package.json` already has `openapi-typescript` as a devDependency and a `types` script. `tests/integration/test_schema_freshness.py` already validates `openapi.json` freshness in CI.

**Extension:** Add TypeScript codegen to `scripts/export_schemas.py` with an optional `--types` flag. After writing `openapi.json`, the script runs `npx openapi-typescript` to generate `frontend/src/api/generated-types.ts`. Update the `package.json` `types` script to output `src/api/generated-types.ts` (currently targets `src/api/types.ts`). Delete the old `types.ts` if it exists.

**CI validation:** `generated-types.ts` is committed to the repo (matching the existing pattern for `ws-schema.json` and `openapi.json`). The frontend CI job runs `npm run types && git diff --exit-code frontend/src/api/generated-types.ts` to validate freshness. The existing `test_schema_freshness.py` continues to validate `openapi.json` freshness in the Python test suite.

**Migration:** Replace hand-written interfaces in `endpoints.ts` with imports from `generated-types.ts`. The `ws-types.ts` interfaces continue to be generated from `ws-schema.json` (separate pipeline, already working).

## Alternatives Considered

**Move web.models into core instead of creating domain objects.** Rejected because it would make core depend on web response semantics (field aliases, serialization config). Domain objects should represent core state, not API responses.

**Use plain dataclasses for domain objects.** Rejected after challenge review. Core already uses Pydantic (`telemetry_models.py`), WS payloads need Pydantic for the schema guard, and mixing conventions in the same layer creates confusion. Using Pydantic throughout eliminates enum coercion issues and keeps `model_dump()` as the single serialization path.

**Post-hoc traceback clearing (approach 2b) for `track_execution()`.** Rejected because it re-duplicates logic at every call site, undermining the goal of consolidating exception handling. The `known_errors` parameter (approach 2a) keeps the decision in one place.

**Inline mapping in each route file instead of `web/mappers.py`.** Rejected because 3-4 routes need the same mappings. Centralizing avoids duplication and makes mapping logic independently testable.

**Generic record factory callable for `_execute()`.** Rejected after challenge review. The factory has no clean typed signature (the two record types differ by one FK field not present in `ExecutionResult`). Two thin wrappers calling `_execute()` are more readable and Pyright-friendly.

## Test Strategy

**Existing coverage is strong:**
- `tests/unit/core/test_runtime_query_service.py` — 13 tests covering app status, events, system status, WS management
- `tests/integration/test_command_executor.py` — 17 tests covering exception contracts, DB persistence, registrations, startup races

**Updates to existing tests:**
- `test_runtime_query_service.py` — update `isinstance` assertions from web model types to domain types. Update imports accordingly.
- `test_command_executor.py` — no behavioral changes expected, but verify all 17 tests pass after both Part 2 (dedup) and Part 1 (SQL extraction).

**New tests:**
- **`tests/unit/core/test_telemetry_repository.py`** — unit tests for each repository method (register_listener, register_job, clear_registrations, persist_batch) using a mock `DatabaseService` with an in-memory SQLite connection.
- **`tests/unit/web/test_mappers.py`** — unit tests for each mapping function, verifying domain-to-response conversion preserves all fields.
- **WS payload shape tests** — the existing `check_schemas_fresh.py` pre-push guard continues to validate WS payload shapes via `WsServerMessage`. No new WS shape test needed since payload types remain Pydantic.
- **OpenAPI freshness check** — CI step that regenerates `frontend/openapi.json` and `frontend/src/api/generated-types.ts` and fails if stale.

**Layer:** Unit tests for Parts 1 and 3 (repository, mappers). Integration tests for Part 2 (execution dedup — the exception contract needs real async execution).

## Open Questions

- ~~The `_run_error_hooks()` stub (referenced as wired in #268) — is that issue still planned?~~ **Resolved:** Remove the stub and all 6 call sites during Part 2. #268 never shipped; the stub is dead code.
- `core/domain_models.py` (Pydantic) will coexist with `core/telemetry_models.py` (also Pydantic). Both are domain models in core using the same library. Consider consolidating into a single `core/models.py` in a follow-up, or document the separation rationale (telemetry = DB query results, domain = live state/events).

## Impact

**Files modified (12):**
- `src/hassette/core/runtime_query_service.py` — remove web.models imports, return domain objects, rewrite event handler construction
- `src/hassette/core/command_executor.py` — replace execution boilerplate + SQL with repository/track_execution calls
- `src/hassette/utils/execution.py` — add `known_errors` parameter to `track_execution()`
- `src/hassette/web/models.py` — WS payload types move to `core/domain_models.py`; wrapper message types import from there
- `src/hassette/web/routes/apps.py` — add mapper calls
- `src/hassette/web/routes/health.py` — add mapper calls
- `src/hassette/web/routes/telemetry.py` — add mapper calls in `dashboard_app_grid()` and `dashboard_kpis()`
- `src/hassette/web/routes/ws.py` — use `connected_payload_from()` mapper
- `src/hassette/web/telemetry_helpers.py` — update type annotations for `get_all_manifests_snapshot()` return type
- `src/hassette/web/utils.py` — update type annotations for `get_all_manifests_snapshot()` return type
- `tests/unit/core/test_runtime_query_service.py` — update assertions to domain types
- `tests/integration/test_command_executor.py` — verify unchanged behavior
- `scripts/export_schemas.py` — extend with `--types` flag to also run `openapi-typescript`
- `frontend/package.json` — update `types` script output path to `src/api/generated-types.ts`

**New files (4-5):**
- `src/hassette/core/telemetry_repository.py` — write-side SQL repository
- `src/hassette/core/domain_models.py` — WS payload + SystemStatus Pydantic domain models
- `src/hassette/web/mappers.py` — domain-to-response mapping functions
- `tests/unit/core/test_telemetry_repository.py` — repository unit tests
- `tests/unit/web/test_mappers.py` — mapper unit tests

**Frontend changes:**
- `frontend/src/api/generated-types.ts` — generated TypeScript types (new, committed)
- `frontend/src/api/endpoints.ts` — replace hand-written interfaces with generated imports

**Schema artifacts:** `frontend/ws-schema.json` must be regenerated via `scripts/export_schemas.py` because class renames (e.g., `AppStatusChangedPayload` → `AppStatusChangedData`) change `$defs` key names in the generated JSON schema.

**Blast radius:** Core and web layers. No changes to app-facing API (`App`, `Bus`, `Scheduler`), no database schema changes. Frontend changes are type-only (generated interfaces replace hand-written ones). The `ws-schema.json` pre-push guard continues to work after regeneration.
