# Design: Execution Overlap Modes for Event Handlers

**Date:** 2026-06-14
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-04-19-execution-overlap-modes/research.md
**Issue:** #543
**Follow-up:** #1027 (scheduler half — deferred)

## Problem

Event handlers fire-and-forget through `TaskBucket.spawn()` with no overlap control. When a trigger re-fires while its prior invocation is still running, both run concurrently. There is no `mode`, `concurrency`, or equivalent parameter on bus registrations.

For an app author, this means a handler that mutates shared state, calls a slow service, or holds a resource can be re-entered before it finishes — producing state corruption, duplicate side effects, and races that only appear under load. A motion handler that turns on a light, waits, then turns it off can be interrupted by a second motion event and leave the light in the wrong state. The framework gives the author no way to say "don't start a second copy while the first is running."

Rate limiters (debounce/throttle) change *when* a handler starts, not whether overlapping executions are allowed. They do not solve overlap.

One fact about the current code shapes the default (verified, and the correct precedent): **framework-internal listeners depend on concurrency.** The service-restart supervisor, the state cache, and the runtime query service all subscribe to the bus, and several must process concurrent events — the supervisor must restart service B while service A's restart sleeps in backoff (`service_watcher.py:321,372`); the state cache must not drop concurrent state updates off the firehose (`core/state_proxy.py:87`). A blanket safe-by-default that also constrained framework listeners would break supervision and stale the cache.

### Scope

This design covers **the event bus only**. The scheduler half — the same `mode` parameter on scheduler methods — is deferred to **#1027**. The reason is not symmetry-for-its-own-sake: recurring scheduled jobs cannot currently overlap themselves (the scheduler reschedules only after a run completes, so a `mode` parameter would have no observable effect without first changing reschedule timing). That prerequisite behavior change is a self-contained piece of work tracked in #1027, which reuses the `ExecutionMode` enum and `ExecutionModeGuard` this design introduces.

## Goals

