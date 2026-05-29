---
task_id: "T06"
title: "Enrich completion event payloads and remove meta dicts"
status: "planned"
depends_on: ["T04"]
implements: ["FR#5", "AC#7"]
---

## Summary
Add `owner_key` and `instance_index` directly to the completion event payloads, then remove the `_listener_meta`/`_job_meta` in-memory cache and its registration side-effects. Under synchronous registration, the Listener/ScheduledJob object is guaranteed alive and in-memory when its handler fires — the decoupling cache is no longer needed.

## Prompt
**Step 1: Enrich event payloads** — in `events/hassette.py`:
- Add `owner_key: str` and `instance_index: int` fields to `InvocationCompletedPayload` and `ExecutionCompletedPayload`.
- Update `events/__init__.py` if it re-exports these types.

**Step 2: Populate enriched fields** — in `command_executor.py`:
- In `_emit_completion_events()`, populate `owner_key` and `instance_index` from the Listener/ScheduledJob object when building the event payload.

**Step 3: Remove meta dicts from RuntimeQueryService** — in `runtime_query_service.py`:
- Delete `_listener_meta` and `_job_meta` dict fields.
- Delete `register_listener_meta()` and `register_job_meta()` methods.
- Delete `prune_meta()` method.
- Update `_on_invocation_completed()` and `_on_execution_completed()` to read `owner_key`/`instance_index` from the event payload instead of the meta dict.

**Step 4: Remove registration side-effects** — in `command_executor.py`:
- Remove `rqs.register_listener_meta()` and `rqs.register_job_meta()` calls from `register_listener()` and `register_job()`.
- Remove `rqs.prune_meta()` call from `reconcile_registrations()`.

**Step 5: Update tests:**
- Update any tests that verify meta dict population or pruning behavior.
- Update any tests that assert on completion event payload shape.

## Focus
- The two RQS handler methods (`_on_invocation_completed`, `_on_execution_completed`) still exist as two separate methods after this task — the merge into a single handler happens in T11. This task only changes the data source (payload instead of dict).
- The event topics (`HASSETTE_EVENT_INVOCATION_COMPLETED`, `HASSETTE_EVENT_EXECUTION_COMPLETED`) remain as two separate topics after this task — T09 collapses them.

## Verify
- [ ] FR#5: Completion event payloads include `owner_key` and `instance_index` (populated from the in-memory object, not a DB read)
- [ ] AC#7: No `_listener_meta` or `_job_meta` dicts exist in `runtime_query_service.py`
