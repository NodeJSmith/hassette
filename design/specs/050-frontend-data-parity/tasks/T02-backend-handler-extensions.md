---
task_id: "T02"
title: "Populate handler min/max duration and add traceback to summary"
status: "done"
depends_on: []
implements: ["FR#4", "FR#17", "AC#3", "AC#13"]
---

## Summary
Fix the handler summary query to actually populate `min_duration_ms` and `max_duration_ms` (fields exist on the model but default to 0.0 because the query uses COALESCE). Change to NULL sentinel. Also add `last_error_traceback` to `ListenerWithSummary` so the frontend can show expandable tracebacks without drilling into invocation history.

## Prompt
In `src/hassette/core/telemetry_query_service.py`, update `get_listener_summary()` (line 255):
1. Find the `COALESCE(MIN(hi.duration_ms), 0.0)` and `COALESCE(MAX(hi.duration_ms), 0.0)` expressions (around line 309-310) and remove the COALESCE — let MIN/MAX return NULL naturally
2. Ensure the `last_err` LEFT JOIN subquery (lines 303-307) also selects `last_err.error_traceback`

In `src/hassette/core/telemetry_models.py`, update `ListenerSummary` (line 59):
- Change `min_duration_ms: float` to `min_duration_ms: float | None = None`
- Change `max_duration_ms: float` to `max_duration_ms: float | None = None`
- Add `last_error_traceback: str | None = None`

In `src/hassette/web/models.py`, update `ListenerWithSummary` (line 277):
- Change `min_duration_ms: float = 0.0` to `min_duration_ms: float | None = None`
- Change `max_duration_ms: float = 0.0` to `max_duration_ms: float | None = None`
- Add `last_error_traceback: str | None = None`

In `src/hassette/web/mappers.py`, update `to_listener_with_summary()` (line 146):
- Pass through `last_error_traceback` from `ListenerSummary` to `ListenerWithSummary`
- Verify that `min_duration_ms` and `max_duration_ms` are already passed through (they should be, but confirm)

Write tests verifying:
- Handler with no invocations returns `None` for min/max
- Handler with invocations returns correct min/max
- Handler with errors includes `last_error_traceback`
- Handler with no errors has `None` traceback

Regenerate schemas after changes. If T01 has already regenerated schemas, this regeneration will overwrite with the combined state — that's fine. If running in parallel with T01, defer schema regeneration to whichever task completes second.

## Focus
- The mapper at `src/hassette/web/mappers.py:146` explicitly maps each field from `ListenerSummary` to `ListenerWithSummary` — the new `last_error_traceback` must be added to this mapping or it will silently drop
- The existing `last_error_message` and `last_error_type` are already mapped — follow the same pattern
- The `ListenerSummary` model has `min_duration_ms: float` and `max_duration_ms: float` (non-optional) — these need to become `float | None` simultaneously with the web model change
- Existing frontend code checks `listener.avg_duration_ms > 0` for "no data" display — the frontend task (T04) will update this to `!= null` for min/max

## Verify
- [ ] FR#4: `get_listener_summary()` returns `min_duration_ms` and `max_duration_ms` as `float | None` (NULL when no invocations, numeric when present)
- [ ] FR#17: `ListenerWithSummary` includes `last_error_traceback` populated from the most recent errored invocation
- [ ] AC#3: Handler summary data includes min, avg, and max duration fields with correct types
- [ ] AC#13: `ListenerWithSummary` carries `last_error_traceback` through the mapper to the API response
