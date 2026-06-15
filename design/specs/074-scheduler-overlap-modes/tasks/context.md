# Context: Execution Overlap Modes for the Scheduler

## Problem & Motivation

A recurring scheduled job that overruns its interval has no way to control what happens to the
next occurrence. The event bus solved this in #543 with four overlap modes (`single`/`restart`/
`queued`/`parallel`) backed by a shared `ExecutionModeGuard`. The scheduler never got the same
control — and deeper, it *cannot* overlap a job with itself today: `dispatch_and_log` runs a job
to completion and only then reschedules, and `Every.advance_past` skips ticks that elapsed during
the run. So the de-facto behavior today is already "no overlap, missed ticks silently skipped." A
`mode` parameter is therefore inert until rescheduling moves to dispatch time. This feature makes
that move (for recurring triggers only) and routes invocations through the reused guard.

## Visual Artifacts

None.

## Key Decisions

1. **Dispatch-time reschedule, Option B ordering.** The current due fire ALWAYS runs once popped
   as due. Only the enqueue of the *next* occurrence moves to dispatch time (before the run, for
   recurring triggers). A trigger that raises or returns `None` enqueues nothing and the job is
   removed *after* the current fire — it never skips the current fire. (Rejected: strict
   reschedule-before-run that removes on error and skips the current fire.)
2. **`single` is the behavior-preserving app default.** Because `Every.advance_past` already skips
   missed ticks during an overrun, today's effective behavior for an overrunning recurring job is
   `single` (no overlap, missed ticks skipped). App tier defaults to `single`; framework tier
   defaults to `parallel` — mirroring the bus's tier rule exactly.
3. **One guard per `ScheduledJob`.** The same job object cycles through the heap (pop → reschedule
   → push one copy), so one `ExecutionModeGuard` on the object spans all re-fires — the structural
   analogue of one guard per `HandlerInvoker`. The guard is reused UNMODIFIED from `execution_mode.py`.
4. **`parallel` awaits inline; non-parallel uses the guard + a completion bridge.** Mirror
   `HandlerInvoker.run_with_mode`: `parallel` awaits `run_job` inline (concurrency comes from
   `serve()` spawning a dispatch task per due-pop); `single`/`restart`/`queued` route through
   `guard.run(run_and_track)` and bridge completion so the dispatch task stays pending until the
   invocation finishes.
