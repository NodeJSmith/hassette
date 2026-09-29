---
task_id: "T04"
title: "Validate served models at construction time"
status: "planned"
depends_on: ["T03"]
implements: ["FR#11", "FR#12", "AC#7", "AC#8"]
---

## Summary
Three places build served data without validation today. `to_listener_with_summary` and `enrich_jobs_with_live` overlay computed or live values with `model_copy(update=...)`, which pydantic doesn't validate. `flush_completions` broadcasts raw dicts. This task routes all three through the wire models' constructors, so a wrongly typed value can't reach a response unvalidated.
- **Listeners:** a bad computed value raises.
- **Jobs:** a bad live value falls back to that job's DB row, using the existing per-job warning path.
- **Completions:** each is built as an `ExecutionCompletedData` when its event arrives, so one malformed completion is rejected on its own and doesn't drop the rest of its batch from the WS feed.

## Target Files
- modify: `src/hassette/web/mappers.py`
- modify: `src/hassette/web/utils.py`
- modify: `src/hassette/core/runtime_query_service.py`
- modify: `tests/unit/web/test_mappers.py`
- modify: `tests/unit/test_web_utils.py`
- modify: `tests/unit/core/test_runtime_query_service.py`
- read: `src/hassette/schemas/listener_models.py`
- read: `src/hassette/schemas/live_counts.py`
- read: `src/hassette/events/hassette.py`
- read: `src/hassette/task_bucket/task_bucket.py`
- read: `src/hassette/core/command_executor.py`
- read: `tests/unit/test_ws_models.py`
- read: `design/specs/116-wire-models-to-hassette-wire/design.md`

## Prompt
Read `tasks/context.md` and these design sections: `### Validated construction (FR#11)`, `### Completion broadcast (FR#12)`, and `## Edge Cases` ("`model_copy(update=...)` skips validation", "Coercion from validated construction").

1. **`to_listener_with_summary`** (`src/hassette/web/mappers.py`, defined at line 183). Today it is `ListenerWithSummary.model_validate(listener, from_attributes=True).model_copy(update={...})`. Change it to `ListenerWithSummary(**listener.model_dump(), listener_kind=…, handler_summary=…, target=…, suppressed_count=…, dropped_count=…, backpressure_dropped_count=…)`, with the computed fields as explicit keyword arguments so pyright checks their types. Don't wrap it in try/except; a bad value raises. `test_listener_summary_fields_are_subset_of_response` keeps guarding that `model_dump()` supplies a field set the response accepts, so keep it passing.
2. **`enrich_jobs_with_live`** (`src/hassette/web/utils.py`, defined at line 15; the `model_copy` block is at ~44–65). Replace `js.model_copy(update={...})` with `JobSummary(**js.model_dump(exclude={…the updated keys…}), schedule_status=…, schedule_status_reason=…, next_run=…, fire_at=…, jitter=…, suppressed_count=…, dropped_count=…)`, keeping the exact value expressions used today. Keep the surrounding `try: … except (AttributeError, TypeError, ValueError): LOGGER.warning(...); enriched.append(js)` exactly as it is. A `ValidationError` is a `ValueError`, so a bad live value takes that fallback. Don't narrow or widen the except clause.
3. **Completions** (`src/hassette/core/runtime_query_service.py`: `on_execution_completed` ~line 212, `flush_completions` ~line 242, `_pending_completions`).
   - `on_execution_completed` builds `ExecutionCompletedData(kind=…, app_key=…, …)` from the `ExecutionCompletedPayload`, with the same fields and values as the dict it appends today, and appends the model. `_pending_completions` becomes `list[ExecutionCompletedData]`.
   - `flush_completions` keeps swapping out the pending list first and broadcasts `{"type": "execution_completed", "data": [c.model_dump() for c in batch], "timestamp": now}`.
   - Nothing in the flush can raise a `ValidationError` any more.
   - A malformed completion raises inside `on_execution_completed`. That is a bus-handler invocation, so `CommandExecutor._execute` records the failure, and the model is never appended.
4. **Tests.**
   - `tests/unit/web/test_mappers.py`: a wrong-typed computed value makes `to_listener_with_summary` raise `pydantic.ValidationError`. The computed values come from typed helpers, so inject the bad value through the input: for example, a `LiveCounts` built with a non-int count (it's a `NamedTuple`, which doesn't validate), or `monkeypatch` of the helper the function calls, if that's cleaner.
   - `tests/unit/test_web_utils.py`: call `enrich_jobs_with_live` directly, not the `enrich_jobs_with_live_data` wrapper the file tests today. Give it a live job whose overlaid value has the wrong type (e.g. `jitter` set to a non-numeric object on a stub `Job`), and assert the result for that job is the unmodified DB row (`is js`, or equal to it) while other jobs are enriched. Assert on the returned data, not on log output.
   - `tests/unit/core/test_runtime_query_service.py`:
     - (a) After some valid completions, `flush_completions` broadcasts a message whose `data` validates with `TypeAdapter(list[ExecutionCompletedData])`.
     - (b) Feed valid, malformed, valid completions to `on_execution_completed` by calling the handler directly. The malformed call raises `ValidationError`, `_pending_completions` holds exactly the two valid models, and the next `flush_completions` broadcasts both.
     - Build the malformed payload by giving the unvalidated frozen dataclass `ExecutionCompletedPayload` a wrong-typed field (e.g. a non-numeric `duration_ms`, or an invalid `status`).

## Focus
- **Bus error path:** `on_execution_completed` is registered via `bus.on(topic=Topic.HASSETTE_EVENT_EXECUTION_COMPLETED, …, name="hassette.rqs.on_execution_completed")` (`runtime_query_service.py:118-123`). When a handler raises, `CommandExecutor._execute` (`core/command_executor.py:276-336`) records it and `execute_handler` (`:495-509`) spawns any registered error handler. The listener isn't unregistered, and the service isn't crashed.
- **Coercion:** validated construction can turn `int` into `float` (`1` → `1.0`). If an existing route/WS test or the schema pin shows a JSON diff, don't hide it. Report it; the PR will explain it (Dependencies and Assumptions: "Accepted: validated construction may coerce output").
- **Behavior pin:** existing `execution_completed` WS tests (`tests/unit/test_ws_models.py`, `tests/integration/web_api/test_ws_endpoint.py`) and job/listener route tests must pass unchanged.
- **Scope:** don't change the `events/hassette.py` payload dataclasses; they're app-author API (Non-Goals).
- **Test conventions:** follow the repo's test conventions (`.claude/rules/test-conventions.md`, `tests/TESTING.md`). Mock only at boundaries, and don't assert on log capture.

## Verify
- [ ] FR#11: `grep -n "model_copy" src/hassette/web/mappers.py src/hassette/web/utils.py` returns nothing, and `enrich_jobs_with_live` still has `except (AttributeError, TypeError, ValueError)`.
- [ ] FR#12: `on_execution_completed` appends `ExecutionCompletedData` instances, `_pending_completions` is annotated `list[ExecutionCompletedData]`, and `flush_completions` contains no model construction (only `model_dump()`).
- [ ] AC#7: `uv run pytest tests/unit/web/test_mappers.py tests/unit/test_web_utils.py -n 4` passes, including the new `to_listener_with_summary`-raises test and the `enrich_jobs_with_live`-returns-DB-row test.
- [ ] AC#8: `uv run pytest tests/unit/core/test_runtime_query_service.py tests/unit/test_ws_models.py tests/integration/web_api/test_ws_endpoint.py -n 4` passes, including the batch-validates test and the malformed-between-two-valid test.
