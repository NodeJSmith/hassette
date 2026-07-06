# Context: Run Now Button for Scheduled Jobs

## Problem & Motivation
The web UI displays scheduled jobs with full execution history, stats, and next-run times, but provides no way to manually trigger a job. Every peer scheduler framework (Airflow, n8n, Prefect, Temporal) offers "run now" from the UI. Without it, developers debugging automations must wait for the next scheduled fire time, and home users cannot manually trigger an automation outside its schedule. This is Layer 1 — a zero-param "Run Now" button that triggers immediate execution and records it with `trigger_mode="manual"`.

## Visual Artifacts
None.

## Key Decisions
1. **Fire-and-forget with WebSocket feedback** — the POST endpoint returns 202 immediately and execution feedback arrives via the existing `execution_completed` WebSocket message. This follows the established app-action pattern (start/stop/reload) and avoids blocking HTTP connections.
2. **Guard pre-check for SINGLE-mode only** — before dispatching, the endpoint checks `guard.is_running()` for single-mode jobs and returns 409 if held. Restart/queued/parallel modes skip the pre-check because their guards handle overlap correctly.
3. **One-shot dequeue before dispatch** — when manually triggering a still-pending one-shot job (`After`/`Once` trigger), the route handler dequeues it from the heap *before* spawning the dispatch. This prevents double-execution. The order is critical: `dequeue_job()` calls `guard.release()` which cancels `current_task` — dequeuing first means the guard has no task to cancel.
4. **One-shot detection predicate** — a job is one-shot when `job.trigger is None` or `job.trigger.next_run_time(job.next_run, now) is None`. Checking `job.trigger is None` alone would miss `run_in()`/`run_once()` jobs, which create `After`/`Once` trigger objects.
5. **409 for "not found on heap"** — the endpoint returns 409 (not 404) because the job exists as a DB resource; it's the job's state (not currently triggerable) that prevents the action.
6. **`trigger_mode` stays as `str | None`** — not converted to an enum. The column predates this work; enum conversion belongs in #648 when all four values are populated.
7. **Separate `JobTriggerResponse` model** — not reusing `ActionResponse` (which has `app_key`/`action` but no `job_id`).
8. **`trigger_mode` rendered independently of context block** — in `detail-panel.tsx`, the existing context block (`trigger_context_id`/`trigger_origin`) is gated on `trigger_context_id` being truthy, which is always `None` for job executions. `trigger_mode` must be its own line item, not inside that conditional.

## Constraints & Anti-Patterns
- Do NOT affect recurring job scheduled timing — the job continues on its normal schedule after a manual fire.
- Do NOT bypass `run_job_with_guard()` — overlap semantics must be respected.
- Do NOT populate `trigger_mode` for non-manual execution types — only `"manual"` is populated; scheduled/event executions continue with `trigger_mode=None`.
- Do NOT add parameter override UI — that's Layer 2 (future).
- Do NOT add "Run Now" to the global `/handlers` page — only the app detail job panel.
- Do NOT place `trigger_mode` inside the `trigger_context_id`-gated context block in `detail-panel.tsx`.
- The POST endpoint request body must be optional/absent from the start so Layer 2 can add parameter overrides additively.

## Design Doc References
- `## Functional Requirements` — FR#1-FR#11, the full requirement set
- `## Edge Cases` — one-shot lifecycle, guard interactions, race conditions
- `## Acceptance Criteria` — AC#1-AC#10, verifiable done conditions
- `## Architecture` — backend method design, route handler steps, frontend component placement
- `## Convention Examples` — app action pattern, loading pattern, API post pattern, job lookup pattern, execution record building
- `## Test Strategy` — unit/integration/frontend test coverage requirements

## Convention Examples
### App action endpoint pattern

**Source:** `src/hassette/web/routes/apps.py`

```python
@router.post("/apps/{app_key}/start", status_code=202, response_model=ActionResponse)
async def start_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette)
    try:
        await hassette.app_handler.start_app(app_key)
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to start app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="start")
```

### Action button loading pattern

**Source:** `frontend/src/components/shared/action-buttons.tsx`

```tsx
const loading = useSignal(false);
const error = useSignal<string | null>(null);

const exec = async (action: (key: string) => Promise<unknown>) => {
  if (loading.value) return;
  error.value = null;
  loading.value = true;
  try {
    await action(appKey);
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
};
```

### API POST endpoint function

**Source:** `frontend/src/api/endpoints.ts`

```typescript
export const startApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${encodeURIComponent(appKey)}/start`);
```

### Job lookup by db_id from live heap

**Source:** `src/hassette/web/utils.py`

```python
live_by_db_id = {job.db_id: job for job in live_jobs if job.db_id is not None}
```

### Execution record building for jobs

**Source:** `src/hassette/core/command_executor.py`

```python
case ExecuteJob():
    return ExecutionRecord(
        kind="job",
        listener_id=None,
        job_id=cmd.job_db_id,
        session_id=session_id,
        execution_start_ts=execution_start_ts,
        duration_ms=result.duration_ms,
        status=result.status,
        app_key=cmd.job.app_key,
        instance_index=cmd.job.instance_index,
        source_tier=cmd.source_tier,
        # ... error fields ...
        execution_id=execution_id,
    )
```