- App authors declare overlap behavior per registration with one `mode=` parameter on bus handlers.
- Four modes, matching Home Assistant's model so users coming from HA YAML already know them: `single`, `restart`, `queued`, `parallel`.
- The default is **tier-aware**: app-tier registrations default to `single` (safe); framework-tier registrations default to `parallel` (preserve today's concurrent behavior). This mirrors HA, where automation modes apply to user automations, never to core internals.
- Suppressed and dropped executions log at DEBUG, never WARNING (the research's primary anti-pattern).
- Mode is persisted and visible in the monitoring UI; suppressed/dropped counts are visible as live diagnostics.
- The enum and guard are shared infrastructure the scheduler follow-up (#1027) reuses without modification.
- The mode interface accommodates a future `max` parameter for `queued`/`parallel` without breaking existing callers.

## Non-Goals

- **The scheduler `mode` parameter.** Deferred to #1027 (requires a reschedule-timing change to be meaningful).
- The `max` parameter for `queued`/`parallel`. Deferred. `queued` ships with a fixed internal cap; the guard already accepts the cap as a constructor argument so `max` adds a value source later, not a new mechanism. (Adding the public `max` kwarg later is additive — no caller breaks — but is a real new keyword argument, not a zero-API change. See Alternatives.)
- A `max_exceeded` selector (HA's `warning`/`silent`/`error`). Suppression logging is DEBUG, full stop.
- Numeric `max_instances`-style limits (APScheduler model). The four named modes are the whole surface.
- Distributed/cross-process overlap control. Overlap is enforced per in-process listener only.
- **Persisting suppressed/dropped counts.** They are live-only diagnostics held in memory and reset on restart — not written to the database. (See Architecture → Telemetry for why.)
- Reworking debounce/throttle or duration-hold semantics. The guard composes with them; it does not change them.

## User Scenarios

### App author: writes an automation that must not overlap

- **Goal:** ensure a handler never runs two copies at once.
- **Context:** registering a handler in `on_initialize`.

#### Default-safe registration

1. **Register a handler without specifying mode**
   - Sees: the same registration call they write today; no new required argument.
   - Decides: nothing — app-tier registrations default to `single`.
   - Then: if the entity changes again while the handler is still running, the re-fire is dropped and logged at DEBUG. The running handler finishes uninterrupted.

#### Choosing restart for "latest wins"

1. **Register with `mode="restart"`**
   - Sees: `await self.bus.on_state_change("sensor.x", handler=..., name="x", mode="restart")`.
   - Decides: that a new trigger should supersede an in-flight run.
   - Then: when a new event arrives mid-run, the running handler task is cancelled (raising `CancelledError` inside it) and a fresh invocation starts with the new event.

#### Choosing queued for "process every trigger in order"

1. **Register with `mode="queued"`**
   - Sees: the `mode="queued"` argument.
   - Decides: that every trigger must run, serialized.
   - Then: triggers arriving during a run are queued and executed one at a time in arrival order. If the queue is already at its cap, the newest trigger is dropped with a DEBUG log and the queue-dropped counter increments.

### App author: inspects overlap behavior in the UI

- **Goal:** confirm a handler is `single` and see how often re-fires were suppressed.
- **Context:** the app detail Handlers tab.

#### Reading mode and counters

1. **Open a listener's detail pane**
   - Sees: a mode chip (`single`/`restart`/`queued`/`parallel`) and, when non-zero, a "Suppressed" count and (for `queued`) a "Dropped" count, alongside the existing call/failed/timed-out cells.
   - Decides: whether the suppression count signals a misconfiguration (a handler dropping work as `single` that should be `queued`).
   - Then: adjusts the `mode` argument in code and redeploys. (The counts are since-process-start; a restart resets them.)

## Functional Requirements

- **FR#1** An `ExecutionMode` enum exists with exactly the values `single`, `restart`, `queued`, `parallel`.
- **FR#2** All four bus registration methods (`on_state_change`, `on_attribute_change`, `on_call_service`, `on`) accept a `mode` parameter.
- **FR#3** When `mode` is not supplied, the effective default is `single` for app-tier registrations and `parallel` for framework-tier registrations.
- **FR#4** In `single` mode, a trigger that fires while a prior invocation of the same listener is still running is dropped and not executed.
- **FR#5** A drop in `single` mode is logged at DEBUG level, not WARNING or INFO.
- **FR#6** In `restart` mode, a trigger that fires while a prior invocation is still running cancels the running invocation and starts a new one.
- **FR#7** A handler cancelled by `restart` surfaces `CancelledError` inside the running invocation and does not crash the dispatching task bucket.
- **FR#8** In `queued` mode, triggers that arrive while an invocation is running are executed in arrival order, one at a time, after the current invocation completes.
- **FR#9** In `queued` mode, when the pending queue is at its cap, the newest trigger is dropped and the existing queue is preserved.
- **FR#10** A queue drop in `queued` mode is logged at DEBUG level.
- **FR#11** In `parallel` mode, multiple invocations of the same listener run concurrently with no overlap guard (matching today's behavior).
- **FR#12** An invalid `mode` value (not one of the four) is rejected at registration time with a clear error.
- **FR#13** Exactly one invocation of a `single`/`restart`/`queued` listener runs at a time, with no race window in which two run concurrently (including a third trigger arriving during a `restart` cancel-and-replace).
- **FR#14** The chosen mode is persisted per listener and is queryable through the telemetry/web API.
- **FR#15** Each listener exposes a live (in-memory, since-process-start) count of suppressed executions (`single` drops) and dropped executions (`queued` cap drops) through the web API.
- **FR#16** A handler cancelled by `restart` is recorded as an execution with `status='cancelled'`.
- **FR#17** When a listener is cancelled or re-registered, any in-flight invocation reference and queued triggers held by its guard are released, leaking no event/listener/app references.
- **FR#18** The monitoring UI displays the mode for each listener.
- **FR#19** The monitoring UI displays the suppressed and dropped counts for each listener when non-zero.
- **FR#20** `mode` composes with `debounce`/`throttle`: rate limiting governs whether an invocation starts; the mode governs overlap of started invocations.
- **FR#21** `mode` composes with `once=True`: a `once` listener fires at most one invocation regardless of mode.
- **FR#22** `mode` composes with duration-hold: the guard applies at the point the held handler actually dispatches, not at trigger arrival.

## Edge Cases

- **Third trigger during `restart` teardown:** triggers A (running), B (cancels A, starts), C (arrives while B is awaiting A's cancellation). The guard's critical section is serialized by a per-guard `asyncio.Lock`, so C waits until B has fully replaced A; exactly one running invocation exists at every settle point (FR#13).
- **`restart` cancellation mid-side-effect:** the cancelled handler may be partway through a service call or state mutation. The framework cancels the task; making handlers cancellation-safe is the author's responsibility. Documented, not enforced.
- **`queued` cap reached repeatedly:** a high-frequency trigger feeding a slow handler hits the cap continuously. Each drop is DEBUG-logged and counted; memory is bounded by the cap.
- **`single` with a never-completing handler:** a handler that hangs blocks all future triggers in `single` mode (by design). The per-listener `timeout` releases the guard when it fires (`command_executor.py` enforces it). Because the drop log is DEBUG-only, a multi-minute stall is otherwise invisible — so a handler still holding the `single` guard past a threshold is surfaced as a WARNING and as a "currently running" indicator in the live telemetry (see Architecture → Observability).
- **Duration-hold + mode:** a duration listener fires its handler only after the hold elapses; the mode guard applies at that delayed dispatch, not at trigger arrival (FR#22).
- **`debounce`/`throttle` + `restart`:** debounce cancels a *pending* (not-yet-started) timer; `restart` cancels a *running* invocation. Both can be active and operate on different lifecycle stages without conflict.
- **App reload / listener replacement:** when a listener is re-registered (same natural key) or cancelled, the guard releases its in-flight task reference and drains its queue, so closures over the old event/listener do not leak (FR#17).
- **Mode change on re-registration:** if an existing listener is re-registered with a different `mode` (`if_exists="replace"`), the new mode takes effect; `config_matches()`/`diff_fields()` treat `mode` as a tracked config field so a mode-only change is detected. (The event-predicate `matches()` is unrelated and unchanged.)
- **Counter loss on restart:** suppressed/dropped counts are live-only and reset to zero when the process restarts. This is intentional (they are diagnostics, not durable telemetry) and documented.
- **Counters for a retired listener:** a listener that is cancelled/retired no longer has a live guard, so its counts are absent (treated as zero) in the summary. Expected.

## Acceptance Criteria

- **AC#1** Registering a handler with each of the four modes succeeds and persists the mode (FR#1, FR#2, FR#14).
- **AC#2** An app-tier handler registered without `mode` behaves as `single`; a framework-tier registration without `mode` behaves as `parallel` (FR#3).
- **AC#3** With `single`, firing a trigger twice while the first invocation blocks yields exactly one execution; the second is dropped with a DEBUG log (FR#4, FR#5).
- **AC#4** With `restart`, firing a second trigger mid-run cancels the first (observable `CancelledError`) and runs the second to completion; the dispatching bucket does not error (FR#6, FR#7).
- **AC#5** With `restart`, firing A then B then C in tight succession against a blocking handler never produces two concurrent running invocations (FR#13).
- **AC#6** With `queued`, firing N triggers during a blocking run executes all N in arrival order after the first completes (FR#8).
- **AC#7** With `queued` at cap, an additional trigger is dropped, the queued items still run, and the drop is counted and DEBUG-logged (FR#9, FR#10).
- **AC#8** With `parallel`, firing M triggers during a blocking run yields M concurrent executions (FR#11).
- **AC#9** Passing an invalid `mode` string raises at registration time (FR#12).
- **AC#10** After `single` drops and `queued` cap-drops, the listener's suppressed and dropped counts (read live via the web API) reflect the drops (FR#15).
- **AC#11** A `restart`-cancelled invocation appears in the executions table with `status='cancelled'` (FR#16).
- **AC#12** Cancelling/re-registering a `queued` listener with pending items releases those items (no reference retained); verified by a no-leak assertion on the guard's queue (FR#17).
- **AC#13** The app detail UI shows the mode chip for listeners, and shows suppressed/dropped counts when non-zero (FR#18, FR#19).
- **AC#14** A handler with both `debounce` and `mode="single"` debounces trigger starts and suppresses overlap among started invocations (FR#20).
- **AC#15** A `once=True` handler in any mode fires at most once (FR#21).
- **AC#16** A duration-hold handler with `mode="single"` applies the guard at hold-expiry dispatch, not at trigger arrival (FR#22).

## Key Constraints

- **Never log suppression/drops above DEBUG.** WARNING-level logs for expected suppressed executions is the research's headline anti-pattern (HA's `single`-mode log spam on motion sensors). The only WARNING is the distinct "handler still holding the `single` guard past a threshold" stall signal.
- **No per-event rows for no-op fires, and no per-event counter writes.** Suppressed (`single`) and dropped (`queued` cap) fires write nothing to the database — not an execution row, not a counter UPDATE. Counts live in memory only.
- **One shared guard, but its task model must fit the bus.** The bus pre-spawns a dispatch task per event. The guard owns its handler task explicitly and is serialized by an internal lock so it behaves identically regardless of how many dispatch tasks call it concurrently. (The scheduler follow-up #1027 reuses this same guard.)
- **The guard must not break the dispatch-drain contract.** The bus tracks in-flight dispatches via `_dispatch_pending` for test/quiescence draining. The guard's handler task must remain accounted for by that mechanism (do not spawn a detached task the drain can't see).
- **`queued` must be bounded.** A fixed internal cap with newest-dropped eviction; no unbounded queue.
- **Mode is config; overlap state and counts are runtime.** `mode` is immutable per registration and part of listener identity for diffing. The running-task reference, the queue, and the suppressed/dropped counts live only in the guard/in-memory registry and never touch the DB.
- **Framework-tier behavior is preserved.** No framework-internal listener changes behavior unless it explicitly opts into a non-`parallel` mode.

## Dependencies and Assumptions

- **Depends on the unified `executions` table** (PR #922, `src/hassette/migrations_sql/001.sql`). Its `status` enum already includes `cancelled`, which `restart` reuses; the table already carries a per-execution `trigger_mode` column (distinct from the new per-registration `listeners.mode`).
- **Depends on the append-only migration mechanism** (`PRAGMA user_version`, `migration_runner.py`). New schema ships as `003.sql`; `001.sql`/`002.sql` are not edited.
- **Depends on `source_tier`** already being resolved at registration (`bus.py:552-566`) so the tier-aware default needs no new plumbing.
- **Depends on the web layer running in-process with the bus**, so the listener-summary path can read live counters from the in-memory registry by listener id.
- **Assumes single event loop, single process.** Overlap is enforced in-process via asyncio primitives.
- **Assumes the OpenAPI → TypeScript pipeline** (`scripts/export_schemas.py --types`) is the source of truth for frontend types.
- **Frontend worktree dependency:** `cd frontend && npm install` before building (node_modules is not shared across worktrees).

## Architecture

### The enum and the shared guard

Add `ExecutionMode(StrEnum)` to `src/hassette/types/enums.py` (`single`/`restart`/`queued`/`parallel`), beside `RestartType`/`ResourceStatus`, so bus, telemetry, web — and later the scheduler (#1027) — import it from one place.

Add `ExecutionModeGuard` (new module, e.g. `src/hassette/execution_mode.py`) owning the four-mode state machine. One instance exists per listener. It is overlap-only and does no I/O:

- Holds the current handler `asyncio.Task | None`, a bounded `collections.deque` of pending invocation factories (for `queued`), a single `asyncio.Lock`, and two integer counters (`suppressed`, `dropped`).
- Its async entry point takes a "start this invocation" coroutine factory and applies the mode under the lock:
  - `single`: if a task is running, increment `suppressed`, return `Suppressed`; else start and track the task.
  - `restart`: if a task is running, cancel it and `await` its settling (still holding the lock so no third trigger interleaves — FR#13), then start the new one.
  - `queued`: if a task is running, append the factory (or increment `dropped` and return `Dropped` if at cap); else start, and on completion drain the next factory.
  - `parallel`: start without tracking (today's behavior); the lock path is a no-op.
- Returns `Ran` / `Suppressed` / `Dropped`. The guard performs no DB writes; its counters are read by the web layer (below).
- **Task ownership:** the guard does not spawn a *detached* task. Each chokepoint hands it a "run-and-track" callable that performs the spawn through the same `task_bucket`/`_dispatch_pending` path the chokepoint already uses (the duration-hold path dispatches via `listener.invoker.dispatch` at `duration_hold.py:144,166,224`). The guard only decides *whether* and *when* to call it, and retains the returned task for cancellation. This keeps one guard abstraction while letting each surface supply its own spawn mechanics.
- The `queued` cap is a module constant (`DEFAULT_QUEUE_DEPTH = 10`, matching HA), passed to the guard's constructor so a future `max` overrides the value with no change to the guard's shape.
- **Cleanup:** a `release()` cancels the tracked task and clears the deque, called from listener cancellation so no closures leak (FR#17).

This is the anti-duplication point and the race-safety point: the overlap logic and its lock live once.

### Tier-aware default

`source_tier` (`app`/`framework`) is resolved during registration (`bus.py:552`, asserted at `:553`). The default mode is computed there: `parallel` when `source_tier == "framework"`, else `single`. An explicit `mode=` always wins. This preserves every framework-internal listener (the supervisor at `service_watcher.py:577-600`, the state firehose at `core/state_proxy.py:87`, the query service at `runtime_query_service.py:92-119`) at today's concurrent behavior while making app handlers safe by default — exactly HA's split between core internals and user automations.

### Bus integration

`ListenerOptions` (`src/hassette/bus/listeners.py:67`) gains `mode: ExecutionMode = ExecutionMode.SINGLE`; the tier override is applied where the option is built (the registration path knows `source_tier`), not in the dataclass default. Enum membership is the validation; an invalid string fails coercion (FR#12).

`HandlerInvoker` owns the per-listener `ExecutionModeGuard` (it is already the per-listener object owning dispatch, rate limiting, and the once-guard). `HandlerInvoker.dispatch()` (`listeners.py:192`) is the chokepoint. Today:

```python
if self.once and self.fired:
    return
if self.once:
    self.mark_fired()
if self.rate_limiter:
    await self.rate_limiter.call(invoke_fn)
else:
    await invoke_fn()
```

The guard wraps the innermost run. Order is preserved: once-guard → rate limiter (whether to start) → mode guard (overlap of started invocations). The dispatch task that reaches this point is spawned by `BusService.dispatch` (`src/hassette/core/bus_service.py:325`); the guard tracks/cancels the handler work via the run-and-track callable above, so the running handler stays counted by `_dispatch_pending`. For `parallel`, the guard is a pass-through, so the default-off path is byte-for-byte today's behavior.

### Telemetry

**`mode` is persisted; the suppressed/dropped counts are not.** This split is deliberate: `mode` is config the UI must show across restarts, but the counts are diagnostic and persisting them was the entire source of the data-integrity risk surface (re-registration upsert resets, retention deletes, crash-window loss, flush coalescing). Live-only counts make that surface disappear rather than be defended.

- **`mode` column** added to `listeners` via `003.sql`:

  ```sql
  ALTER TABLE listeners ADD COLUMN mode TEXT NOT NULL DEFAULT 'single';
  ```

  Written through the existing registration upsert (`telemetry_repository.py`) — added to the insert-params dict and the `ON CONFLICT DO UPDATE SET` list, exactly like `debounce`/`once`. Because the resolved (tier-aware) mode is part of the registration, this is correct config persistence. No counter columns are added; `scheduled_jobs` is untouched (scheduler is #1027).
- **Suppressed/dropped counts** live on the per-listener guard (above). The bus exposes a snapshot of current counts keyed by listener `db_id` (the bus already holds every active listener in its router; each listener carries its `db_id` after registration). The listener-summary path merges these counts into the `ListenerWithSummary` DTOs after the DB query, matching by `db_id`; a listener with no live guard contributes zero. No flush loop, no accumulator-reset discipline, no upsert interaction — the counts never reach the database.
- **`restart` cancellations** need no new mechanism: the cancelled task flows through `CommandExecutor` and lands as a `status='cancelled'` execution row. (Trade-off noted in Alternatives: under a high-frequency `restart` trigger this is one row per cancellation — bounded by trigger rate, and acceptable because `restart` implies wanting each attempt recorded.)

### Observability

Because the `single` drop log is DEBUG-only, a stalled handler holding the guard is otherwise silent. Two signals address the 2am-debugging gap: a WARNING when an invocation holds a `single`/`queued` guard longer than a threshold (independent of the per-listener timeout, which still ultimately releases it), and a "currently running" / last-blocked indicator surfaced through the live per-listener snapshot so the UI can show that a handler is actively blocking re-fires.

### Web models and frontend

Add `mode: str`, `suppressed_count: int`, `dropped_count: int` to `ListenerWithSummary` (`src/hassette/web/models.py`) and the telemetry model (`telemetry_models.py`). `mode` is selected from the DB in the summary projection (`registration_queries.py`); `suppressed_count`/`dropped_count` are populated by the mapper (`web/mappers.py`) from the live in-memory snapshot, defaulting to 0. Regenerate types with `uv run python scripts/export_schemas.py --types`.

Frontend: render a mode chip in `unified-handler-row.tsx` (beside the kind chip) and add mode + suppressed/dropped cells to `listener-detail.tsx` (mirroring the existing conditional `Cancelled` cell — show only when non-zero), using the shared `Chip`/`Badge` components.

## Replacement Targets

No existing code is being replaced. The change is additive: a new enum, a new guard module, a new `mode` column, new web fields/UI cells, and a wrap at the existing `HandlerInvoker.dispatch` chokepoint. `parallel` mode is the explicit name for the current implicit fire-and-forget behavior, so the existing path is retained (as the `parallel` branch), not removed.

## Migration

Schema migration plus one behavioral change; no data transformation.

- **Schema:** `003.sql` adds the `mode` column to `listeners` via `ALTER TABLE ... ADD COLUMN` with `NOT NULL DEFAULT 'single'`. Existing rows backfill to `single`. Forward-only, consistent with `001.sql`/`002.sql`. (Note: a `user_version` mismatch recreates the DB from scratch — `database_service.py:476,493` — so the backfill runs on a fresh schema across an upgrade.)
- **Behavioral change — tier-aware default:** app-tier listeners default to `single`, changing runtime behavior for existing app handlers that currently overlap. Authors relying on overlap set `mode="parallel"`. Framework-tier registrations are unchanged (`parallel`).

Ships as a `feat!` with a `BREAKING CHANGE:` footer per `.claude/rules/changelog-quality.md`, naming the default flip and the `mode="parallel"` escape hatch. Acceptable pre-1.0 (current 0.43.0; targets the v1.0.0 milestone). The scheduler reschedule-timing change is **not** part of this PR — it ships with #1027.

## Convention Examples

### Behavioral options struct with `__post_init__` validation

**Source:** `src/hassette/bus/listeners.py:67`

```python
@dataclass(slots=True)
class ListenerOptions:
    """Behavioral timing parameters (once, debounce, throttle, timeout, priority) with validation."""

    once: bool = False
    debounce: float | None = None
    throttle: float | None = None
    timeout: float | None = None
    timeout_disabled: bool = False
    priority: int = 0

    def __post_init__(self) -> None:
        if self.debounce is not None and self.debounce <= 0:
            raise ValueError("'debounce' must be a positive number")
        if self.once and (self.debounce is not None or self.throttle is not None):
            raise ValueError("Cannot combine 'once=True' with 'debounce' or 'throttle'")
```

The new `mode: ExecutionMode = ExecutionMode.SINGLE` field follows this shape; the tier override is applied by the registration path that constructs the options (it knows `source_tier`), not baked into the dataclass default.

### Dispatch chokepoint to wrap

**Source:** `src/hassette/bus/listeners.py:192` (`HandlerInvoker.dispatch`)

```python
async def dispatch(self, invoke_fn: Callable[[], Awaitable[None]]) -> None:
    if self.once and self.fired:
        return
    if self.once:
        self.mark_fired()
    if self.rate_limiter:
        await self.rate_limiter.call(invoke_fn)
    else:
        await invoke_fn()
```

The mode guard wraps the actual invocation, after the once-guard and rate limiter. `parallel` is a pass-through so this path is byte-for-byte today's behavior when mode is `parallel`.

### Tier resolved at registration

**Source:** `src/hassette/bus/bus.py:552`

```python
source_tier = parent.source_tier
assert source_tier in ("app", "framework"), f"Invalid source_tier={source_tier!r} on {parent.class_name}"
```

The default mode is derived here (`framework → parallel`, else `single`) before the options are built, so the tier-aware default needs no new plumbing.

### Append-only column migration

**Source:** `src/hassette/migrations_sql/002.sql`

```sql
ALTER TABLE listeners ADD COLUMN cancelled_at REAL;
```

`003.sql` follows the same one-statement-per-line form. Migrations are never edited in place.

### StrEnum in the shared enums module

**Source:** `src/hassette/types/enums.py:18` (`RestartType`)

```python
class RestartType(StrEnum):
    ...
```

`ExecutionMode(StrEnum)` lives here beside it.

## Alternatives Considered

- **Global `single` default (no tier split).** Rejected: framework-internal listeners must run concurrently — `single` would drop the supervisor's FAILED events (`service_watcher.py:321,372`) and concurrent state-cache updates (`core/state_proxy.py:87`). The tier split mirrors HA, where modes apply to user automations only.
- **Global `parallel` default (non-breaking).** Rejected: leaves the unsafe default in place for app code and diverges from HA/the issue's stated `single` default.
- **Including the scheduler in this PR.** Rejected/deferred to #1027: recurring jobs can't self-overlap under the current after-completion reschedule timing, so the mode parameter would do nothing without a prerequisite reschedule-timing change. That change has independent merit (on-schedule firing) and its own risk (the scheduler heap/cancellation loop), so it ships as its own work reusing this design's enum and guard.
- **Persisting suppressed/dropped counts (best-effort columns + periodic flush).** Considered and rejected. It re-creates a data-integrity surface (re-registration upsert reset, retention deletion, crash-window loss, accumulator-reset discipline) for diagnostic counts whose loss doesn't matter. Live-only counts delete that surface entirely. Revisit only if counts ever need to be authoritative or survive restarts.
- **Per-event execution rows for suppressions (`status='suppressed'`).** Rejected: unbounded writes on high-frequency triggers re-create the log-spam anti-pattern in the database.
- **Two separate overlap implementations (bus now, scheduler later, each its own).** Rejected: the four-mode state machine and its lock are identical; two copies drift. One `ExecutionModeGuard` is built here and reused by #1027, with each surface supplying its own spawn-and-track callable.
- **Unbounded `queued`.** Rejected: memory-leak footgun. Fixed cap + newest-dropped; `max` lifts it later.
- **Numeric `max_instances` / RxJS operators.** Rejected: harder to reason about and misaligned with the HA-shaped audience.
- **`max`'s public-API impact.** Noted, not hidden: `max` will be additive on the bus (a new key in the `Options` TypedDict, no caller breaks), and shipping `queued` now at cap=10/newest-dropped sets an eviction-policy default `max` must stay compatible with.

## Test Strategy

### Existing Tests to Adapt

- **Bus dispatch/overlap tests** (covering `HandlerInvoker.dispatch` / `BusService.dispatch` in `tests/`): any test that fires a listener rapidly and asserts overlapping invocation counts now sees app-tier `single` semantics by default — set `mode="parallel"` explicitly or update expected counts.
- **Framework-tier behavior tests:** add/confirm that framework listeners (supervisor, state proxy, query service) still run concurrently — i.e., the tier default did not regress them.
- **Registration/upsert tests** (`telemetry_repository` / registration queries): adapt for the `mode` column in insert-params and the summary projection.
- **Web model / OpenAPI snapshot tests:** regenerated schema adds three fields to `ListenerWithSummary`; update snapshots and regenerate `generated-types.ts`/`ws-types.ts`.

### New Test Coverage

- **Unit — `ExecutionModeGuard`:** single suppresses + increments `suppressed` (FR#4, FR#15); restart cancels-and-replaces (FR#6/FR#7); restart A→B→C never runs two concurrently, asserting the lock serializes teardown (FR#13); queued orders and drains (FR#8); queued cap drops newest + increments `dropped` (FR#9, FR#15); parallel runs concurrently (FR#11); `release()` clears task + queue (FR#17). Use an `asyncio.Event` gate to hold an invocation "running" while firing re-triggers (the startup-race pattern in CLAUDE.md).
- **Unit — tier default + validation:** app→`single`, framework→`parallel` (FR#3); invalid `mode` rejected (FR#12).
- **Integration — bus:** each mode via real `on_state_change`; DEBUG log on suppress/drop asserted via the counter increment, not log capture (per testing rules).
- **Integration — live counters:** after drops, the web listener-summary endpoint returns the live suppressed/dropped counts merged by `db_id` (FR#15); a retired listener reports zero.
- **Integration — composition:** `mode`+`debounce` (FR#20), `mode`+`once=True` (FR#21), `mode`+duration-hold (FR#22).
- **Integration — telemetry:** `mode` persists across re-registration and a mode-only change is detected by `diff_fields()`; restart-cancel lands as `status='cancelled'` (FR#16).
- **System/E2E (core change):** touches `src/hassette/core/bus_service.py` dispatch, so run `nox -s system` and `nox -s e2e` per CLAUDE.md. Confirm the mode chip and suppressed/dropped counts render in app detail (FR#18/FR#19), and add a system-level assertion that the supervisor still restarts a second failed service while a first restart is in backoff (the framework-tier regression guard).

### Tests to Remove

No tests to remove. `parallel` retains the previously-default behavior under an explicit name; overlap tests are adapted, not deleted.

## Documentation Updates

- **`docs/` concept page — bus:** add an "Execution modes" section: the four modes by behavior, the tier-aware default, DEBUG logging, the `queued` cap, and that suppressed/dropped counts are live-only. System-as-subject per `voice-guide.md`; tested `.py` snippets under the page's `snippets/`. Run `doc-persona-review` on the new/edited page. (The scheduler concept-page update ships with #1027.)
- **Docstrings:** `mode` on every bus registration method and `ListenerOptions`; note the tier default, composition with debounce/throttle/`once`/duration, and that suppressed/dropped counts are live-only (FR#15, FR#20–22).
- **API reference allowlist:** if `ExecutionMode`/`ExecutionModeGuard` should appear in the generated reference, add to `PUBLIC_MODULES` in `tools/docs/gen_ref_pages.py`.
- **Migration guide / CHANGELOG framing:** `feat!` with a `BREAKING CHANGE:` footer per `.claude/rules/changelog-quality.md`, covering the default flip and the `mode="parallel"` escape hatch.
- **README:** update only if its feature list enumerates concurrency control (verify during implementation).

## Impact

### Changed Files

Shared/cross-cutting first (higher risk):

- `src/hassette/types/enums.py` — new `ExecutionMode` (imported by bus, telemetry, web; reused by #1027).
- `src/hassette/execution_mode.py` *(new)* — `ExecutionModeGuard` (lock, task ownership, deque, counters, `release()`) + queue-depth constant.
- `src/hassette/migrations_sql/003.sql` *(new)* — `mode` column on `listeners`.
- `src/hassette/bus/listeners.py` — `mode` on `ListenerOptions`; guard owned by `HandlerInvoker`; wrap in `dispatch`; `release()` on cancel.
- `src/hassette/bus/options.py` — `mode` in the `Options` TypedDict.
- `src/hassette/bus/bus.py` — tier-aware default at `:552`; `mode` via `**opts` for the three typed methods, but an explicit `mode` kwarg on the generic `on()` (`:429`) and on `_on_internal` (`:514`), threaded into `ListenerOptions`.
- `src/hassette/bus/sync.py` — `mode` via `**opts` for the typed sync facades; explicit `mode` kwarg on the sync `on()` (`:88`).
- `src/hassette/core/bus_service.py` — ensure the guard's handler task stays counted by `_dispatch_pending`; guard release on `remove_listener`; expose the live per-listener counter snapshot keyed by `db_id`; populate `mode` in `_build_registration` (`:166`).
- `src/hassette/core/registration.py` — add `mode` field to `ListenerRegistration`.
- `src/hassette/core/telemetry_repository.py` — `mode` in `_listener_insert_params` and the listener upsert (no counter columns).
- `src/hassette/core/telemetry_models.py`, `src/hassette/core/telemetry/registration_queries.py` — `mode` field + projection (two projection blocks).
- `src/hassette/bus/listeners.py` — also add `mode` to `config_matches()`/`diff_fields()` (not `matches()`).
- `src/hassette/web/models.py`, `src/hassette/web/mappers.py`, `src/hassette/web/routes/telemetry.py`, `src/hassette/web/routes/bus.py` — new response fields; merge live counts by `db_id` at both mapper call sites.
- `frontend/src/api/generated-types.ts`, `frontend/src/api/ws-types.ts`, `frontend/openapi.json`, `frontend/ws-schema.json` *(all regenerated)*.
- `frontend/src/components/app-detail/unified-handler-row.tsx`, `listener-detail.tsx` — mode chip + counter cells.
- `docs/` bus concept page + snippets; relevant docstrings.

<!-- Gap check 2026-06-14: 4 gaps included — bus/sync.py facades (covered via Options TypedDict) → T02; ws-types.ts/ws-schema.json regeneration (listener model flows over WS via web/routes/bus.py) → T03; web/routes/telemetry.py live-counter merge wiring → T03; extend tests/unit/test_source_tier_propagation.py for tier default → T02. ListenerOptions construction sites (test_utils/helpers.py:509, listeners.py:488, test_handler_invoker.py) are all keyword-based — safe. -->

### Behavioral Invariants

- **Framework-tier listeners are unchanged** — they default to `parallel`, today's behavior. The supervisor restarting concurrent failures and the state cache absorbing concurrent updates must keep working.
- **`parallel` mode == today's behavior**, exactly. The existing fire-and-forget spawn path remains reachable and unchanged under `parallel`.
- **Rate limiting (debounce/throttle) semantics are unchanged.** The guard sits after the rate limiter and must not alter when rate-limited invocations start.
- **`once=True` still fires at most once.**
- **The `_dispatch_pending` drain still sees all in-flight handler work** — the guard's task must not be invisible to it.
- **Telemetry natural key unchanged.** Listener `(app_key, instance_index, name, topic)` upsert key is unaffected by the new column.
- **Existing execution-row semantics unchanged.** `restart` reuses `status='cancelled'`; no new status value.
- **The scheduler is untouched** — `scheduled_jobs`, `scheduler.py`, and `scheduler_service.py` are not modified by this PR (that is #1027).

### Blast Radius

App-tier handlers change behavior at the default flip to `single`. Framework-tier code is held at `parallel` and should not change. The web API response grows three fields per listener; the UI gains a chip and two cells; the bus gains an in-memory counter snapshot read by the web layer. Because the change touches `src/hassette/core/bus_service.py` dispatch, regressions surface in the system/e2e suites — required pre-ship per CLAUDE.md, with an explicit supervisor-concurrency regression test.

## Open Questions

None. Resolved via challenge review and follow-up scoping: four modes on the bus; tier-aware default (`framework→parallel`, `app→single`); DEBUG-only suppression logging plus a distinct stall WARNING; `queued` bounded with newest-dropped eviction; `max` deferred but interface-additive; **live-only suppressed/dropped counts** (in-memory, read by the web layer by `db_id`, reset on restart — no DB columns, no flush, no integrity surface); `restart`-cancels as `cancelled` execution rows; a single shared `ExecutionModeGuard` with an internal lock and explicit task ownership; and the **scheduler half deferred to #1027** (it requires a reschedule-timing change to make modes meaningful and reuses this design's enum and guard).
