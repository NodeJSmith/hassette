# Design: Harden Web API Response Models

**Date:** 2026-05-23
**Status:** approved
**Scope-mode:** hold
**Issue:** #832

## Problem

The web API's response contracts are too loose for typed consumers. Status and classification fields use unconstrained strings, making it impossible for consumers to exhaustively match on values without guessing. Two endpoints have no declared response schema at all, and one has a mismatched type annotation. These gaps prevent a CLI tool — and any future typed consumer — from reliably rendering or validating API output.

Separately, the telemetry query layer has performance bottlenecks: per-record subqueries that scale linearly with the number of registered handlers, and sequential database calls where parallel execution is safe. These compound the response model problem — a consumer that can't trust the shape also can't trust the latency.

Finally, the execution log endpoint lives under an unintuitive path that conflates log retrieval with execution identity. A dedicated execution-scoped path better matches the domain concept and aligns with the CLI's noun-based command structure.

## Goals

- Every API endpoint returns a response with a declared, typed schema — no untyped dictionaries or implicit shapes
- All fields with a fixed set of valid values use constrained types, enabling exhaustive matching by consumers
- The most expensive telemetry queries complete in sub-linear time relative to the number of registered handlers
- Execution logs are accessible via an execution-scoped path that matches the domain model
- The CLI design spec (063-cli-query-tool) is fully unblocked after this ships

## Non-Goals

