# Design: Execution Overlap Modes for the Scheduler

**Date:** 2026-06-15
**Status:** approved
**Scope-mode:** hold
**Research:** design/specs/073-execution-overlap-modes/design.md (the bus half — archived; defines the shared enum/guard this design reuses)

## Problem

A recurring scheduled job that overruns its interval has no way to say what should
happen to the next occurrence. The event bus solved this in #543 with four execution
overlap modes — `single`, `restart`, `queued`, `parallel` — backed by a shared
`ExecutionModeGuard`. The scheduler never got the same control.

The deeper problem is that the scheduler *cannot* overlap a job with itself today, so a
`mode` parameter would be inert. `SchedulerService.dispatch_and_log`
(`src/hassette/core/scheduler_service.py:278`) runs a job to completion and only then
reschedules it. For a recurring trigger, the next occurrence is not even on the heap until
the current run finishes — and `Every.advance_past`
(`src/hassette/scheduler/triggers.py:220`) then skips every interval tick that elapsed
during the run. So an overrunning `Every(seconds=10)` job that takes 25s does not run at
10s or 20s; it reschedules to the next future grid tick after it finishes. The de-facto
behavior today is already "no overlap, missed ticks silently skipped."

This matters now because the shared enum and guard already exist and are documented as
"reused by #1027 unchanged." The only thing standing between the scheduler and overlap
modes is the reschedule-timing change — a self-contained prerequisite with independent
merit (jobs fire on their grid, not interval-after-completion).

## Goals

- A recurring scheduled job can declare an overlap `mode` (`single`/`restart`/`queued`/`parallel`)
  that takes observable effect when a run is still in flight as the next occurrence comes due.
- Recurring jobs reschedule at dispatch time, so the next occurrence is queued before the
  current run completes — making overlap possible and firing jobs on their grid.
- The scheduler's overlap surface matches the bus's: same four modes, same tier-aware
  default rule, same live suppressed/dropped diagnostics, same `restart`-cancelled
  execution recording.
- A job that completes within its interval fires at exactly the same times it does today.
- The shared `ExecutionModeGuard` and `ExecutionMode` enum are reused without modification.

## Non-Goals

- **Numeric `max_instances`-style limits.** The four named modes are the whole surface, as
  on the bus. `queued` is bounded by the guard's existing `DEFAULT_QUEUE_DEPTH` cap.
- **Config-level default-mode overrides** (e.g. a `hassette.toml` global default mode).
  The tier-aware default plus per-call `mode` is the whole control surface.
- **Persisting suppressed/dropped counts.** They stay live-only, in-memory on the guard,
  reset on restart — identical to the bus (no new DB columns for counters).
- **Changing one-shot trigger behavior.** `After` and `Once` fire exactly once and keep
  their current timing and removal semantics.

## User Scenarios

### App author: writes a recurring automation that can overrun

- **Goal:** control what happens when a periodic job is still running as its next tick arrives.
- **Context:** an `App` scheduling a poll, sync, or cleanup that occasionally runs long.

#### Declaring an overlap mode

1. **Schedule a recurring job with a mode**
   - Sees: the new `mode=` parameter on `run_every`/`run_cron`/`run_daily`/`schedule`.
   - Decides: `single` (skip overruns — the default), `queued` (run every tick, in order),
     `restart` (cancel the stale run, start fresh), or `parallel` (let them overlap).
   - Then: the job registers; `mode` is persisted and visible in the jobs UI.

2. **Observe overlap behavior at runtime**
   - Sees: in the jobs UI, the job's mode plus live `suppressed`/`dropped` counts when
     overruns occur; a DEBUG log line on each suppressed/dropped re-fire.
   - Decides: whether the mode is right, or the job needs tuning.
   - Then: adjusts `mode=` and re-deploys.

### App author: writes a one-shot job

- **Goal:** schedule a single deferred action.
- **Context:** `run_in` / `run_once`.

#### Passing mode to a one-shot

1. **Schedule with (or without) a mode**
   - Sees: `mode=` is accepted on `run_in`/`run_once` for API uniformity.
   - Decides: usually omits it.
   - Then: the job fires once; the mode has no overlap effect (a one-shot never re-fires),
     and the passed value is persisted as-is.

### Framework (state proxy): periodic cache poll

- **Goal:** poll Home Assistant state on an interval without ever overlapping two polls.
- **Context:** `StateProxy.subscribe_to_events` schedules `load_cache` via `run_every`
  (`src/hassette/core/state_proxy.py:93`).

#### Preserving skip-if-running under the new default

