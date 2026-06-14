# Context: Execution Overlap Modes for Event Handlers

## Problem & Motivation

Event handlers fire-and-forget through `TaskBucket.spawn()` with no overlap control. When a trigger re-fires while its prior invocation is still running, both run concurrently — causing state corruption, duplicate side effects, and load-dependent races. Rate limiters (debounce/throttle) change *when* a handler starts, not whether overlapping executions are allowed. This adds a `mode` parameter (`single`/`restart`/`queued`/`parallel`, matching Home Assistant) to all bus registration methods so authors can declare overlap behavior per registration. Scope is the **event bus only**; the scheduler half is deferred to issue #1027 because recurring jobs can't currently overlap themselves (the scheduler reschedules only after a run completes).

## Visual Artifacts

None.

## Key Decisions

1. **Four modes via a shared `ExecutionMode` StrEnum** in `src/hassette/types/enums.py` (beside `RestartType`). `single` = drop re-fires while running; `restart` = cancel running + start new; `queued` = serialize in order; `parallel` = concurrent (today's behavior).
2. **One shared `ExecutionModeGuard`** (new `src/hassette/execution_mode.py`) owns the four-mode state machine, an internal `asyncio.Lock` (serializes `restart` teardown so no third trigger interleaves), the per-listener running-task reference, a bounded `deque` for `queued`, and two integer counters. It does no I/O. The scheduler follow-up (#1027) reuses it unchanged.
3. **Tier-aware default**: app-tier registrations default to `single`; framework-tier default to `parallel`. Computed at registration where `source_tier` is already resolved (`bus.py:552`). This preserves framework-internal listeners (supervisor, state-cache firehose, query service) that must run concurrently — exactly HA's split between core internals and user automations.
4. **Guard task ownership**: the guard does NOT spawn a detached task. Each chokepoint hands it a "run-and-track" callable that spawns through the same `task_bucket`/`_dispatch_pending` path the bus already uses, so the running handler stays counted by the dispatch-drain mechanism. The guard only decides whether/when to call it and retains the returned task for cancellation.
5. **`queued` is bounded** by a module constant `DEFAULT_QUEUE_DEPTH = 10` (matching HA), passed to the guard's constructor — newest-dropped eviction. A future `max` (deferred) overrides this constant with no change to the guard's shape.
6. **Suppressed/dropped counts are live-only** — held in memory on the guard, exposed to the web layer by listener `db_id`, reset on restart. NOT persisted (no DB columns, no flush loop). Only `mode` itself is persisted (a single new column). This deliberately avoids the data-integrity surface that persisting diagnostic counters would create.
7. **`restart` cancellations reuse the existing `status='cancelled'` execution row** path via `CommandExecutor` — no new mechanism.
8. **Logging**: suppressed/dropped events log at DEBUG only (never WARNING — the research's headline anti-pattern). The single exception is a distinct WARNING when a handler holds a `single`/`queued` guard past a stall threshold.

## Constraints & Anti-Patterns

- **Never log suppression/drops above DEBUG.** The only WARNING is the stall signal.
- **No per-event DB writes for no-op fires** — not an execution row, not a counter UPDATE. Counts live in memory only.
- **Do not persist the suppressed/dropped counts.** Persisting them was explicitly rejected; it re-introduces re-registration-upsert reset, retention deletion, and crash-window loss concerns.
- **The guard's handler task must remain visible to `_dispatch_pending`** — do not spawn a detached task the test/quiescence drain can't see.
- **`parallel` mode must be byte-for-byte today's behavior** — a pass-through, so the default-off path is unchanged.
- **Framework-tier listeners must not change behavior** — they default to `parallel`. A regression here breaks the service supervisor and stales the state cache.
- **`mode` is config (immutable, part of listener identity for diffing); overlap state and counts are runtime** (live only in the guard).
- **Do NOT touch the scheduler** — `scheduled_jobs`, `scheduler.py`, `scheduler_service.py` are out of scope (issue #1027).
- **Do NOT add the `max` parameter** — deferred; only design the cap as a constructor arg.

## Design Doc References

- `## Architecture` — the enum, the shared guard (lock/task-ownership/counters/release), tier-aware default, bus integration at the `HandlerInvoker.dispatch` chokepoint, telemetry split (persist mode, live counters), observability, web/frontend.
- `## Functional Requirements` — FR#1–FR#22.
- `## Acceptance Criteria` — AC#1–AC#16.
- `## Key Constraints` — DEBUG-only logging, no per-event writes, guard task model, bounded queue, framework-tier preservation.
- `## Migration` — `003.sql` adds the `mode` column; one behavioral change (tier default); ships `feat!`.
- `## Test Strategy` — existing tests to adapt, new coverage mapped to FRs, system/e2e for the core change.
- `## Impact` — changed files, behavioral invariants, blast radius.

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

The default mode is derived here (`framework → parallel`, else `single`) before the options are built.

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
