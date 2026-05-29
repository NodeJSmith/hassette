# Context: Database Schema Redesign

## Problem & Motivation
Execution records are split across two near-identical tables (`handler_invocations`, `job_executions`), forcing every telemetry feature to be implemented twice — storage, queries, API responses, WS messages, and frontend components. The duplication cascades through every layer. 11 open database issues exist, 3 of which require adding columns to both tables. The query service (1,187 lines) and repository (687 lines) are each ~40% pure duplication. Listener identity relies on a fragile computed key, and each listener carries two IDs (in-memory and database) that can disagree, producing orphan records. The migration tool (Alembic) is unused beyond running hand-written SQL, but its 3-dependency chain remains.

## Visual Artifacts
None.

## Key Decisions
1. Unify `handler_invocations` + `job_executions` into a single `executions` table with a `kind` discriminator. Registration tables (`listeners`, `scheduled_jobs`) stay separate.
2. Two nullable FK columns (`listener_id`, `job_id`) with CHECK constraint enforcing exactly one non-null per row.
3. `name=` becomes required on all DB-registered listeners. Natural key: `(owner_key, instance_index, name, topic)`. Cancel-listeners are exempt (bypass DB). Once-listeners participate in upsert dedup.
4. Synchronous registration — DB INSERT awaited inline, no background tasks. DB row ID is the only identifier.
5. Replace Alembic with `PRAGMA user_version` + ~35-line runner. Migration chain resets to 001 (delete-recreate).
6. `app_key` renames to `owner_key` across all layers (mechanical codemod, separate first commit).
7. `_listener_meta`/`_job_meta` dicts replaced by adding `owner_key`/`instance_index` directly to completion event payloads.
8. `AppHealthSummary` retains split fields (`total_invocations`/`total_executions`) for API stability. Aggregation queries reconstruct by kind.
9. `ActivityFeedEntry.row_id` switches to `execution_id` UUID.
10. `dropped_no_session` counter removed from all layers (dead code under synchronous registration).

## Constraints & Anti-Patterns
- The `owner_key` rename MUST land as a separate commit before any schema changes — ~613 occurrences would obscure structural diffs.
- Upsert `ON CONFLICT` target must exactly match the unique index expression — divergence causes silent INSERT.
- `_RETENTION_TABLES` and parent-guard DELETEs hard-code table names — must update to `executions`.
- `BusService` and `SchedulerService` must both declare `depends_on: [DatabaseService]`.
- Do NOT implement Non-Goals: statistics aggregation (#672), per-app retention (#651), configurable intervals (#564), seeding script (#854), execution registry (#834).
- Do NOT add CHECK constraints beyond the two specified in 001.sql (kind and FK mutex).
- `auto_vacuum` PRAGMA requires a separate raw `sqlite3.Connection` before any transaction — cannot be inside `BEGIN IMMEDIATE`.

## Design Doc References
- `## Architecture > ### Schema` — unified table DDL, indexes, new columns
- `## Architecture > ### Listener Identity` — natural key, once-listener behavior
- `## Architecture > ### Synchronous Registration` — registration flow changes
- `## Architecture > ### Migration Runner` — PRAGMA user_version runner steps
- `## Architecture > ### Query Service Module Structure` — decomposition into telemetry/ submodules
- `## Architecture > ### Reconciliation and Retention` — table name changes in SQL
- `## Architecture > ### API Unification` — endpoint paths, discriminated union response
- `## Architecture > ### Frontend` — WS signal merge, routing, badge removal
- `## Registration Errors` — exception classes and message templates
- `## Edge Cases` — once-listeners, cancel-listeners, concurrent registration, row_id format
- `## Replacement Targets` — what gets deleted/rewritten
- `## Convention Examples` — SQL fragment pattern, INSERT param builder, depends_on, WS messages, DB_ERRORS

## Convention Examples
### SQL query builder pattern — parameterized fragment + bind params

**Source:** `src/hassette/core/telemetry_query_service.py:59-76`

```python
def _source_tier_clause(source_tier: QuerySourceTier, alias: str) -> tuple[str, dict[str, str]]:
    match source_tier:
        case "all":
            return ("", {})
        case "app" | "framework":
            return (f"AND {alias}.source_tier = :source_tier", {"source_tier": source_tier})
        case _ as unreachable:
            assert_never(unreachable)
```

### INSERT param builder — dict-from-record

**Source:** `src/hassette/core/telemetry_repository.py:27-52`

```python
def _inv_insert_params(record: HandlerInvocationRecord) -> dict[str, Any]:
    return {
        "listener_id": record.listener_id,
        "session_id": record.session_id,
        "execution_start_ts": record.execution_start_ts,
        # ... all columns
        "execution_id": record.execution_id,
    }
```

### Service class with `depends_on`

**Source:** `src/hassette/core/command_executor.py:67-83`

```python
class CommandExecutor(Service):
    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=120,
    )
```

### DB_ERRORS catch pattern

**Source:** `src/hassette/web/CLAUDE.md`

```python
from hassette.web.dependencies import DB_ERRORS

try:
    result = await telemetry.some_query()
except DB_ERRORS:
    LOGGER.warning("Failed to fetch ...", exc_info=True)
    response.status_code = 503
    return []
```
