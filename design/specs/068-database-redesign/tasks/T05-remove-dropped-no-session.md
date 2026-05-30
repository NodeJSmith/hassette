---
task_id: "T05"
title: "Remove dropped_no_session counter from all layers"
status: "done"
depends_on: ["T04"]
implements: ["FR#15", "FR#16", "AC#10"]
---

## Summary
Remove the `dropped_no_session` counter from the execution pipeline, API, and backend models. This counter is dead code after synchronous registration — the startup ordering guarantees `session_id` is always available before any listener is routable.

## Prompt
**Step 1: Remove from command_executor.py:**
- Delete `_dropped_no_session` field.
- Update `get_drop_counters()` return from 4-tuple to 3-tuple (remove the third element).

**Step 2: Remove from session_manager.py:**
- Delete the `dropped_no_session` UPDATE statement that increments the counter on the sessions table.

**Step 3: Remove from web layer:**
- `web/models.py` — remove `dropped_no_session` from `TelemetryStatusResponse`.
- `web/routes/telemetry.py` — update `get_drop_counters()` unpacking (4 → 3 values).

**Step 4: Remove from models:**
- `core/telemetry_models.py` — remove `dropped_no_session` from `SessionRecord`.

**Step 5: Update test infrastructure:**
- `test_utils/web_mocks.py` — update `get_drop_counters()` mock return value (4-tuple → 3-tuple).
- `tests/integration/web_api/test_validation.py` — update assertions on `dropped_no_session`.

## Focus
- The `dropped_no_session` column is already absent from the 001.sql schema (T02 dropped it). This task removes the Python-side references.
- Other drop counters (`dropped_overflow`, `dropped_exhausted`, `dropped_shutdown`) are unaffected — they guard against write queue congestion, not session ordering.
- `get_drop_counters()` callers use positional unpacking — the tuple position shift must be correct.

## Verify
- [ ] FR#15: `dropped_no_session` counter does not exist in `command_executor.py`
- [ ] FR#16: No references to `dropped_no_session` remain in backend production code
- [ ] AC#10: `grep -r "dropped_no_session" src/hassette/ --include="*.py"` returns zero hits
