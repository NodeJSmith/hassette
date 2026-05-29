---
task_id: "T09"
title: "Unify REST API and WS message types"
status: "planned"
depends_on: ["T05", "T08"]
implements: ["FR#10", "FR#11", "AC#2"]
---

## Summary
Create the unified REST execution endpoints and the unified WebSocket message type. Replace dual response models with discriminated union types.

## Prompt
**Step 1: Unified REST endpoints** — in `web/routes/telemetry.py`:
- Combined list: `GET /telemetry/executions?kind=handler|job` — returns discriminated union response.
- Detail: `GET /telemetry/listener/{id}/executions` — returns executions for one listener.
- Detail: `GET /telemetry/job/{id}/executions` — returns executions for one job.
- All three share the same query function from T08 with different FK filter params.
- Use the `DB_ERRORS` catch pattern for graceful degradation.

**Step 2: Unified WS message** — in `web/models.py`:
- Delete `InvocationCompletedWsMessage` and `ExecutionCompletedWsMessage`.
- Create unified `ExecutionCompletedData(BaseModel)` with fields: `kind: Literal["handler", "job"]`, `owner_key: str`, `instance_index: int`, `status: str`, `duration_ms: float`, `error_type: str | None`, `listener_id: int | None`, `job_id: int | None`.
- Create `ExecutionCompletedWsMessage(BaseModel)` with `type: Literal["execution_completed"]`, `data: list[ExecutionCompletedData]`, `timestamp: float`.
- Update `WsServerMessage` discriminated union to include the new message type.

**Step 3: Update `runtime_query_service.py`** WS broadcast — merge the two handler methods (`_on_invocation_completed`, `_on_execution_completed`) into a single `_on_execution_completed` that reads `owner_key`/`instance_index` from the event payload. Merge `_pending_invocations`/`_pending_executions` into `_pending_completions`. Update `_flush_completions()` to emit a single `execution_completed` message type.

**Step 4: Update `web/mappers.py`** and `web/telemetry_helpers.py`** — field name updates.

**Step 5: Regenerate schemas** — run `uv run python scripts/export_schemas.py --types`.

**Step 6: Write integration tests:**
- Test: unified execution endpoint returns responses with `kind` indicator
- Test: detail endpoints return filtered results
- Test: WS `execution_completed` message has correct discriminated union structure

## Focus
- The `get_drop_counters()` return in `web/routes/telemetry.py` changed from 4-tuple to 3-tuple in T04 — verify the unpacking is correct.
- `test_ws_models.py` has model validation tests for the old WS types — update.
- `test_schema_freshness.py` checks model export lists — update.
- `tests/integration/web_api/test_telemetry.py` tests endpoint responses — update URLs and response shapes.

## Verify
- [ ] FR#10: `/telemetry/executions` returns execution records with `kind` indicator
- [ ] FR#11: WS `execution_completed` message includes `kind` field in payload
- [ ] AC#2: Integration tests pass for unified execution interface and real-time notifications