- Pagination support for list endpoints — follow-up work
- Composite execution detail endpoint (combining logs + invocation metadata + job results) — deferred to CLI v2
- Multi-instance aggregation (returning data across all instances of a multi-instance app) — document the current behavior, don't change it
- Decomposing the telemetry query service or repository into smaller modules (#811, #812) — separate issue
- Query execution timeouts (#713) — separate issue
- Execution registry table for definitive 404 on unknown execution IDs (#834) — UUIDv7 covers retention disambiguation; the registry adds typo detection as a follow-up

## User Scenarios

### CLI Developer: Building a typed consumer

- **Goal:** Query any hassette API endpoint and render the response reliably
- **Context:** Writing a CLI tool that maps API responses to terminal output (tables, colored status indicators, structured JSON)

#### Querying handler health

1. **Requests health data for an app**
   - Sees: error rate, health classification, handler summaries
   - Decides: whether to investigate further based on health status
   - Then: system returns a response where every status/classification field has a known, enumerated set of values

2. **Renders status indicators**
   - Sees: constrained status values that map directly to display output (colors, icons, labels)
   - Decides: nothing — the mapping is exhaustive and deterministic
   - Then: no fallback "unknown status" case is needed because the type system guarantees completeness

#### Fetching execution logs

1. **Looks up logs for a specific execution**
   - Sees: a list of log records with level, message, timestamp, and correlation metadata
   - Decides: whether the execution completed normally based on log content
   - Then: system returns logs via an execution-scoped path, not buried under a logging sub-resource

#### Handling server errors

1. **Server is unreachable**
   - Sees: a connection error naming the server URL
   - Decides: whether the server is down or misconfigured
   - Then: CLI suggests checking if hassette is running at the configured address

2. **Server returns a temporary error (e.g., database locked)**
   - Sees: a warning that the server reported a temporary error, with zero-value or empty data
   - Decides: whether to retry or investigate the server
   - Then: CLI exits with a non-zero status code so scripts can detect the failure

### Framework Operator: Monitoring via dashboard

- **Goal:** View real-time handler and job status without latency spikes
- **Context:** Checking the web dashboard during an incident or routine monitoring

#### Loading the dashboard

1. **Opens the dashboard page**
   - Sees: app grid with health indicators, handler counts, error rates
   - Decides: which app to investigate based on health classification
   - Then: system responds within a consistent time budget regardless of how many handlers are registered or how much invocation history exists

## Functional Requirements

- **FR#1** Every field that carries a value from a fixed, enumerated set uses a constrained type that rejects values outside that set at validation time
- **FR#2** Every API endpoint declares a typed response schema that the framework validates before sending to the consumer
- **FR#3** The handler summary query does not execute per-handler subqueries; aggregate error information is computed in a single pass over the data
- **FR#4** The app health endpoint uses a purpose-built aggregate query instead of fetching per-item detail and aggregating client-side
- **FR#5** The global listeners endpoint uses a single query returning all listeners across all apps and instances, not a fan-out of per-instance queries
- **FR#6** Database indexes support the query patterns used by handler and job summary aggregation, including filtered lookups by status
- **FR#7** Execution logs are served from a path scoped to the execution concept, not nested under a logging sub-resource
- **FR#8** The previous execution log path is removed (not aliased) and all internal consumers are updated to use the new path
- **FR#9** Per-app telemetry endpoints document their instance-scoping behavior so consumers know they are receiving data for a single instance, not an aggregate

## Edge Cases

- A handler invocation has a status value written before the constrained type was introduced — validation must accept all historically valid values including those added by later migrations
- A fresh app with zero invocations queries health — the health classification function returns `"excellent"` (consistent with the 503 fallback path), not a separate `"unknown"` value. The `HealthStatus` Literal covers this case without a fifth value
- An execution ID that has never existed but has a valid UUIDv7 format returns an empty log list — `retention_expired` is determined by extracting the timestamp from the UUID itself (no DB lookup needed). A malformed or non-UUIDv7 execution ID returns 422
- The services endpoint proxies data from an external system with an unpredictable schema — the response model must declare this as an opaque typed container rather than attempting to validate its internal structure
- A multi-instance app is queried without specifying an instance index — the endpoint returns data for the default instance (index 0) and the response documentation makes this explicit
- A database row contains a status value not in the Literal type (data corruption bypassing SQLite CHECK constraints) — the Pydantic ValidationError propagates as a 500; this surfaces genuine corruption rather than hiding it. The CHECK constraints make this near-impossible; if it occurs, it's a real bug.
- The database is unavailable when the execution endpoint is queried — the endpoint returns 503 with an empty response, matching the existing telemetry endpoint pattern (`try/except DB_ERRORS`)

## Acceptance Criteria

- **AC#1** All status, health classification, error rate classification, log level, listener kind, and source tier fields across all response models reject values not in their declared set (FR#1)
- **AC#2** Every route in the web layer has an explicit `response_model` parameter — no implicit or untyped returns remain (FR#2)
- **AC#3** The handler summary query executes zero per-handler subqueries regardless of how many handlers are registered (FR#3)
- **AC#4** The app health endpoint issues a single aggregate query that returns one row of totals, not per-listener/per-job detail (FR#4)
- **AC#5** The global listeners endpoint (`GET /bus/listeners` without an app_key filter) issues a single database query, not one per app instance (FR#5)
- **AC#6** Composite indexes exist for the status-filtered lookup patterns used by handler and job summary aggregation (FR#6)
- **AC#7** `GET /api/executions/{execution_id}` returns log records for the given execution, reusing the existing log response shape (FR#7)
- **AC#8** `GET /api/logs/by-execution/{execution_id}` no longer exists — requests to the old path return 404 (FR#8)
- **AC#9** Frontend code that previously called the old execution log path calls the new path instead (FR#8)
- **AC#10** Per-app telemetry endpoint parameters include documentation describing instance-scoping behavior (FR#9)
- **AC#11** The OpenAPI specification and generated TypeScript types reflect all model changes
- **AC#12** The existing test suite passes with no regressions; new behaviors have corresponding test coverage

## Key Constraints

- The last-error aggregation uses `ROW_NUMBER()` window functions for row coherence — all error detail columns come from the same invocation row. This matches the pattern already used in `get_per_app_last_errors()`.
- The services endpoint proxies an external system's schema — do not attempt to model its internal structure. Declare it as an opaque typed container.
- Do not change the default behavior of `instance_index=0` on per-app endpoints. Document it; do not change it.

## Dependencies and Assumptions

- The CLI design spec (063-cli-query-tool in the `worktree-cli` branch) depends on this work shipping first. The CLI assumes all response models are typed and all status fields are constrained.
- The frontend uses generated TypeScript types from the OpenAPI spec. Type changes propagate automatically via codegen, but the frontend build must pass after regeneration.
- The telemetry database uses SQLite with WAL mode. Multi-statement read methods that require snapshot consistency use `BEGIN DEFERRED` under `_snapshot_lock` (e.g., `get_all_app_summaries`). After the `ROW_NUMBER()` CTE rewrite, `get_all_jobs_summary` and the new `get_all_listeners_summary` become single-statement queries and no longer need the lock — SQLite guarantees consistency within a single statement.
- Migration numbering continues from `009` (the latest existing migration).

## Architecture

### Constrained type definitions

Two kinds of constrained types, chosen based on usage pattern:

**New StrEnum** for domain concepts used across multiple layers (CLI filters, match/case, display formatting):
- `InvocationStatus` (`success`, `error`, `cancelled`, `timed_out`) — in `src/hassette/types/types.py` alongside `SourceTier`

**Reuse existing types:**
- `ResourceStatus` (StrEnum, 9 values) — already exists at `src/hassette/types/enums.py:84`. Apply to `AppInstanceResponse.status` and `ServiceInfoResponse.status`. Do NOT create a new type for these fields.
- `SystemStatus.status: Literal["ok", "degraded", "starting"]` — already typed at `src/hassette/core/domain_models.py:62`. Extract as `SystemHealthStatus = Literal["ok", "degraded", "starting"]` and apply to `SystemStatusResponse.status`.
- `LOG_LEVEL_TYPE = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]` — already exists at `src/hassette/types/types.py:18`. Do NOT define a new `LogLevel` alias.
- `SourceTier` — already exists at `src/hassette/types/types.py:21`. Apply to `LogEntryResponse.source_tier`.

**New Literal aliases** for display classifications and value sets without existing types:
- In `src/hassette/web/models.py`: `ManifestStatus = Literal["disabled", "blocked", "running", "failed", "stopped"]`, `ErrorRateClass = Literal["good", "warn", "bad"]`, `HealthStatus = Literal["excellent", "good", "warning", "critical"]`, `ListenerKind = Literal["state change", "service call", "event"]`

Apply the types to their respective model fields:
- In `src/hassette/core/telemetry_models.py`: `InvocationStatus` on `HandlerInvocation.status`, `JobExecution.status`, `ActivityFeedEntry.status`; `LOG_LEVEL_TYPE` on `LogRecord.level` (no CHECK constraint exists on `log_records.level`, but the risk is low — hassette controls the `DatabaseLogHandler` and only standard Python levels are expected; a non-standard level surfacing as a ValidationError is acceptable)
- In `src/hassette/web/models.py`:
  - `ResourceStatus` on `AppInstanceResponse.status`, `ServiceInfoResponse.status` (instance-scoped, 9 values)
  - `ManifestStatus` on `AppManifestResponse.status`, `DashboardAppGridEntry.status` (manifest-scoped, 5 values)
  - `SystemHealthStatus` on `SystemStatusResponse.status` (system-scoped, 3 values)
  - `InvocationStatus` on `InvocationCompletedData.status`, `ExecutionCompletedData.status` (WebSocket payload models — same values as HTTP)
  - Plus the Literal aliases (`ErrorRateClass`, `HealthStatus`, `ListenerKind`) on their respective fields

The three status vocabularies are distinct concepts from distinct sources — conflating them under a single type causes production 500s when any instance is in a transient state. See Alternatives Considered for the rejected single-type approach.

The `InvocationStatus` StrEnum must include `CANCELLED` — while `TIMED_OUT` was added in migration 005, the enum must cover all values the database can contain. Verify by checking the CHECK constraints in migrations 001 and 005 and grepping for status string assignments. Pydantic v2 coerces string values to StrEnum members automatically on model construction and serializes them back to plain strings in JSON responses.

### Route fixes

The telemetry models in `core/telemetry_models.py` are already Pydantic models and serve as the shared contract between the query service and the web layer. Rather than adding a projection layer of near-identical models, tighten the Literal types directly on the telemetry models and continue returning them from routes. This avoids model sprawl — the codebase has three model layers (runtime domain, telemetry query results, web composites), and a fourth projection layer would add indirection without filtering any fields.

Routes that already return telemetry models (`HandlerInvocation`, `JobExecution`, `JobSummary`, `ActivityFeedEntry`) continue to do so — the models themselves become stricter.
- `src/hassette/web/routes/events.py`: add `response_model=list[EventEntry]`, convert returned dicts via `EventEntry.model_validate()`.
- `src/hassette/web/routes/services.py`: add `response_model=dict[str, Any]` to the decorator.
- `src/hassette/web/routes/logs.py`: fix function signature from `-> list[dict]` to `-> list[LogEntryResponse]`, add `model_validate` mapping (both `get_logs_recent` and `get_logs_by_execution` — the latter already has this pattern at line 91).
- `src/hassette/web/telemetry_helpers.py`: annotate `classify_error_rate() -> ErrorRateClass` and `classify_health_bar() -> HealthStatus` so Pyright enforces the Literal constraint at the producer, not just the model consumer.
- All per-app telemetry routes: add `description` to the `instance_index` Query parameter.

### Execution endpoint

Create `src/hassette/web/routes/executions.py` with `GET /executions/{execution_id}`. The handler:
1. Validates the execution_id is a well-formed UUIDv7 — return 422 if malformed
2. Extracts the embedded timestamp from the UUIDv7 to determine `retention_expired` — no `check_execution_predates_retention_cutoff()` DB query needed
3. Calls `_repo.get_log_records_by_execution` for log records
4. Returns `LogsByExecutionResponse` (reuse — it already has the right shape: `records`, `truncated`, `retention_expired`)

Reuse `LogsByExecutionResponse` as the response model.

**Switch execution ID generation from UUIDv4 to UUIDv7.** Find where execution IDs are generated (`src/hassette/core/command_executor.py:421, 491` — grep for `uuid4`) and replace with `uuid_utils.uuid7()`. Add `uuid-utils` to `pyproject.toml` dependencies — it's a thin Rust-backed wrapper with no transitive dependencies and a stable API.

Existing UUIDv4 execution IDs in the database remain valid — the endpoint accepts both formats but can only extract timestamps from UUIDv7 IDs. For UUIDv4 IDs, fall back to the existing `check_execution_predates_retention_cutoff()` DB query using `log_retention_days` (not `database.retention_days`) as the cutoff, consistent with `routes/logs.py:102`. The UUIDv4 fallback path remains active for the duration of the log retention window (default 3 days) then becomes dead code as all executions roll over to UUIDv7. Update docstrings on `HandlerInvocation.execution_id` and `JobExecution.execution_id` from "UUID4 string" to "UUID string (UUIDv7 for new executions, UUIDv4 for historical)".

Remove `get_logs_by_execution` from `routes/logs.py` and its route registration. Register the new router in `src/hassette/web/app.py`.

Update the frontend to call `/api/executions/{execution_id}` instead of `/api/logs/by-execution/{execution_id}`. Search for the old path in `frontend/src/` to find all call sites.

**Update the CLI design spec** (063-cli-query-tool in the `worktree-cli` branch): change the command table entry for `hassette execution <uuid>` from `GET /api/logs/by-execution/{id}` to `GET /api/executions/{execution_id}`. The CLI spec is approved but unimplemented — this is a one-line documentation update.

### Query performance

**Correlated subquery rewrite** in `src/hassette/core/telemetry_query_service.py`:

Replace the `LEFT JOIN handler_invocations last_err ON last_err.id = (SELECT ...)` pattern in `get_listener_summary` (line ~231), `get_job_summary` (line ~302), and `get_all_jobs_summary` (line ~375) with a `ROW_NUMBER()` window function approach, using the pattern already established in `get_per_app_last_errors()` (`telemetry_query_service.py:718`):

```sql
-- CTE: rank errors by recency per listener
WITH ranked_errors AS (
    SELECT listener_id, error_type, error_message, error_traceback, execution_start_ts,
           ROW_NUMBER() OVER (PARTITION BY listener_id ORDER BY execution_start_ts DESC) AS rn
    FROM handler_invocations
    WHERE status IN ('error', 'timed_out')
)
-- Join only the most recent error (rn = 1) per listener
LEFT JOIN ranked_errors last_err ON last_err.listener_id = l.id AND last_err.rn = 1
```

This eliminates O(N) correlated subqueries while preserving row coherence — all four error columns (`error_type`, `error_message`, `error_traceback`, `execution_start_ts`) come from the same invocation row. The independent `MAX(CASE WHEN ...)` approach was rejected because it produces cross-row column mixing: each `MAX()` independently selects the lexicographically largest string per column, combining values from different error rows.

**Purpose-built aggregate query** in `src/hassette/core/telemetry_query_service.py`:

Add a `get_app_health_aggregates()` method that returns a single row of totals (total invocations, handler errors, handler timed_out, handler avg duration, total executions, job errors, job timed_out, job avg duration, last activity timestamp) using two CTEs (`handler_agg`, `job_agg`) joined in one query. This replaces the `app_health` route's current pattern of calling `get_listener_summary()` + `get_job_summary()` and aggregating in Python. The existing `get_all_app_summaries()` method already takes this approach — this aligns `app_health` with that pattern.

Update `src/hassette/web/routes/telemetry.py` `app_health` to call `get_app_health_aggregates()` instead of the two detail queries. The route's response assembly simplifies to reading fields from a single result object instead of summing across lists.

**Global listeners query** in `src/hassette/core/telemetry_query_service.py`:

Add a `get_all_listeners_summary()` method mirroring the existing `get_all_jobs_summary()`. A single query returning all listeners across all apps and instances with aggregated invocation stats — no `WHERE app_key = :app_key AND instance_index = :instance_index` filter. The ROW_NUMBER() CTE rewrite applies here too.

Both `get_all_listeners_summary()` and `get_all_jobs_summary()` become single-statement queries after the ROW_NUMBER() CTE rewrite — SQLite guarantees consistency within a single statement, so `_snapshot_lock` and `BEGIN DEFERRED` are no longer needed on either method. Remove the lock acquisition from `get_all_jobs_summary()` as part of the CTE rewrite. The new `get_all_listeners_summary()` does not need the lock at all.

Update `src/hassette/web/routes/bus.py` to call `get_all_listeners_summary()` directly when no `app_key` filter is provided, replacing the `gather_all_listeners()` fan-out in `src/hassette/web/utils.py`. The current fan-out creates one `get_listener_summary()` call per app instance (e.g., 10 apps × 3 instances = 30 queries), each containing a correlated subquery. The jobs endpoint already avoids this pattern via `get_all_jobs_summary()`.

**Composite indexes** via new migration `010_perf_indexes.py`:
- `CREATE INDEX idx_hi_listener_status_time ON handler_invocations(listener_id, status, execution_start_ts DESC)`
- `CREATE INDEX idx_je_job_status_time ON job_executions(job_id, status, execution_start_ts DESC)`

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `GET /api/logs/by-execution/{execution_id}` in `routes/logs.py` | `GET /api/executions/{execution_id}` in `routes/executions.py` | Remove the route and handler from `logs.py`; create new route file |
| Correlated `LEFT JOIN ... ON id = (SELECT ... LIMIT 1)` in `telemetry_query_service.py` (3 occurrences) | `ROW_NUMBER()` window function CTE for row-coherent last-error data | Rewrite the SQL in all three methods; remove `_snapshot_lock` from `get_all_jobs_summary()` since the CTE makes it a single-statement query |
| Sequential `get_listener_summary()` + `get_job_summary()` calls in `telemetry.py` app_health route, with client-side aggregation | Single `get_app_health_aggregates()` query returning one row of totals | Replace two detail queries + Python aggregation with one purpose-built aggregate query |
| `gather_all_listeners()` fan-out in `web/utils.py` — one `get_listener_summary()` call per app instance | Single `get_all_listeners_summary()` query in `TelemetryQueryService` | Replace N per-instance queries with one global query, mirroring `get_all_jobs_summary()` |
| Bare `str` status fields on `HandlerInvocation`, `JobExecution`, `JobSummary`, `ActivityFeedEntry` | `Literal` type aliases (`InvocationStatus`, etc.) applied directly to the telemetry models | Update field type annotations in `core/telemetry_models.py` |

## Migration

Migration `010_perf_indexes.py` adds two composite indexes to existing tables. This is an additive, non-destructive change — no data is modified, no columns are added or removed. The migration is fully reversible via `DROP INDEX IF EXISTS`. Existing data is unaffected; SQLite builds the indexes from existing rows on upgrade.

No data format changes. No schema column changes. The Literal type constraints are enforced at the application layer (Pydantic validation), not at the database layer — existing data with valid status values will pass validation unchanged.

## Convention Examples

### Response model structure

**Source:** `src/hassette/web/models.py`

```python
class BootIssueResponse(BaseModel):
    severity: Literal["err", "warn"]
    label: str
    detail: str

class SystemStatusResponse(BaseModel):
    status: str
    websocket_connected: bool
    uptime_seconds: float
    entity_count: int
    app_count: int
    services_running: list[str]
    services: list[ServiceInfoResponse] = Field(default_factory=list)
    version: str = ""
    boot_issues: list[BootIssueResponse] = Field(default_factory=list)
    log_records_dropped: int = 0
```

`BootIssueResponse.severity` demonstrates the existing Literal pattern. New constrained fields should follow this — type alias for reuse, applied directly to the field.

### Domain-to-web mapper

**Source:** `src/hassette/web/mappers.py`

```python
def system_status_response_from(status: SystemStatus) -> SystemStatusResponse:
    boot_issues = [
        BootIssueResponse(severity=issue.severity, label=issue.label, detail=issue.detail)
        for issue in status.boot_issues
    ]
    services = [
        ServiceInfoResponse(
            name=svc.name, status=svc.status, role=svc.role,
            ready_phase=svc.ready_phase, retry_at=svc.retry_at,
        )
        for svc in status.services
    ]
    return SystemStatusResponse(
        status=status.status,
        websocket_connected=status.websocket_connected,
        uptime_seconds=status.uptime_seconds,
        entity_count=status.entity_count,
        app_count=status.app_count,
        services_running=status.services_running,
        services=services,
        version=status.version,
        boot_issues=boot_issues,
        log_records_dropped=status.log_records_dropped,
    )
```

Existing composite mappers (domain object → web response model) follow this pattern: pure function, explicit field copy, nested models built via list comprehension. No new mappers are needed for this change — telemetry models are returned directly from routes.

### Route with response_model

**Source:** `src/hassette/web/routes/health.py`

```python
@router.get(
    "/health",
    response_model=SystemStatusResponse,
    responses={503: {"model": SystemStatusResponse}},
)
async def get_health(runtime: RuntimeDep, response: Response) -> SystemStatusResponse:
    status_data = runtime.get_system_status()
    if status_data.status != "ok":
        response.status_code = 503
    return system_status_response_from(status_data)
```

Every route must have `response_model=` in the decorator and a matching return type annotation.

### Literal type alias

**Source:** `src/hassette/types/types.py`

```python
SourceTier = Literal["app", "framework"]
```

Reusable Literal type aliases live in the module closest to their consumers. `SourceTier` is shared across core and web layers, so it lives in `types/`. New aliases used only by web models belong in `web/models.py`.

### Migration structure

**Source:** `src/hassette/migrations/versions/009_log_records_table.py`

```python
revision = "009"
down_revision = "008"

def upgrade() -> None:
    op.execute("CREATE INDEX idx_lr_exec ON log_records(execution_id) WHERE execution_id IS NOT NULL")

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_lr_exec")
```

Revision IDs are simple numeric strings. Downgrades use `IF EXISTS` for idempotency. Index names use predictable prefixes derived from the table name.

## Alternatives Considered

**All Literal for every value set.** Simpler and matches existing `SourceTier` pattern, but domain-level status types (`InvocationStatus`, `AppStatus`) benefit from StrEnum's iterability, named constants, and potential for domain methods. Using Literal everywhere forces string matching in CLI formatters and match/case blocks. Rejected for domain types; kept for display classifications.

**All StrEnum for every value set.** Consistent but adds class definitions for types that are just classification outputs (`ErrorRateClass`, `HealthStatus`). These are output-only values from helper functions, not domain concepts that flow through multiple layers. Over-engineering for display values. Rejected.

**Web-layer projection models wrapping telemetry models.** Would add `HandlerInvocationResponse`, `JobExecutionResponse`, `JobSummaryResponse`, `ActivityFeedEntryResponse` as web-layer wrappers with mapper functions. Rejected because the telemetry models are already Pydantic models that serve as a shared contract — inspection showed no fields that need hiding from API consumers (`args_json`/`kwargs_json` on `JobSummary` are useful diagnostic info). Adding 4 near-identical models + 4 mapper functions creates model sprawl and maintenance burden without filtering anything. Tightening Literal types directly on the telemetry models achieves the same type safety with zero new code.

**asyncio.gather to parallelize the two existing detail queries for app_health.** Reduces wall-clock time from sequential to concurrent, but still fetches per-listener and per-job detail only to sum it into aggregates. The database can compute the aggregates directly in a single query — asking a better question is preferable to running the wrong question faster. Rejected.

**Independent MAX(CASE WHEN) for last-error columns instead of ROW_NUMBER().** Simpler SQL, but produces row-incoherent results: `error_type`, `error_message`, and `error_traceback` each come from whichever row sorts lexicographically last per column, not from the same error. This is not a same-millisecond tie-breaking edge case — it happens routinely with varied error types. Rejected in favor of `ROW_NUMBER()`, which is already used in `get_per_app_last_errors()` and guarantees all error columns come from the same row.

**Keep /logs/by-execution/{id} as an alias alongside the new /executions/{id} path.** Avoids breaking the frontend temporarily, but creates two paths to the same data — confusing for consumers and docs. Since we control the frontend and can update it in the same PR, a clean move is better. Rejected.

## Test Strategy

### Existing Tests to Adapt

- `tests/integration/web_api/test_endpoints.py` — 4 tests for `GET /api/logs/by-execution/{id}` must be moved/rewritten to test `GET /api/executions/{execution_id}` with the new route path and import
- `frontend/src/test/handlers.ts` — MSW mock registered for `"/api/logs/by-execution/:execution_id"` must be updated to `"/api/executions/:execution_id"` alongside the `endpoints.ts` API call update
- `tests/integration/web_api/test_telemetry.py` — response field assertions should continue to pass since the telemetry models are returned directly (no field name changes); verify Literal type tightening doesn't break mock data setup
- `tests/integration/web_api/test_telemetry_route.py` — enrichment tests for job summaries should be unaffected since the model type is unchanged
- `tests/integration/web_api/test_validation.py` — DB error guard tests should be unaffected; verify after implementation
- `tests/integration/telemetry/test_telemetry_query_service.py` — tests for `get_listener_summary` and `get_job_summary` must pass with the rewritten SQL; the `last_error_*` fields in the result model need verification

### New Test Coverage

- **Literal/StrEnum validation** (FR#1): unit tests confirming Pydantic rejects out-of-range values for `InvocationStatus`, `ManifestStatus`, `ResourceStatus`, `ErrorRateClass`, `HealthStatus`, `ListenerKind`, `LOG_LEVEL_TYPE`
- **Execution endpoint** (FR#8, FR#9): happy path, truncation, retention expiry, empty results, and 404 on old path
- **Last-error aggregation correctness** (FR#3): verify that `get_listener_summary` returns correct error fields after the SQL rewrite — multiple errors at different timestamps, single error, no errors
- **Aggregate query correctness** (FR#4): verify `get_app_health_aggregates()` returns correct totals matching the sum of per-item detail queries; test with mixed handler/job success/error/timed_out statuses
- **Global listeners query** (FR#5): verify `get_all_listeners_summary()` returns all listeners across apps/instances matching the combined results of per-instance calls

### Tests to Remove

- The 4 tests in `test_endpoints.py` for the old `/api/logs/by-execution/{id}` path are replaced by new tests for `/api/executions/{execution_id}` — remove the originals after the new tests are written.

## Documentation Updates

- **OpenAPI spec** (`openapi.json`): regenerated automatically — Literal types appear as string enums, new `/executions/{id}` path appears, old `/logs/by-execution/{id}` path removed
- **Generated TypeScript types** (`frontend/src/api/generated-types.ts`): regenerated automatically — union string types replace bare `string` for status fields
- **`instance_index` parameter descriptions**: added inline via FastAPI `Query(description=...)` on per-app telemetry routes — these flow into the OpenAPI spec automatically
- No docs site (`docs/`) changes required — the affected endpoints are internal framework telemetry, not user-facing API documentation

## Impact

### Changed Files

**Shared / cross-cutting (higher risk):**
- `src/hassette/web/models.py` — add type aliases, apply Literal types to existing web models
- `src/hassette/core/telemetry_models.py` — apply Literal types to existing fields (shared contract between query service and web routes)
- `src/hassette/web/app.py` — register new executions router

**Route files:**
- `src/hassette/web/routes/telemetry.py` — switch app_health to `get_app_health_aggregates()`, add instance_index descriptions
- `src/hassette/web/routes/logs.py` — fix return type mismatch, remove by-execution route
- `src/hassette/web/routes/events.py` — add response_model, convert to EventEntry
- `src/hassette/web/routes/services.py` — add response_model
- `src/hassette/web/routes/bus.py` — add instance_index description
- `src/hassette/web/routes/executions.py` — new file

**Query layer:**
- `src/hassette/core/telemetry_query_service.py` — rewrite correlated subqueries to ROW_NUMBER() CTEs, add `get_app_health_aggregates()` and `get_all_listeners_summary()`, remove `_snapshot_lock` from `get_all_jobs_summary()`

**Migration:**
- `src/hassette/migrations/versions/010_perf_indexes.py` — new file

**Frontend:**
- `frontend/src/` — update API call paths from `/logs/by-execution/` to `/executions/`
- `frontend/src/api/generated-types.ts` — regenerated

**Schema:**
- `openapi.json` — regenerated

### Behavioral Invariants

- All existing telemetry route responses must continue returning the same data fields (values may become more strictly typed, but no fields removed)
- The dashboard app grid must continue loading with the same visual output
- WebSocket message types (`WsServerMessage` discriminated union) are unchanged
- Job summary enrichment with live heap data (`next_run`, `fire_at`, `jitter`) must continue working — the `JobSummary` model is unchanged except for tighter field types
- Log record queries must return identical results — the SQL rewrite only affects how "last error" is computed, not the log records themselves

### Blast Radius

- **Frontend**: TypeScript types regenerated — `string` fields become union literals. Frontend build must pass. The execution log path change requires updating API call sites.
- **CLI design spec**: unblocked — all prerequisites satisfied
- **Tests**: test files need adaptation for the execution endpoint route path change; Literal type tightening should be transparent to existing tests
- **OpenAPI consumers**: the spec changes (new path, removed path, tighter types) — any external consumer of the spec is affected

## Open Questions

None — all questions resolved during discovery.
