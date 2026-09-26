---
task_id: "T01"
title: "Replace LogWsMessage with LogHintWsMessage and update WS filter"
status: "done"
depends_on: []
implements: ["FR#1", "FR#9", "AC#1", "AC#7"]
---

## Summary
Replace `LogWsMessage` with a minimal `LogHintWsMessage` (type + timestamp only), add `id: int` to `LogEntryResponse` so the frontend can track its cursor, update the `WsServerMessage` discriminated union, and extend `ws.py`'s per-client `_send_from_queue` filter to gate `log_hint` on `subscribe_logs` (no `min_log_level` sub-filter). This is the foundational model change that all other tasks build on.

## Target Files
- modify: `src/hassette/web/models.py`
- modify: `src/hassette/web/routes/ws.py`
- modify: `tests/unit/test_ws_models.py`
- modify: `tests/unit/test_model_types.py`
- modify: `tests/support/web_telemetry_helpers.py`
- read: `design/specs/114-ws-log-notify-fetch/design.md`

## Prompt
In `src/hassette/web/models.py`:

1. Add `id: int` as the first field on `LogEntryResponse` (line 183). The SQL query already selects `lr.*` which includes `id`, but the Pydantic model currently drops it. This is required for the frontend cursor. Adding it as a required field will break test factories — update them in this task (see Focus).

2. Replace the `LogWsMessage` class (line 266-269) with:
```python
class LogHintWsMessage(BaseModel):
    type: Literal["log_hint"]
    timestamp: float
```
Follow the `*WsMessage` naming convention. Use bare `Literal["log_hint"]` with no default (matching the existing pattern — `AppStatusChangedWsMessage` etc. have no default on `type`).

3. Update the `WsServerMessage` union (line 321-330): replace `LogWsMessage` with `LogHintWsMessage`.

In `src/hassette/web/routes/ws.py`:

4. Extend `_send_from_queue`'s filter (lines 70-77) to also match `log_hint`. Gate on `subscribe_logs` only — no `min_log_level` sub-filter (hints carry no level). The current code checks `if message.get("type") == "log":` — extend to also match `"log_hint"`, but only apply the `subscribe_logs` gate (not the `min_log_level` sub-filter) for the hint type.

5. Update `tests/unit/test_ws_models.py`: change imports from `LogWsMessage` to `LogHintWsMessage`, update isinstance assertions. The hint has no `data` field — adjust tests accordingly.

6. Update `tests/unit/test_model_types.py`: add `id` to `minimal_log_entry_response()` factory (line 157-160).

7. Update `tests/support/web_telemetry_helpers.py`: add `id` parameter (with a default like `id=1`) to `make_log_entry_response()` (line 193-195).

After all code changes, regenerate schemas: `uv run python scripts/export_schemas.py --types`

## Focus
- The `WsServerMessage` union uses `Field(discriminator="type")` — Pydantic discriminated unions require each member to have a unique `type` literal. `LogHintWsMessage` uses `"log_hint"` which doesn't collide with anything.
- `LogEntryResponse` is used in `src/hassette/cli/commands/log.py:51` and `src/hassette/web/routes/executions.py` — adding `id` is additive and won't break those (they read from `lr.*` which includes `id`). But test factories that build `LogEntryResponse` manually (`tests/support/web_telemetry_helpers.py:make_log_entry_response`, `tests/unit/test_model_types.py:minimal_log_entry_response`) will need the new required `id` field.
- Frontend test factories (`frontend/src/test/factories.ts`, `frontend/src/test/handlers.ts`) also build `LogEntryResponse` fixtures — these need `id` too, but they're addressed in T06 after schema regeneration.
- `ws.py`'s filter at line 70-77: the `subscribe_logs` check applies to both `"log"` and `"log_hint"`, but the `min_log_level` sub-check at lines 73-77 only applies to `"log"` (which is being removed in T02, but until then the check still needs to work for any residual `"log"` messages during the transition).
- `tests/integration/test_schema_freshness.py` hardcodes `LogWsMessage` in a parametrize list — addressed in T06.

## Verify
- [ ] FR#1: `LogHintWsMessage` has only `type: Literal["log_hint"]` and `timestamp: float` — no `data`, no cursor field
- [ ] FR#9: `LogEntryResponse` has `id: int` as its first field
- [ ] AC#1: WS schema includes `log_hint` message type, not `log`; `LogWsMessage` class no longer exists
- [ ] AC#7: `uv run python scripts/export_schemas.py --types` produces updated `ws-schema.json` and `openapi.json` reflecting the new models