5. **In-lock `_dequeued` re-check (FR#17).** `dequeue_job` is lockless and can set `_dequeued` at
   any await point. The dispatch-time re-enqueue must re-check `_dequeued` *inside* the queue lock,
   atomic with the heap push, or a cancelled job gets re-pushed (spurious dispatch, violates the
   single heap-copy invariant).
6. **Mode accepted uniformly, no-op on one-shots.** `mode=` is accepted on all 8 methods including
   `run_in`/`run_once`; it has no overlap effect for one-shots (they fire once). Matches the bus's
   uniform acceptance.
7. **State-proxy poll pinned to `single`.** The one framework-tier scheduled job (`load_cache`
   poll) is scheduled with `mode="single"` so the framework `parallel` default does not allow
   concurrent polls within a scheduler lifecycle.
8. **Stall watch mirrors the bus.** Non-parallel guarded invocations get a 60s
   `STALL_THRESHOLD_SECONDS` watchdog WARNING (reuse the constant), so a stuck/`timeout_disabled`
   job is observable before the 600s job timeout.
9. **Mode persistence is display/telemetry only.** App code is authoritative — on restart the job
   re-registers from `on_initialize` and the upsert overwrites `scheduled_jobs.mode`. The column is
   NOT read back to reconstruct the guard. The job-side persistence chain is entirely net-new
   (unlike `listeners`, which already has it).

## Constraints & Anti-Patterns

- **Do NOT modify `ExecutionModeGuard` or the `ExecutionMode` enum** — shared with the bus, reused
  unchanged. Supply a scheduler-specific run-and-track callable through the guard's existing API.
- **Preserve the single heap-copy invariant** — exactly one heap entry per job object at any time;
  reschedule pops-then-pushes one copy, never duplicates.
- **`parallel` must NOT route through `guard.run`'s tracked path** — await inline (mirror the bus).
- **The reschedule-timing change applies to recurring triggers only** — one-shot dispatch/removal
  unchanged.
- **Do NOT persist suppressed/dropped counts** — live-only on the guard, reset on restart.
- **Do NOT rely on the dataclass default for `mode` persistence** — `add_job` must explicitly pass
  `mode=job.mode.value` at the `ScheduledJobRegistration(...)` construction site, or every job
  silently persists as `single`.
- **No `from __future__ import annotations`; `X | None` not `Optional`; no lazy imports.** (Repo rules.)
- **`trigger_due_jobs` (test harness) must not block on the completion bridge for `QUEUED_ACCEPTED`
  outcomes** — that deadlocks under a frozen clock. Queued multi-tick tests advance the loop
  (`await asyncio.sleep(0)`) and assert via a drain helper.

## Design Doc References

- `## Architecture` — the 7-part implementation breakdown (dispatch-time reschedule, guard on
  ScheduledJob, guard routing, mode resolution, persistence, web/UI, state-proxy pin).
- `## Functional Requirements` (FR#1–FR#18) and `## Acceptance Criteria` (AC#1–AC#16) — the
  traceability targets.
- `## Edge Cases` — dequeued race, trigger-error ordering, queued cap, restart cancel,
  frozen-clock test path, stuck guard-holding job, single heap-copy invariant.
- `## Convention Examples` — verbatim code patterns to follow (copied below).
- `## Test Strategy` — existing tests to adapt, new coverage mapped to FR#N.
- `## Impact` — Changed Files, Behavioral Invariants, Blast Radius.

## Convention Examples

### Tier-aware mode resolution

**Source:** `src/hassette/bus/bus.py:567`

```python
if mode is None:
    resolved_mode = ExecutionMode.PARALLEL if source_tier == "framework" else ExecutionMode.SINGLE
elif isinstance(mode, ExecutionMode):
    resolved_mode = mode
else:
    try:
        resolved_mode = ExecutionMode(mode)
    except ValueError as exc:
        valid = ", ".join(repr(m.value) for m in ExecutionMode)
        raise ValueError(f"Invalid execution mode {mode!r}; must be one of {valid}") from exc
```

### Guard wiring with a completion bridge

**Source:** `src/hassette/bus/listeners.py:272` (`HandlerInvoker.run_with_mode`)

```python
if self.mode is ExecutionMode.PARALLEL:
    await invoke_fn()
    return

loop = asyncio.get_running_loop()
done: asyncio.Future[None] = loop.create_future()
self.pending_done.add(done)

def resolve_done() -> None:
    self.pending_done.discard(done)
    if not done.done():
        done.set_result(None)

def run_and_track() -> asyncio.Task[None]:
    task = self.task_bucket.spawn(self.invocation_with_stall_watch(invoke_fn), name="bus:mode_invocation")
    task.add_done_callback(lambda _t: resolve_done())
    return task

outcome = await self.guard.run(run_and_track)
if outcome in (Outcome.SUPPRESSED, Outcome.DROPPED):
    resolve_done()
    return
await done
```

### Stall watchdog

**Source:** `src/hassette/bus/listeners.py:314` (`invocation_with_stall_watch` / `warn_stalled`), constant at line 27 (`STALL_THRESHOLD_SECONDS = 60.0`)

```python
async def invocation_with_stall_watch(self, invoke_fn):
    watchdog = asyncio.get_running_loop().call_later(STALL_THRESHOLD_SECONDS, self.warn_stalled)
    try:
        await invoke_fn()
    finally:
        watchdog.cancel()
```

### Migration ALTER for a mode column

**Source:** `src/hassette/migrations_sql/003.sql`

```sql
ALTER TABLE listeners ADD COLUMN mode TEXT NOT NULL DEFAULT 'single'
    CHECK (mode IN ('single', 'restart', 'queued', 'parallel'));
```

### Live (suppressed, dropped) surfacing — never persisted

**Source:** `src/hassette/core/bus_service.py:194` (`live_execution_counts`)

```python
counts: dict[int, tuple[int, int]] = {}
for listeners in self.router.owners.values():
    for listener in listeners:
        if listener.db_id is None:
            continue
        guard = listener.invoker.guard
        counts[listener.db_id] = (guard.suppressed, guard.dropped)
return counts
```

For jobs, equivalent counts are read from `job.guard.suppressed`/`job.guard.dropped` by adding new
logic to `enrich_jobs_with_heap` (`web/utils.py`), which already iterates the live-heap snapshot
keyed by `db_id`.