1. **Poll job runs on its interval**
   - Sees: nothing changes — overruns are skipped, never run concurrently.
   - Decides: n/a (framework-internal).
   - Then: because the framework tier default is `parallel`, the poll job explicitly opts
     into `mode="single"` to preserve today's non-overlapping behavior.

## Functional Requirements

- **FR#1** Recurring jobs (triggers whose `next_run_time()` returns a non-`None` time)
  reschedule the next occurrence at dispatch time — before the current invocation runs —
  so the next occurrence can become due while the current run is in flight.
- **FR#2** One-shot jobs (triggers whose `next_run_time()` returns `None`, i.e. `After`,
  `Once`) fire exactly once and are removed after firing, with the same fire timing as today.
- **FR#3** A job that completes within its interval fires at the same wall-clock times it
  fires today (the reschedule-timing change is observable only when a run overruns).
- **FR#4** Each `ScheduledJob` owns one `ExecutionModeGuard`, created from its resolved
  mode, that persists across all re-fires of that job.
- **FR#5** The scheduler routes each recurring invocation through its job's guard, which
  applies the job's configured mode to decide whether the invocation runs, is suppressed, is
  queued, replaces a running one, or runs concurrently. (Per-mode outcomes are specified in
  AC#4–AC#7.)
- **FR#6** `schedule()` and all seven convenience methods (`run_in`, `run_once`, `run_every`,
  `run_minutely`, `run_hourly`, `run_daily`, `run_cron`) accept an optional
  `mode: ExecutionMode | str | None = None` parameter.
- **FR#7** An omitted mode resolves tier-aware: `parallel` for `source_tier == "framework"`,
  `single` for `source_tier == "app"`. An explicit mode always wins.
- **FR#8** An invalid mode string raises `ValueError` naming the valid values, at scheduling
  time (before the job is registered).
- **FR#9** `mode` is accepted on one-shot schedules without error and has no overlap effect.
- **FR#10** The resolved mode is persisted to a new `scheduled_jobs.mode` column for
  display/telemetry. App code is authoritative for mode: on restart, the job re-registers from
  app `on_initialize` code (which re-supplies `mode=`) and the upsert overwrites the column. The
  column is **not** read back to reconstruct the in-memory guard.
- **FR#11** The jobs API (`JobSummary`) exposes the job's persisted `mode` and its live
  `suppressed`/`dropped` counts; the counts are read from the live guard and default to
  `(0, 0)` for jobs with no guard activity.
- **FR#12** The jobs UI displays each job's mode and, when non-zero, its suppressed/dropped counts.
- **FR#13** When the execution write queue has capacity, a `restart`-cancelled invocation is
  recorded as an execution with `status='cancelled'` (reusing the existing `executions.status`
  enum). Delivery is best-effort on the same bounded write path as `success`/`error` records — not
  a durability guarantee.
- **FR#14** Cancelling or removing a job (`cancel_job`, `cancel_group`, owner removal,
  exhaustion) releases its guard: the in-flight invocation is cancelled and queued factories are
  dropped. One inherited edge from the shared guard remains: a task spawned by `drain_next`
  concurrently with `release()` may detach rather than cancel (it runs to completion, then is
  collected) — the scheduler does not work around this since the guard is reused unmodified.
- **FR#15** The state-proxy poll job is scheduled with `mode="single"` so the framework
  `parallel` default does not allow concurrent `load_cache` runs within a single scheduler
  lifecycle. A reconnect that replaces the job builds a fresh guard, so a brief overlap between an
  old in-flight run and the new job's first fire is possible; it is mitigated by `load_cache`'s
  internal `async with self.lock`.
- **FR#16** A due fire always executes once the job has been popped as due. Computing the next
  occurrence affects only whether a next occurrence is enqueued: a future time enqueues one
  (before the run, enabling overlap); a `None` return or a raising trigger enqueues nothing and
  the job is removed after the current fire completes. A trigger error never skips the current fire.
- **FR#17** The dispatch-time re-enqueue is gated by a `_dequeued` re-check performed while holding
  the queue lock, atomic with the heap push, so a job cancelled between dispatch entry and the push
  is not re-enqueued.
- **FR#18** A non-`parallel` guarded invocation still running after the shared stall threshold
  (`STALL_THRESHOLD_SECONDS`, 60s) logs a WARNING naming the job and its mode — mirroring the bus's
  stall watch. This surfaces a stuck job well before the 600s default job timeout, and is the only
  signal for a `timeout_disabled` job that holds its guard indefinitely. `parallel` holds no guard
  and gets no stall watch.

## Edge Cases

