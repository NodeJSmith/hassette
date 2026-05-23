# Context: Web Response Model Hardening

## Problem & Motivation
The web API's response contracts are too loose for typed consumers. Status and classification fields use unconstrained strings, making exhaustive matching impossible. Two endpoints have no declared response schema, and one has a mismatched type annotation. The telemetry query layer has performance bottlenecks: correlated subqueries that scale linearly with handler count, a fan-out pattern that creates one DB query per app instance, and an endpoint that fetches per-item detail only to sum it into aggregates. The execution log endpoint lives under an unintuitive path. The CLI design spec (063-cli-query-tool) is blocked until this ships.

## Visual Artifacts
None.

## Key Decisions
1. **StrEnum for domain types, Literal for display classifications.** `InvocationStatus` is a StrEnum (iterable, named constants for CLI/match-case). `ErrorRateClass`, `HealthStatus`, `ListenerKind` are Literal aliases (output-only values from classification functions).
2. **Three separate status vocabularies, not one.** Instance status reuses `ResourceStatus` (9 values), manifest status gets a new `ManifestStatus` Literal (5 values), system status gets `SystemHealthStatus` Literal (3 values). Conflating them under a single type causes production 500s.
3. **No projection layer.** Telemetry models are already Pydantic models serving as the shared contract. Tighten types directly on them rather than adding near-identical wrapper models.
4. **ROW_NUMBER() CTE for last-error, not MAX(CASE WHEN).** Independent MAX() expressions produce cross-row column mixing. ROW_NUMBER() preserves row coherence and is already used in `get_per_app_last_errors()`.
5. **Purpose-built aggregate query for app_health.** Single CTE-based query returning one row of totals, replacing two detail queries + Python aggregation.
6. **Global listeners query mirroring get_all_jobs_summary().** Eliminates the gather_all_listeners() fan-out (N queries → 1 query).
7. **UUIDv7 via uuid_utils package.** Embeds timestamp for retention disambiguation. UUIDv4 fallback for historical IDs uses `log_retention_days` cutoff.
8. **Clean move for execution endpoint.** `/logs/by-execution/{id}` → `/executions/{execution_id}`, no alias. Frontend and CLI spec updated in the same PR.
9. **_snapshot_lock removal.** After ROW_NUMBER() CTE rewrite, `get_all_jobs_summary` becomes a single-statement query and no longer needs the lock.

## Constraints & Anti-Patterns
- Do NOT create a single `AppStatus` type — three distinct status vocabularies exist (ResourceStatus, ManifestStatus, SystemHealthStatus).
- Do NOT add projection models wrapping telemetry models — tighten types in place.
- Do NOT use `asyncio.gather` for dashboard queries — WAL snapshot isolation concerns.
- Do NOT use `MAX(CASE WHEN ...)` for last-error columns — produces row-incoherent results.
- Do NOT add `_snapshot_lock` to new single-statement queries — SQLite guarantees consistency within a single statement.
- Do NOT use `database.retention_days` for the UUIDv4 fallback — use `log_retention_days`.
- `_health_status_from_summary()` must return `"excellent"` for zero-invocation apps, not `"unknown"`.
- The `"unknown"` health status value must NOT exist in the HealthStatus Literal.

## Design Doc References
- `## Architecture > Constrained type definitions` — which types to create, where they live, what fields they apply to
- `## Architecture > Route fixes` — which routes need response_model, model_validate, return type fixes
- `## Architecture > Execution endpoint` — new route, UUIDv7 switch, CLI spec update
- `## Architecture > Query performance` — correlated subquery rewrite, aggregate query, global listeners, indexes
- `## Replacement Targets` — table of what's being replaced and by what
- `## Edge Cases` — all edge cases to handle
- `## Test Strategy` — existing tests to adapt, new coverage needed, tests to remove
- `## Key Constraints` — ROW_NUMBER coherence, services endpoint opacity, instance_index default

## Convention Examples

### Response model structure
**Source:** `src/hassette/web/models.py`
```python
class BootIssueResponse(BaseModel):
    severity: Literal["err", "warn"]
    label: str
    detail: str
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
    ...
```
Existing composite mappers follow this pattern: pure function, explicit field copy. No new mappers are needed for this change — telemetry models are returned directly from routes.

### Route with response_model
**Source:** `src/hassette/web/routes/health.py`
```python
@router.get("/health", response_model=SystemStatusResponse, responses={503: {"model": SystemStatusResponse}})
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
Reusable Literal type aliases live in the module closest to their consumers.

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
Revision IDs are simple numeric strings. Downgrades use `IF EXISTS` for idempotency.