- **Job cancelled between heap-pop and dispatch.** The `job._dequeued` guard at
  `dispatch_and_log` entry skips dispatch. The single entry check is **not sufficient** under
  dispatch-time reschedule: the re-enqueue path awaits the queue lock, and `dequeue_job` can set
  `_dequeued` synchronously in that window, re-pushing a cancelled job (a spurious later dispatch
  that violates the single heap-copy invariant). A second `_dequeued` re-check must be held
  **inside the queue lock**, atomic with the heap push (FR#17).
- **Trigger raises or exhausts during dispatch-time reschedule.** The current due fire still
  runs (it was already popped as due). The trigger error/`None` only suppresses the *next*
  occurrence: nothing is enqueued, and the job is removed after the current fire completes;
  removal callbacks fire (FR#16). This differs from a naive reschedule-before-run ordering, which
  would skip the current fire — that ordering is explicitly rejected.
- **Trigger returns a non-future time (delta ≤ 0).** A WARNING is logged and the next run
  is advanced by 1 second (existing behavior, preserved).
- **`queued` cap reached.** The newest trigger is dropped (never the oldest), `dropped`
  increments, and a DEBUG line is logged — the guard's existing behavior.
- **`restart` while running.** The in-flight task is cancelled and awaited under the guard's
  lock before the replacement spawns; the cancelled run surfaces as a `cancelled` execution row.
- **Jitter with overlap.** Re-enqueue at dispatch time still applies jitter via
  `apply_jitter_to_heap`; `single`/`queued` suppression/queueing is unaffected by jitter
  because it gates the *run*, not the heap entry.
- **Frozen-clock test dispatch (`trigger_due_jobs`).** In production, `serve()` spawns each
  dispatch as its own task, so a `queued` `QUEUED_ACCEPTED` invocation awaiting the completion
  bridge resolves normally when its eventual child drains. But `trigger_due_jobs` awaits dispatch
  **inline in a sequential loop** — awaiting a `QUEUED_ACCEPTED` `done` future there deadlocks,
  because the future only resolves via the prior task's drain callback, which cannot fire while
  the loop is still on the stack. Therefore `trigger_due_jobs` must not block on the drain chain
  for deferred (`QUEUED_ACCEPTED`) outcomes; `queued` multi-tick tests advance the loop explicitly
  (`await asyncio.sleep(0)`) and assert via a guard-drain helper. The current-snapshot-only loop
  already excludes jobs re-enqueued during dispatch, so a recurring job does not infinitely
  re-trigger under a frozen clock. See Test Strategy.
- **Single heap-copy invariant.** A job object is popped before each dispatch and re-enqueued
  exactly once, so at most one heap entry exists per job object even while a prior run is in flight.
- **Stuck guard-holding job.** A non-`parallel` job whose invocation hangs holds its guard and
  silently suppresses/queues re-fires. The default 600s job timeout eventually records a
  `timed_out` execution, but a `timeout_disabled` job never times out. The stall watchdog (FR#18)
  emits a WARNING at 60s naming the job and mode, so the stall is observable regardless of timeout
  configuration.

## Acceptance Criteria

- **AC#1** A recurring job whose run overruns its interval has its next occurrence on the heap
  before the current invocation completes (FR#1).
- **AC#2** A one-shot job fires once and is removed; passing `mode=` to `run_in`/`run_once`
  does not raise and does not change its single-fire behavior (FR#2, FR#9).
- **AC#3** A recurring job that completes within its interval produces the same fire-time
  sequence with and without this change (FR#3).
- **AC#4** With `mode="single"`, an overrunning recurring job suppresses re-fires (only the
  original run executes) and the guard's `suppressed` count increases (FR#5).
- **AC#5** With `mode="queued"`, every tick during an overrun runs in arrival order, one at a
  time, until the cap; beyond the cap the newest is dropped and `dropped` increases (FR#5).
- **AC#6** With `mode="restart"`, a re-fire cancels the in-flight run (recorded as a `cancelled`
  execution when write-queue capacity allows) and starts a fresh one (FR#5, FR#13).
- **AC#7** With `mode="parallel"`, overlapping invocations run concurrently (FR#5).
- **AC#8** An omitted mode on an app-tier schedule resolves to `single`; on a framework-tier
  schedule it resolves to `parallel` (FR#7).
- **AC#9** An invalid mode string raises `ValueError` at scheduling time naming the valid
  values (FR#8).
- **AC#10** Registering with `mode="queued"` writes `'queued'` to `scheduled_jobs.mode` and that
  value appears in the jobs API response; after a restart the job re-registers from app code and
  the column reflects whatever the app code supplies — there is no DB→guard reconstruction (FR#10).
- **AC#11** `GET /api/scheduler/jobs` returns each job's `mode` and live `suppressed`/`dropped`
  counts; the jobs UI renders them (FR#11, FR#12).
- **AC#12** Cancelling a job with an in-flight invocation cancels that invocation and clears
  any queued factories (FR#14).
- **AC#13** In steady state (no reconnect), the state-proxy poll job never runs `load_cache`
  concurrently, even when a poll overruns the interval (FR#15).
- **AC#14** A recurring job whose trigger raises on a given cycle still runs the current due fire,
  then is removed with no future fires (FR#16).
- **AC#15** A job cancelled between dispatch entry and the dispatch-time re-enqueue is not pushed
  back onto the heap and produces no later spurious dispatch (FR#17).
- **AC#16** A `single`/`restart`/`queued` invocation still running after the stall threshold emits
  a WARNING identifying the job and mode; a `parallel` invocation does not (FR#18).

## Key Constraints

- **Do not modify `ExecutionModeGuard` or the `ExecutionMode` enum.** They are shared with the
  bus and documented as reused unchanged. The scheduler supplies its own run-and-track callable
  through the guard's existing interface; if the scheduler appears to need a guard change, that
  is a signal the integration is wrong, not the guard.
- **Preserve the single heap-copy invariant.** Exactly one heap entry per job object at any
  time. Reschedule-at-dispatch must pop-then-push one copy, never duplicate a job onto the heap.
- **`parallel` must not route through `guard.run`'s tracked path.** Mirror the bus: `parallel`
  awaits the invocation inline within the dispatch task (concurrency comes from multiple dispatch
  tasks), and only `single`/`restart`/`queued` use the guard's tracked/queued machinery.
- **The reschedule-timing change applies to recurring triggers only.** One-shot dispatch and
  removal semantics stay exactly as they are.
- **Do not persist suppressed/dropped counts.** Live-only on the guard, as on the bus.

## Dependencies and Assumptions

- Depends on the shared `ExecutionModeGuard` (`src/hassette/execution_mode.py`) and
  `ExecutionMode`/`Outcome` (`src/hassette/types/enums.py`) shipped by #543.
- Depends on the unified `executions` table (`status` enum already includes `cancelled`).
- `CommandExecutor.execute` already enqueues a `cancelled` execution record on `CancelledError`
  before re-raising (`command_executor.py:270-272`), so the `restart` path reuses an existing
  mechanism. That record rides the same bounded write queue as all execution records, so delivery
  is best-effort (FR#13) — not a new durability guarantee.
- Assumes the jobs API enriches `JobSummary` from a single live-heap snapshot
  (`enrich_jobs_with_heap`), so the per-job guard's live counts are available in that same snapshot.

## Architecture

### 1. Dispatch-time reschedule (the prerequisite)

Restructure `SchedulerService.dispatch_and_log` (`src/hassette/core/scheduler_service.py:278`).
The **current due fire always runs** once the job is popped as due; only the enqueue of the
*next* occurrence moves to dispatch time. The order becomes: skip-if-dequeued → compute next →
(enqueue next OR mark for removal) → run-through-guard → remove-if-marked.

- **Compute the next occurrence first** (the existing `reschedule_job` next-run computation,
  `scheduler_service.py:350`, moved earlier). If the trigger returns a future time, enqueue one
  heap copy **before** invoking the job — this is what enables overlap. If the trigger returns
  `None` or raises, enqueue nothing and mark the job for removal *after* the current fire (FR#16);
  the current fire is never skipped by a trigger error (the Option B ordering — a strict
  reschedule-before-run that removes on error and skips the current fire is explicitly rejected).
- **The re-enqueue must be atomic with a `_dequeued` re-check (FR#17).** The single entry-level
  `if job._dequeued: return` (line 284) does not cover the re-enqueue. `dequeue_job` is lockless —
  it calls `remove_item_sync` and sets `job._dequeued = True` (line 458) without acquiring the
  queue lock — so a cancel can land at any await point after the entry check, including while the
  dispatch coroutine is suspended awaiting the `FairAsyncRLock` for the re-enqueue. Add a second
  `if job._dequeued: return` inside the queue lock, immediately before the `_job_queue.add` push.
  The flag is set lock-free but read inside the lock; because both run on the single event-loop
  thread, the in-lock read sees any `_dequeued` set before the push and prevents re-adding a
  cancelled job (a spurious later dispatch that would violate the single heap-copy invariant).
  Push-then-check is not enough — the check must guard the push within one lock hold.
- **One-shots** (`After`/`Once`, `next_run_time()` → `None`): nothing is enqueued; the job runs
  once and is removed after the fire, as today.

This is the highest-risk change (it touches the heap/cancellation loop the 073 doc flagged).
The behavior-preserving property for the common case rests on `Every.advance_past` and the cron
triggers being pure functions of `(previous_run, current_time)`: a job that completes within its
interval computes the same next grid tick whether the enqueue happens before or after the run.

### 2. The guard lives on `ScheduledJob`

Add two fields to `ScheduledJob` (`src/hassette/scheduler/classes.py:135`), both
`compare=False` so they never affect heap ordering, and neither persisted on the object's
identity:

- `mode: ExecutionMode` — the resolved overlap mode.
- `guard: ExecutionModeGuard` (`init=False`) — created in `__post_init__` from `mode`. This adds a
  new import to `classes.py` (`from hassette.execution_mode import ExecutionModeGuard`); guard
  construction does no I/O and cannot fail.

Because the same `ScheduledJob` object cycles through the heap (pop → reschedule → push one
copy), one guard per object naturally spans every re-fire — the structural analogue of one
guard per `HandlerInvoker` on the bus.

### 3. Routing invocations through the guard

Mirror `HandlerInvoker.run_with_mode` (`src/hassette/bus/listeners.py:272`). In the dispatch
path, replace the direct `await self.run_job(job)` with mode-aware routing:

- `parallel`: `await self.run_job(job)` inline — byte-for-byte today's behavior; concurrency
  comes from `serve()` spawning a fresh dispatch task per due-pop.
- `single`/`restart`/`queued`: build a `run_and_track` callable that spawns the invocation via
  `task_bucket.spawn(...)` and returns the task. The spawned coroutine wraps `run_job` in a stall
  watchdog mirroring the bus's `invocation_with_stall_watch`/`warn_stalled`
  (`bus/listeners.py:314-329`): a `loop.call_later(STALL_THRESHOLD_SECONDS, …)` that logs a WARNING
  naming the job and mode if the invocation is still running at the threshold, cancelled in a
  `finally` (FR#18). The shared `STALL_THRESHOLD_SECONDS` constant is reused, not redefined.
  call `await job.guard.run(run_and_track)`; bridge completion with a per-invocation future
  (resolved when the spawned task settles, immediately for `SUPPRESSED`/`DROPPED`, or by guard
  release) so the production dispatch task stays pending until the invocation finishes. In
  production this is safe because `serve()` spawns each dispatch as its own task — a
  `QUEUED_ACCEPTED` invocation awaiting its bridge resolves when its eventual child drains
  concurrently. A `restart` cancellation surfaces as `CancelledError` inside the child only and is
  swallowed in the dispatch path so the dispatch task does not crash.
- **Test-path caveat (`trigger_due_jobs`):** because that harness awaits dispatch inline in a
  sequential loop, it must **not** block on the bridge for deferred (`QUEUED_ACCEPTED`) outcomes —
  doing so deadlocks (the drain callback can't fire while the loop holds the stack). See the
  Edge Cases entry and Test Strategy for the harness drain mechanism.

### 4. Tier-aware mode resolution in `schedule()`

Resolve the mode in `Scheduler.schedule` (`src/hassette/scheduler/scheduler.py:361`), mirroring
the bus resolution at `src/hassette/bus/bus.py:567-580`: `None` → `parallel` for framework,
`single` for app; an `ExecutionMode` passes through; a string is coerced with a `ValueError` on
invalid. Pass the resolved `ExecutionMode` to the `ScheduledJob` constructor. The seven
convenience methods each gain a `mode` parameter and forward it to `schedule()`.

### 5. Persistence

The job-side `mode` persistence chain is **entirely net-new** — unlike `listeners`, which already
has all three pieces (`ListenerRegistration.mode`, the `register_listener` upsert, and the
`listeners.mode` column). For jobs, all of the following must be added:

- New migration `src/hassette/migrations_sql/004.sql`: `ALTER TABLE scheduled_jobs ADD COLUMN
  mode TEXT NOT NULL DEFAULT 'single' CHECK (mode IN ('single','restart','queued','parallel'))`
  — the exact shape `003.sql` used for `listeners.mode`. (`004.sql` does not exist yet.)
- Add a `mode: str = "single"` field to `ScheduledJobRegistration`
  (`src/hassette/core/registration.py:69`) — it has no such field today (mirror
  `ListenerRegistration.mode` at line 63).
- `SchedulerService.add_job` must pass `mode=job.mode.value` at the `ScheduledJobRegistration(...)`
  construction site (`scheduler_service.py:259`). Relying on the dataclass default silently
  persists every job as `single` (see Changed Files note).
- Add `mode` to the `register_job` upsert (`src/hassette/core/telemetry_repository.py:327`) — it is
  absent from all three places today: add it to the INSERT column list, the `VALUES` params, and the
  `ON CONFLICT DO UPDATE SET` list (`group`/`name_auto` are the shape to follow — but note `group`
  is already wired and `mode` is not).

### 6. Web + UI surfacing

- Add `mode: str = "single"`, `suppressed_count: int = 0`, `dropped_count: int = 0` to
  `JobSummary` (`src/hassette/core/telemetry_models.py:145`), mirroring the listener fields on
  `ListenerWithSummary` (`src/hassette/web/models.py:331`).
- The job summary DB query selects the new `mode` column.
- Live counts are **new logic** in `enrich_jobs_with_heap` (`src/hassette/web/utils.py`), which
  today enriches only `next_run`/`fire_at`/`jitter`. Add reading of `job.guard.suppressed`/
  `job.guard.dropped` from the heap-snapshot `ScheduledJob` objects, keyed by `db_id`, defaulting
  to `(0, 0)`. This depends on the `guard` field being added to `ScheduledJob` first (Architecture §2).
- Frontend: surface `mode` and the suppressed/dropped counts in the jobs table, mirroring how
  the handlers view renders listener mode and counts
  (`frontend/src/components/app-detail/unified-handler-row.tsx`,
  `frontend/src/pages/handlers-rows.tsx`). Regenerate types via
  `uv run python scripts/export_schemas.py --types`.

### 7. Migrate the one framework caller

`StateProxy.subscribe_to_events` (`src/hassette/core/state_proxy.py:93`) schedules the poll job
with an explicit `mode="single"` so the framework `parallel` default cannot produce concurrent
`load_cache` runs.

## Replacement Targets

- **The after-completion reschedule ordering in `dispatch_and_log`** (`scheduler_service.py:278-305`)
  is replaced by dispatch-time rescheduling for recurring jobs. The `reschedule_job` logic itself
  is reused (moved, not rewritten). The direct inline `await self.run_job(job)` is replaced by
  mode-aware routing through the guard. This is a restructuring of one method's control flow, not
  a deletion of functionality.

No other existing code is being replaced — the rest is additive (new fields, new column, new
parameters, new web fields).

## Migration

- `004.sql` adds `scheduled_jobs.mode` with `DEFAULT 'single'`. Existing rows and any job written
  by old code receive `'single'` on upgrade. Because `single` preserves today's de-facto
  no-overlap/skip-missed behavior for app jobs, existing app jobs behave identically after upgrade.
- The one framework job (state-proxy poll) is pinned to `single` in code, so the new framework
  `parallel` default does not change its behavior.
- Forward-only, consistent with the project's append-only migration chain (`001`→`004`). No
  down-migration; the column default makes the change transparent to existing data.

## Convention Examples

### Tier-aware mode resolution

**Source:** `src/hassette/bus/bus.py:567`

```python
# Tier-aware default (FR#3): an omitted mode (None) resolves to ``parallel`` for framework
# listeners ... and ``single`` for app listeners. An explicit mode always wins. A raw string
# is coerced here so an invalid value raises a clear ValueError at registration time.
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

### Migration ALTER for a mode column

**Source:** `src/hassette/migrations_sql/003.sql`

```sql
ALTER TABLE listeners ADD COLUMN mode TEXT NOT NULL DEFAULT 'single'
    CHECK (mode IN ('single', 'restart', 'queued', 'parallel'));
```

### Persisting a registration field through the upsert

**Source:** `src/hassette/core/telemetry_repository.py:327` (`register_job`)

The mode is added to three places in the existing upsert — the INSERT column list, the
`VALUES` named params, and the `ON CONFLICT DO UPDATE SET` list — exactly as `"group"` and
`name_auto` are handled.

### Live (suppressed, dropped) surfacing — never persisted

**Source:** `src/hassette/core/bus_service.py:194` (`live_execution_counts`)

```python
# No awaits in this method — safe from asyncio mutation races. Counts are live and in-memory
# only — no DB access. Entries without a db_id are skipped; the web layer treats a missing
# entry as (0, 0).
counts: dict[int, tuple[int, int]] = {}
for listeners in self.router.owners.values():
    for listener in listeners:
        if listener.db_id is None:
            continue
        guard = listener.invoker.guard
        counts[listener.db_id] = (guard.suppressed, guard.dropped)
return counts
```

For jobs, equivalent counts are read from `job.guard.suppressed`/`job.guard.dropped` by
**adding new logic** to `enrich_jobs_with_heap` — that function already iterates the live-heap
`ScheduledJob` snapshot keyed by `db_id` (for `next_run`/`fire_at`/`jitter`), so the counts join
in the same pass, but the guard-reading itself does not exist yet and depends on the `guard` field
being added to `ScheduledJob`.

## Alternatives Considered

- **Framework default = `single` for the scheduler (diverge from the bus).** Rejected. Defaulting
  both tiers to `single` would be safer-by-default for jobs, but it splits the tier rule across two
  surfaces (bus framework→parallel, scheduler framework→single), adding a documented exception the
  reader must hold. With only one framework job today, pinning that job to `single` explicitly keeps
  one cross-surface rule and migrates the single caller visibly. (User-selected.)
- **Reject `mode` on one-shot triggers with `ValueError`.** Rejected. A one-shot can never overlap,
  so `mode` is a harmless no-op; rejecting it adds a special-case branch and diverges from the bus's
  uniform acceptance. Accepting it keeps the API additive and consistent. (User-selected.)
- **A second overlap implementation for the scheduler.** Rejected per the 073 doc: the four-mode
  state machine and its lock are identical; two copies drift. One `ExecutionModeGuard` is reused,
  with the scheduler supplying its own spawn-and-track callable.
- **Do nothing (keep after-completion reschedule, no modes).** Rejected: it leaves recurring jobs
  with no overlap control and no on-grid firing, the explicit ask of #1027.

## Test Strategy

### Existing Tests to Adapt

- `tests/integration/test_scheduler.py` — tests asserting the exact reschedule timing of recurring
  jobs may need to account for dispatch-time reschedule. Tests for jobs that complete within their
  interval must still pass unchanged (FR#3); only tests that assumed "next occurrence appears after
  completion" need updating. Audit cancellation, group-cancel, jitter, and exhaustion tests — they
  must continue to pass (Behavioral Invariants).
- Any web test asserting `JobSummary` shape (e.g. `tests/.../test_scheduler_routes` and frontend
  `*.test.tsx` for the jobs view) gains `mode`/`suppressed_count`/`dropped_count` assertions.
- Migration/schema tests that snapshot `scheduled_jobs` columns gain the `mode` column.

### New Test Coverage

- **Dispatch-time reschedule (FR#1, FR#3):** an overrunning recurring job has its next occurrence
  enqueued before the current run completes (use an `asyncio.Event` to hold the run open and assert
  the heap has the next entry); a non-overrunning job produces an identical fire sequence (unit/integration).
- **Per-mode overlap (FR#5, AC#4–AC#7):** one integration test per mode driving an overrun and
  asserting which invocations execute, plus guard `suppressed`/`dropped` counts for `single`/`queued`.
  The `queued` multi-tick test must not call `trigger_due_jobs` twice back-to-back and block on the
  bridge — advance the loop with `await asyncio.sleep(0)` and assert via a guard-drain helper
  (see the `trigger_due_jobs` Edge Case).
- **`restart`-cancelled execution (FR#13, AC#6):** happy-path assertion that a `cancelled` execution
  row is recorded when the write queue has capacity. This verifies the `CommandExecutor.execute`
  cancellation path on the scheduler surface; it does **not** assert durability under write-queue
  pressure (delivery is best-effort by design).
- **Current fire always runs on trigger error (FR#16, AC#14):** a trigger that raises (or returns
  `None`) on a cycle still executes the current due fire, then the job is removed with no future
  fires — assert one execution row and no re-enqueue.
- **Dequeued race (FR#17, AC#15):** a job cancelled between dispatch entry and the dispatch-time
  re-enqueue is not pushed back onto the heap (use a gate to hold dispatch at the re-enqueue point,
  cancel, release, assert the heap has no entry for the job).
- **Tier-aware default + validation (FR#7, FR#8):** app→single, framework→parallel, invalid string
  raises (unit).
- **One-shot no-op (FR#2, FR#9):** `run_in`/`run_once` accept `mode=` and still fire once (unit).
- **Mode persistence (FR#10, AC#10):** registering with a mode writes that value to
  `scheduled_jobs.mode` (memory→DB) and it appears in the jobs API response. Do **not** assert a
  DB→guard reconstruction — jobs re-register from app code on restart, so no such path exists (integration).
- **Guard release on cancel (FR#14, AC#12):** cancelling a job with an in-flight/queued invocation
  cancels and clears it (integration). Note the inherited `drain_next`/`release` interleave edge
  (FR#14) is out of scope to fix here — do not assert cancellation coverage for that specific race.
- **Stall watchdog (FR#18, AC#16):** a non-`parallel` invocation held past the (test-shortened)
  stall threshold logs a WARNING naming the job and mode; a `parallel` invocation does not. Assert
  the WARNING is emitted by the behavior (a stuck handler), not by capturing the log string —
  patch the threshold low and verify via the watchdog firing path (integration/unit).
- **State-proxy poll non-overlap (FR#15, AC#13):** an overrunning `load_cache` poll never runs
  concurrently (integration).
- **Web surface (FR#11, AC#11):** `GET /api/scheduler/jobs` returns mode + live counts; frontend
  renders them.

### Tests to Remove

No tests to remove — the change restructures dispatch ordering and adds surface; it does not delete
functionality.

## Documentation Updates

- **`docs/` scheduler concept page** — add an "Execution modes" section (the four modes by behavior,
  the tier-aware default, the dispatch-time-reschedule consequence for overrunning jobs, the
  `queued` cap, DEBUG suppression logging, live-only counts). System-as-subject per `voice-guide.md`;
  tested `.py` snippets under the page's `snippets/`. Run `doc-persona-review` and
  `doc-accuracy-review` on the edited page per `.claude/rules/doc-rules.md`.
- **Docstrings** — `schedule()` and the seven convenience methods document the new `mode` parameter
  (the four values, the tier-aware default, the one-shot no-op). `ScheduledJob` documents the
  `mode`/`guard` fields.
- **CHANGELOG** — not edited manually (release-please). The PR title is the changelog entry; this
  ships as a `feat` describing scheduler overlap modes and on-grid firing.

## Impact

<!-- Gap check 2026-06-15: 6 unlisted deps included in tasks — scheduler/sync.py (sync facade, 8 methods) → T01; web/routes/telemetry.py /app/{app_key}/jobs (2nd JobSummary route) → T05; cli/commands/job.py (job table mode column) → T05; tests/unit/test_telemetry_models.py + tests/unit/core/test_telemetry_models.py (JobSummary fields) → T05; migration/schema tests (test_schema_migration.py, test_migration_runner.py, conftest) → T03; test_scheduler.py + test_scheduler_service_dequeue.py + test_app_harness_simulation.py (dispatch change) → T02. web/mappers.py confirmed NOT a gap (jobs enrich directly, no mapper). -->

### Changed Files

Shared / higher-risk first:

- `src/hassette/core/scheduler_service.py` — dispatch-time reschedule restructure + guard routing
  (the core, highest-risk change). Also the `ScheduledJobRegistration(...)` construction in
  `add_job` (line ~259) **must pass `mode=job.mode.value`** — the dataclass `default="single"`
  must not be relied on to carry the resolved mode, or every job silently persists as `single`
  with no type error and no failing default-case test.
- `src/hassette/scheduler/classes.py` — `mode`/`guard` fields on `ScheduledJob`.
- `src/hassette/scheduler/scheduler.py` — `mode` param + tier-aware resolution on `schedule()` and
  seven convenience methods.
- `src/hassette/core/registration.py` — `mode` on `ScheduledJobRegistration`.
- `src/hassette/core/telemetry_repository.py` — `mode` in the `register_job` upsert + job summary query.
- `src/hassette/migrations_sql/004.sql` — new `scheduled_jobs.mode` column.
- `src/hassette/core/telemetry_models.py` — `mode`/`suppressed_count`/`dropped_count` on `JobSummary`.
- `src/hassette/web/utils.py` — live counts in `enrich_jobs_with_heap`.
- `src/hassette/core/state_proxy.py` — pin poll job to `mode="single"`.
- `frontend/src/...` (jobs view + types) — display mode + counts; regenerated types.
- `docs/pages/.../scheduler...` — execution-modes section + snippets.
- `tests/...` — adapted + new tests (see Test Strategy).

### Behavioral Invariants

- One-shot jobs fire exactly once with unchanged timing.
- Recurring jobs that complete within their interval fire at identical times.
- The state-proxy poll never overlaps.
- Cancellation, group-cancel, jitter, and exhaustion behavior is unchanged.
- Exactly one heap entry per job object at any time.
- `ExecutionModeGuard` / `ExecutionMode` are unmodified.

### Blast Radius

- App authors gain a new optional `mode` parameter — purely additive; existing code that omits it
  keeps current behavior (`single`).
- The scheduler dispatch loop changes for all recurring jobs (timing of the *next-occurrence enqueue*,
  not of completed-within-interval fires). Any app relying on overrunning recurring jobs implicitly
  skipping ticks keeps that behavior under the `single` default.
- The jobs API response gains three fields; the OpenAPI spec and frontend types regenerate.

## Open Questions

None.
