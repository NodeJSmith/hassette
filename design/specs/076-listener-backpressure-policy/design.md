# Design: Per-Listener Backpressure Overflow Policy (BLOCK + DROP_NEWEST)

**Date:** 2026-06-18
**Status:** approved
**Scope-mode:** reduce
**Research:** design/research/2026-06-18-listener-backpressure-policy/research.md

## Problem

Layer 1 (#678, merged via #1075) bounded concurrent event dispatch with a single global
`asyncio.Semaphore`. Before it, `BusService.dispatch` spawned one task per matching listener per
event with no ceiling — under a Home Assistant state storm, task count grew as `events × listeners`,
exhausting memory and starving the event loop.

Layer 1 fixed unbounded fan-out but applies one implicit policy to every listener: **block and wait
for a slot** (`bus_service.py:391`, `await self._dispatch_semaphore.acquire()`). A blocked acquire
stalls the whole dispatch loop, which is the intended backpressure — but it means a noisy sensor's
event stalls the loop exactly as much as a critical handler's. An app author has no way to say "if
the bus is saturated, drop my event rather than add to the backlog." A high-frequency, low-value
sensor (e.g. a power meter emitting every 250ms) contributes to saturation that delays everything
else, with no opt-out.

#1076 (issue #72, Layer 2) makes the saturation policy a per-listener choice.

## Goals

- A listener can declare `backpressure="drop_newest"` so its events are skipped when the dispatch
  semaphore is saturated, instead of blocking the loop.
- The default policy is `BLOCK` — existing apps see **zero behavior change**.
- Dropped events are observable: a live per-listener counter, surfaced in the monitoring UI and
  distinguishable from existing `suppressed` (single-mode) and `dropped` (queued-cap) counts.
- The configured policy is persisted on the `listeners` table for parity with `mode`, so the UI can
  show a listener's policy even at zero drops.

## Non-Goals

- **`KEEP_LATEST` (coalescing).** Replacing a pending event with the newest requires per-listener
  cross-event state (a 1-slot mailbox) plus a drain mechanism in the dispatch loop — the only
  High-risk part of the feature, with no precedent in the codebase. It is deferred to a tracked
  follow-up issue (see Open Questions) and gets its own design + `/mine-challenge` pass.
- **Layer 3 event-priority classification (#671).** Out of scope.
- **Per-listener (rather than global) saturation.** The semaphore is global; `DROP_NEWEST` drops
  when the *whole bus* is saturated, not when this listener alone is busy. That is the intended
  meaning; this design documents it rather than changing it.
- **Resizing the semaphore at runtime.** Unchanged from Layer 1.

## User Scenarios

### App author: writes a noisy-sensor automation
- **Goal:** prevent a high-frequency sensor's handler from contributing to dispatch backlog.
- **Context:** registering a bus subscription in `on_initialize`.

#### Declare a drop policy on a subscription

1. **Calls `self.bus.on_state_change(..., backpressure="drop_newest", name="power_meter")`**
   - Sees: the same subscription call shape as `mode`/`debounce` — one more keyword.
   - Decides: which listeners are "droppable under load" vs. must-not-miss (default `BLOCK`).
   - Then: at registration the policy is validated, persisted, and carried on the listener.

2. **Under a state storm, the bus saturates**
   - Sees (later, in the UI): a "Backpressure dropped" count climbing for that listener.
   - Then: the listener's events are skipped while saturated; critical (`BLOCK`) listeners still
     wait for capacity and run every event.

### Operator: monitors listener health in the web UI
- **Goal:** see whether a listener is dropping events under load and how many.
- **Context:** the app-detail Listeners view.

#### Inspect drop counts

1. **Opens a listener's detail row**
   - Sees: the configured backpressure policy, and a "Backpressure dropped" cell when the count > 0.
   - Decides: whether to raise `lifecycle.max_concurrent_dispatches`, speed up handlers, or accept
     the drops.
   - Then: no action required from the framework — counts are live diagnostics.

## Functional Requirements

- **FR#1** A subscription accepts an optional `backpressure` parameter — a `BackpressurePolicy` enum
  value or its string form — on the raw `Bus.on()` method (explicit param) and on every typed `on_*`
  method (`on_state_change`, `on_attribute_change`, `on_call_service`, via `Unpack[Options]`).
- **FR#2** When `backpressure` is omitted, the listener's effective policy is `BLOCK`.
- **FR#3** A `BLOCK` listener waits for a dispatch slot exactly as it does today (acquire then spawn);
  no observable behavior changes for existing listeners.
- **FR#4** A `DROP_NEWEST` listener, when the dispatch semaphore is saturated at its acquire point,
  skips dispatch for that event (no task spawned, no slot acquired) and records one drop.
- **FR#5** A `DROP_NEWEST` listener, when the semaphore is **not** saturated, dispatches normally
  (acquire then spawn), identical to `BLOCK`.
- **FR#6** Each listener exposes a live count of events it dropped due to backpressure, tracked
  separately from the existing suppressed (single-mode) and dropped (queued-cap) counts.
- **FR#7** The backpressure-drop count is surfaced in the listener's web summary and rendered in the
  UI when greater than zero, labeled distinctly from "Suppressed" and "Dropped".
- **FR#8** The configured policy is persisted with the listener's registration record so it survives
  and is queryable, defaulting to `BLOCK` for listeners written before this change.
- **FR#9** An invalid `backpressure` string raises a clear `ValueError` at registration time, listing
  the valid values (mirroring the `mode` coercion error).
- **FR#10** `config_matches`/`diff_fields` treat `backpressure` as a configuration field, so an
  `if_exists="skip"` re-registration with a changed policy reports drift.

## Edge Cases

- **Invalid policy string** (`backpressure="drop"`): coercion fails in `ListenerOptions.__post_init__`
  → `ValueError` listing valid values. (FR#9)
- **`DROP_NEWEST` + `debounce`/`throttle`/`mode`:** orthogonal — backpressure gates at the dispatch
  acquire point (system saturation); debounce/throttle/mode act inside the invoker (per-listener
  rate/overlap). No combination is forbidden for the two shipped policies; this is allowed and
  documented. (Contrast: KEEP_LATEST *would* need composition rules — deferred with it.)
- **Drop does not leak dispatch bookkeeping:** a dropped event must NOT increment `_dispatch_pending`
  or clear `_dispatch_idle_event` (it never spawns a task), or `await_dispatch_idle`-based tests hang.
- **Saturation-warning text accuracy:** the shared `warn_dispatch_saturated` message
  (`bus_service.py:151-155`) currently says new dispatches are *"waiting for a slot"* — false for a
  `DROP_NEWEST` listener, which discards rather than waits. Reword the warning to be policy-neutral
  (state that the bus is saturated and that listeners may be waiting *or dropping per their policy*),
  so the one rate-limited warning isn't misleading now that it fires for two opposite outcomes. Keep
  its existing rate limiting.
- **Fan-out order affects which listener drops:** the semaphore is global and `locked()` is checked
  fresh per listener inside the per-event fan-out loop. A `BLOCK` listener earlier in the loop can take
  the last slot; a `DROP_NEWEST` listener later in the same event then sees `locked()` and drops. So
  *which* `DROP_NEWEST` listener drops within one event depends on fan-out order (route specificity,
  then registration order). This is the intended contract — "drop if no free slot at the instant this
  listener is reached" — and must be **documented**, not smoothed over.
- **Sustained-saturation starvation:** under sustained saturation a `DROP_NEWEST` listener may be
  skipped *every* time and never run for the duration of the storm. This is intended for the noisy-
  sensor use case but is surprising — document plainly that `DROP_NEWEST` listeners may not run at all
  while the bus stays saturated, and that must-run handlers should use `BLOCK`.
- **`db_id is None`** (listener not yet persisted): `live_execution_counts` skips it, as today; the
  web layer treats a missing entry as zero.

## Acceptance Criteria

- **AC#1** (FR#3, FR#5) `test_dispatch_under_limit_runs_all_without_blocking` and the existing
  semaphore tests pass unchanged; a `DROP_NEWEST` listener under the limit runs every event.
- **AC#2** (FR#4) A new test: with the semaphore held locked, a `DROP_NEWEST` listener's event is
  skipped (handler not invoked) and its `bp_dropped` increments by exactly one per dropped event.
- **AC#3** (FR#3) With the semaphore held locked, a `BLOCK` listener's dispatch blocks until a slot
  frees, then runs (unchanged Layer 1 behavior).
- **AC#4** (FR#6, FR#7) A listener with `bp_dropped > 0` returns a non-zero backpressure-drop field in
  its `ListenerWithSummary`, and the UI renders a distinct cell; `suppressed`/`dropped` are unaffected.
- **AC#5** (FR#8) After registering a `DROP_NEWEST` listener, the `listeners` row has
  `backpressure = 'drop_newest'`; a `BLOCK`/omitted listener has `'block'`.
- **AC#6** (FR#9) `on_state_change(..., backpressure="bogus")` raises `ValueError` naming the valid
  policies.
- **AC#7** (FR#10) Re-registering an existing listener under `if_exists="skip"` with a different
  `backpressure` value reports `backpressure` in the drift error.
- **AC#8** `uv run pyright` and the migration runner apply cleanly; a fresh DB and a DB migrated from
  the prior schema both end with the `backpressure` column defaulting to `'block'`.
- **AC#9** (FR#8, upsert path) Registering `name=X` with `BLOCK`, then re-registering `name=X` with
  `DROP_NEWEST` via `if_exists="replace"`, leaves the persisted `listeners` row reading `'drop_newest'`
  — exercising the `ON CONFLICT ... DO UPDATE SET` clause, not just the first INSERT.

## Key Constraints

- **Default must be `BLOCK` with zero behavior change.** The acquire-gate code path for an omitted
  policy must be byte-for-byte the current path. Do not restructure the loop in a way that changes
  `BLOCK` timing.
- **`DROP_NEWEST` must not `await` between `locked()` and the decision.** The race-free saturation
  check depends on no `await` separating `self._dispatch_semaphore.locked()` from the branch. Adding
  an await reintroduces a TOCTOU race. (See `bus_service.py:386-391` comment.)
- **A dropped event must not touch `_dispatch_pending` / `_dispatch_idle_event`.** Coalesced/dropped
  events never spawn, so they must not enter the pending/idle accounting.
- **`live_execution_counts` must stay await-free.** It snapshots `router.owners` on the loop without
  synchronization; widening its return type must not introduce an await or a tearing risk.
- **`bp_dropped` has exactly one writer.** It is incremented only in the dispatch loop, on the event
  loop, with no `await` between the `locked()` check and the increment — the same no-await window that
  makes the saturation check race-free. Do not split them or insert an `await` (e.g. an async metrics
  emit) between the check and the increment. Encode this as an inline comment on the drop branch.
- **Migration `CHECK` lists only implemented values.** The `backpressure` column's CHECK constraint
  allows only `'block'` and `'drop_newest'` — the values the enum can emit this PR. The KEEP_LATEST
  follow-up owns widening the constraint (a new migration), so the DB never accepts a value the code
  can't produce.

## Dependencies and Assumptions

- Builds directly on Layer 1 (#1075). Assumes the global dispatch semaphore and acquire-before-spawn
  structure (`bus_service.py:384-406`) are stable.
- Assumes `ExecutionMode` (`enums.py:58`) remains the canonical StrEnum + tier-default precedent.
- Assumes the migration runner applies numbered SQL files in `src/hassette/migrations_sql/` in order
  (next file: `008.sql`).
- No external systems or teams.

## Architecture

The recommended approach is **Option B** from the research brief: ship the full `BackpressurePolicy`
enum carrying `BLOCK` + `DROP_NEWEST`, enforced at the acquire gate, with complete instrumentation,
persistence, UI, and docs. Every piece reuses an existing, verified rail.

### 1. Policy enum — `src/hassette/types/enums.py`

Add a `BackpressurePolicy(StrEnum)` mirroring `ExecutionMode` (`enums.py:58`):

```python
class BackpressurePolicy(StrEnum):
    """What a listener does when the dispatch concurrency semaphore is saturated."""
    BLOCK = auto()        # wait for a slot (default; today's behavior)
    DROP_NEWEST = auto()  # skip this event if saturated
```

Add a `DEFAULT_BACKPRESSURE_POLICY: str = BackpressurePolicy.BLOCK.value` constant alongside
`DEFAULT_OVERLAP_MODE` for use as the registration/summary default. `KEEP_LATEST` is intentionally
absent — it joins the enum in the follow-up.

### 2. Option plumbing — `Options` → `ListenerOptions` → `_on_internal`

- `src/hassette/bus/options.py`: add a `backpressure: BackpressurePolicy | str` key to the `Options`
  TypedDict with a docstring matching the `mode` entry's style. This covers the `on_state_change`/
  `on_attribute_change`/`on_call_service` methods, which take `**opts: Unpack[Options]` and forward
  through `_subscribe` into `_on_internal` — no per-method edit needed for them.
- `src/hassette/bus/listeners.py`: add `backpressure: BackpressurePolicy = BackpressurePolicy.BLOCK`
  to `ListenerOptions` (it is `@dataclass(slots=True)`, **not** frozen — match it, do not add frozen).
  Extend `__post_init__` (`listeners.py:114`) to coerce a raw string into the enum with a clear
  `ValueError`, mirroring the `mode` coercion at lines 117-122. The policy is read at the gate via
  `listener.options.backpressure` (see §4) — no copy onto `HandlerInvoker` (the `HandlerInvoker` gains
  only the `bp_dropped` *counter*, see §5).
- `src/hassette/bus/bus.py`: **`_on_internal` and `Bus.on()` have fully explicit named params — there
  is no `**opts` catch-all to ride on.** `mode` is threaded as an explicit param through both; mirror
  it exactly:
  - Add `backpressure: BackpressurePolicy | str | None = None` to `_on_internal`'s signature
    (`bus.py:521-540`, alongside `mode` at line 533), and pass `backpressure=backpressure` into the
    `ListenerOptions(...)` construction (`bus.py:600`).
  - Add the same explicit param to the public `Bus.on()` signature (`bus.py:429-445`, alongside `mode`
    at line 441) and forward it explicitly in `on()`'s `_on_internal(...)` call (`bus.py:497-515`,
    alongside `mode=mode` at line 508). Without this, `self.bus.on(topic=..., backpressure="drop_newest")`
    raises `TypeError` — `on()` is the one public method not backed by `Options`.
  - Resolve an omitted policy to a flat `BLOCK` (not tier-aware, unlike `mode`) — either via the
    `ListenerOptions` field default or a `backpressure or BackpressurePolicy.BLOCK` at construction.
    No tier-resolution block is needed, so this is simpler than `mode`'s `bus.py:567-580` logic.

### 3. Config equality — `config_matches` / `diff_fields`

Add a `backpressure` comparison to `diff_fields` (`listeners.py:536`, alongside the `mode` check at
line 560) and the matching `config_matches`. Without this, an `if_exists="skip"` re-registration with
a changed policy silently mismatches. (FR#10)

### 4. Enforcement — the acquire gate in `bus_service.dispatch`

The per-listener loop (`bus_service.py:384-406`) acquires the semaphore before spawning. Branch on the
policy *before* the acquire:

```python
for listener in listeners:
    if self._dispatch_semaphore.locked():
        self.warn_dispatch_saturated()
        if listener.options.backpressure is BackpressurePolicy.DROP_NEWEST:
            listener.invoker.bp_dropped += 1   # single writer: this loop, on the loop, no await
            self.logger.debug("backpressure drop_newest: skipping event for %s", listener.identity.name)
            continue  # no acquire, no spawn, no pending/idle bookkeeping
    await self._dispatch_semaphore.acquire()
    # ... unchanged BLOCK path: pending++, idle.clear(), spawn, done-callbacks ...
```

`BLOCK` (and an omitted policy) takes the existing path untouched. The `locked()` check is race-free
here because no `await` separates it from the branch (`bus_service.py:386-391` comment). The `continue`
skips all pending/idle accounting, satisfying the no-leak constraint.

**Single-writer invariant (must be documented in code).** `bp_dropped` is incremented only here — one
writer, on the event loop, with **no `await` between the `locked()` check and the increment**. This is
the same no-await window that makes the saturation check race-free; do not split them or insert an
`await` (e.g. an async metrics emit) between the check and the increment, or both the TOCTOU-freedom
and the counter's atomicity break. Add this as a Key Constraint and an inline comment on the branch.

### 5. Instrumentation — separate `bp_dropped` counter

- **The counter lives on `HandlerInvoker`, NOT `ExecutionModeGuard`.** `ExecutionModeGuard` is
  documented overlap-only (`execution_mode.py:4-6`: "holds no telemetry beyond two live counters")
  and its `suppressed`/`dropped` counts are decisions the guard itself makes inside
  `run_single`/`run_queued`. `bp_dropped` is a count of a decision made *outside* the guard, at the bus
  semaphore gate — putting it on the guard violates that contract and gives every scheduler job (which
  shares `ExecutionModeGuard` per #1027) a permanently-zero dead field. Instead add `bp_dropped: int`
  to `HandlerInvoker` (`listeners.py:137`, `@dataclass(slots=True)` — add to slots, init 0).
  `HandlerInvoker` is per-listener, is bus-only (jobs don't have one), and already holds bus-specific
  copies of `mode`/`once` for exactly this reason. The dispatch gate already reaches
  `listener.invoker` to spawn, so `listener.invoker.bp_dropped += 1` is the same reach depth.
- `src/hassette/core/bus_service.py`: `live_execution_counts` (`bus_service.py:232`) currently returns
  `dict[int, tuple[int, int]]` of `(suppressed, dropped)`, reading `guard.suppressed`/`guard.dropped`.
  Add the backpressure count by reading `listener.invoker.bp_dropped` (the guard stays untouched), and
  **widen the return to a small `NamedTuple`** (e.g. `LiveCounts(suppressed, dropped, bp_dropped)`)
  rather than a positional 3-tuple, so a future fourth count (KEEP_LATEST's `coalesced`) can't shift
  positions. Two **production** callers invoke it — `web/routes/telemetry.py:188` and
  `web/routes/bus.py:42` — and both pass the dict straight through to `to_listener_with_summary`
  without unpacking (type-annotation touch-up only).
- `src/hassette/web/mappers.py`: the only behavioral consumer. The tuple is **unpacked** in
  `to_listener_with_summary` (`mappers.py:188`, `suppressed, dropped = (live_counts or {}).get(...,
  (0, 0))`). Update the unpack to three fields, the default, and the `live_counts` type annotation
  (`mappers.py:175`).
- **Full caller inventory (per "migrate callers then delete legacy API").** Beyond the two routes and
  the mapper, two tests **fabricate the tuple shape** and MUST be migrated, or they pass at collection
  while asserting a stale shape: `tests/integration/web_api/test_telemetry.py:134`
  (`return_value={7: (2, 4)}`) and `tests/integration/bus/test_execution_modes.py:240-290`
  (`test_live_execution_counts_snapshot_keyed_by_db_id`). Construct the `NamedTuple` **by keyword**
  in tests (`LiveCounts(suppressed=2, dropped=4, bp_dropped=0)`) so a later field addition can't
  silently shift positions. `test_utils/web_mocks.py:156` returns `{}` (compatible — confirm no test
  relies on the old width).
- **Not affected:** the job-enrichment path (`web/utils.py:42-43`) reads `guard.suppressed`/
  `guard.dropped` directly off live heap entries — it does **not** call `live_execution_counts` and
  does **not** gain a backpressure field (jobs can't drop on the bus).

### 6. Persistence — migration + registration struct

- `src/hassette/migrations_sql/008.sql`: `ALTER TABLE listeners ADD COLUMN backpressure TEXT NOT NULL
  DEFAULT 'block' CHECK (backpressure IN ('block', 'drop_newest'));` — exactly the shape of `003.sql`
  (which added `mode`).
- `src/hassette/core/registration.py`: add `backpressure: str = DEFAULT_BACKPRESSURE_POLICY` to
  `ListenerRegistration` (alongside `mode`, line 64).
- `src/hassette/core/bus_service.py`: add `backpressure=listener.options.backpressure.value` to
  `build_registration` (alongside `mode=...`, line 229).
- `src/hassette/core/telemetry_repository.py`: **this is where the SQL lives, not `bus_service.py`.**
  Three coordinated edits: (1) add `"backpressure": registration.backpressure` to
  `_listener_insert_params` (`telemetry_repository.py:82`, alongside `"mode"` at line 109); (2) add the
  `backpressure` column + `:backpressure` bind to the `INSERT INTO listeners` statement
  (`telemetry_repository.py:292`, columns at line 297, values at line 303); (3) add
  `backpressure = excluded.backpressure` to the `ON CONFLICT ... DO UPDATE SET` clause (line 317,
  alongside `mode = excluded.mode`). Missing (3) means a re-registration with a changed policy keeps
  the old persisted value; missing (1)/(2) means the column silently stays at the SQL default `'block'`.

### 7. Web model + frontend

- `src/hassette/web/models.py`: add `backpressure_dropped_count: int = 0` and `backpressure: str`
  (the configured policy) to `ListenerWithSummary` (line 296, alongside `suppressed_count`/
  `dropped_count` at 334-335).
- `src/hassette/web/mappers.py`: `to_listener_with_summary` (line 173) maps the new live count and the
  persisted policy onto the model.
- `frontend/src/components/app-detail/listener-detail.tsx`: add a conditional cell mirroring lines
  58-59 — `if (listener.backpressure_dropped_count > 0) cells.push({ label: "Backpressure dropped",
  value: ... })`. **Render a drop rate, not just a raw count:** a bare count can't distinguish "50 of
  60" from "50 of 50,000". The summary already carries the listener's total-invocation count; show
  `bp_dropped` as a fraction of `(invocations + bp_dropped)` (e.g. `"40 (12%)"`) so a chronically-
  dropping listener is visually distinct from an incidental one. Show the configured policy chip only
  when non-default (`drop_newest`), consistent with how the UI avoids noise for default values.
  Regenerate types via `uv run python scripts/export_schemas.py --types`.

This UI change reuses the existing cell pattern (same `cells.push` shape, same conditional), so no new
design tokens are introduced.

## Replacement Targets

No existing code is being replaced. This is purely additive: a new enum value-set, a new option field,
a new branch in the dispatch loop (the existing `BLOCK` path is preserved verbatim), a new counter, a
new column, and a new UI cell. The only signature change is widening `live_execution_counts`'s return
from a positional tuple to a named struct — its three call sites are migrated in the same change, with
no compatibility shim (per coding-style: migrate callers, delete the old shape).

## Migration

`008.sql` adds `listeners.backpressure TEXT NOT NULL DEFAULT 'block'` with a `CHECK` allowing only
`'block'` and `'drop_newest'`. Existing rows (written before the migration) receive `'block'` via the
column default, preserving today's behavior. The migration is forward-only (consistent with the
existing numbered-SQL runner — no down-migrations in this project).

**Reversibility / forward-compat:** SQLite cannot alter a `CHECK` constraint in place, so adding
`KEEP_LATEST` later requires a table-rebuild migration. That cost is accepted and assigned to the
KEEP_LATEST follow-up. The two-value `CHECK` is the **house convention**, not belt-and-suspenders:
every enum-like TEXT column in this schema carries one — `003.sql` (`listeners.mode`), `005.sql`
(`tier`, `source_tier`), `006.sql` (`scheduled_jobs.mode`), `007.sql` (`blocking_events.reason`).
An unconstrained enum column would be the anomaly. Keeping the DB honest (it accepts only what the
code emits) is consistent with the existing schema and worth the one-time future rebuild.

## Convention Examples

### StrEnum with auto() + per-member docstrings

**Source:** `src/hassette/types/enums.py:58`

```python
class ExecutionMode(StrEnum):
    """Overlap behavior for a listener when a trigger fires while a prior invocation still runs."""
    SINGLE = auto()
    """Drop the re-fire while a prior invocation is still running."""
    RESTART = auto()
    """Cancel the running invocation and start a new one."""
```

### Dataclass option field + string coercion in `__post_init__`

**Source:** `src/hassette/bus/listeners.py:105-122`

```python
mode: ExecutionMode = ExecutionMode.SINGLE
# ...
def __post_init__(self) -> None:
    if not isinstance(self.mode, ExecutionMode):
        try:
            self.mode = ExecutionMode(self.mode)
        except ValueError as exc:
            valid = ", ".join(repr(m.value) for m in ExecutionMode)
            raise ValueError(f"Invalid execution mode {self.mode!r}; must be one of {valid}") from exc
```

### ALTER TABLE migration with CHECK constraint

**Source:** `src/hassette/migrations_sql/003.sql`

```sql
ALTER TABLE listeners ADD COLUMN mode TEXT NOT NULL DEFAULT 'single'
    CHECK (mode IN ('single', 'restart', 'queued', 'parallel'));
```

### Live-counter snapshot (await-free) — the pipeline `bp_dropped` joins

**Source:** `src/hassette/core/bus_service.py:232-253`

```python
def live_execution_counts(self) -> "dict[int, tuple[int, int]]":
    counts: dict[int, tuple[int, int]] = {}
    for listeners in self.router.owners.values():
        for listener in listeners:
            if listener.db_id is None:
                continue
            guard = listener.invoker.guard
            counts[listener.db_id] = (guard.suppressed, guard.dropped)
    return counts
```

**DON'T** add an `await` inside this loop or return a wider *positional* tuple — use a `NamedTuple` so
the unpack site (`mappers.py:188`) stays readable.

### Saturation test harness (semaphore held locked)

**Source:** `tests/unit/core/test_bus_dispatch_semaphore.py:38,84`

The existing tests (`test_dispatch_bounds_concurrent_handlers`,
`test_dispatch_under_limit_runs_all_without_blocking`) show the pattern: drive `dispatch` with the
semaphore saturated and assert on handler invocation. New `DROP_NEWEST` tests mirror this — hold the
semaphore locked, dispatch, assert the handler did not run and `bp_dropped` incremented.

## Alternatives Considered

- **Option A — all three policies including `KEEP_LATEST` now.** Rejected for this PR: `KEEP_LATEST`
  needs a coalescing mailbox + drain mechanism with re-entrancy against `release_dispatch_slot` and
  subtle `_dispatch_pending` accounting — the only High-risk subtask, with no codebase precedent. It
  deserves its own design and `/mine-challenge` pass. Shipping B first validates the entire
  API/telemetry/persistence/UI surface so the follow-up is purely the dispatch-mechanics problem.
- **Option C — generalized bounded mailbox `(depth, overflow)`.** Rejected: more configuration surface
  than the issue asks for, diverges from the named policies users understand, competes conceptually
  with `mode=queued`'s in-invoker buffer, and does **not** reduce the hard drain work it shares with A.
  Violates subtract-first / experience-first ("say no to 1,000 options").
- **In-memory-only policy (no DB column).** Rejected by user decision: inconsistent with how `mode`
  and `debounce` persist, and the UI couldn't show a listener's configured policy at zero drops.
- **Reuse the existing `dropped` counter** instead of a separate `bp_dropped`. Rejected by user
  decision: conflates queued-cap drops with backpressure drops in the UI; distinct attribution is
  clearer.
- **Do nothing / manual workaround.** App authors could self-throttle in the handler, but the handler
  only runs *after* acquiring a slot — it can't relieve the saturation it contributes to. The whole
  point of Layer 2 is gating before the acquire.

## Test Strategy

### Existing Tests to Adapt
- `tests/unit/core/test_bus_dispatch_semaphore.py` — the five existing tests (lines 38, 84, 104, 120,
  152) must pass **unchanged** (they pin the `BLOCK`/default behavior; AC#1, AC#3).
- `tests/integration/web_api/test_telemetry.py:134` and `tests/integration/bus/test_execution_modes.py`
  (`test_live_execution_counts_snapshot_keyed_by_db_id`, ~240-290) — these **fabricate** the
  `(suppressed, dropped)` tuple shape; migrate them to the keyword-constructed `NamedTuple`
  (`LiveCounts(suppressed=…, dropped=…, bp_dropped=0)`) or they assert a stale shape.
- `tests/unit/bus/test_listeners.py` — extend `config_matches`/`diff_fields` and `__post_init__`
  validation tests to cover `backpressure` (drift detection, invalid-value `ValueError`; AC#6, AC#7).
- Any web/mapper test asserting `ListenerWithSummary` fields — add the new fields.

### New Test Coverage
- **FR#4 / AC#2:** `DROP_NEWEST` skips under a locked semaphore; `bp_dropped` increments by one per
  drop; handler not invoked. (unit, `test_bus_dispatch_semaphore.py`)
- **FR#5:** `DROP_NEWEST` under the limit dispatches normally. (unit)
- **FR#3 / AC#3:** `BLOCK` still blocks-then-runs under saturation. (unit)
- **FR#6 / FR#7 / AC#4:** `bp_dropped` (on `HandlerInvoker`) flows through `live_execution_counts` →
  `ListenerWithSummary`; UI renders the cell with a drop rate when > 0. (unit for the mapper; frontend
  cell follows existing pattern)
- **FR#8 / AC#5:** persisted `listeners.backpressure` value after first registration. (integration)
- **FR#8 / AC#9:** persisted policy is **updated** on `if_exists="replace"` re-registration — exercises
  the `DO UPDATE SET backpressure = excluded.backpressure` upsert clause, the real silent-bug trap.
  (integration)
- **FR#9 / AC#6:** invalid string → `ValueError`. (unit)
- **FR#10 / AC#7:** `if_exists="skip"` drift on changed policy. (unit)
- **AC#8:** migration applies on fresh and upgraded DB. (integration, migration-runner test)

### Tests to Remove
No tests to remove.

### Pre-ship note
This touches `src/hassette/core/` and `src/hassette/types/enums.py`, so per CLAUDE.md the system and
e2e suites must run locally before the PR — not just unit/integration. Do not run `pytest -n auto`
locally (known machine-freeze risk); let CI run the heavy suites.

## Documentation Updates

- **`docs/pages/core-concepts/bus/` (concept page + a tested snippet under its `snippets/`):** add a
  "Backpressure policy" section. Lead with what `DROP_NEWEST` does, show a minimal subscription with
  `backpressure="drop_newest"`. The page (and the `BackpressurePolicy` docstring's first sentence)
  must carry the load on these non-obvious properties, since the API shape sits next to per-listener
  `mode`/`debounce`:
  - **Global, not per-listener** (F13): `DROP_NEWEST` drops when the *whole bus* is saturated, not
    when this listener alone is busy — unlike `throttle`/`debounce`, which are per-listener rate.
  - **Starvation** (F10): a `DROP_NEWEST` listener may not run at all while the bus stays saturated;
    use `BLOCK` for must-run handlers.
  - **Fan-out order** (F9): within one event, which `DROP_NEWEST` listeners drop depends on dispatch
    order — "drop if no free slot at the instant this listener is reached."
  - **Trades a loud signal for a quiet one** (F8): `BLOCK` propagates overload as latency the operator
    feels; `DROP_NEWEST` converts it to silent loss visible only as the drop count. Use it only where
    loss is genuinely acceptable.
  - **Drop counts are live-only** (F6): they reset on app reload/restart and are never persisted — the
    configured *policy* persists, the *counts* do not.
  Follow voice-guide.md (system-as-subject on the concept page). Snippet is Pyright-checked in CI.
- **Docstrings:** `BackpressurePolicy` enum and members; the `backpressure` entry in the `Options`
  TypedDict and `ListenerOptions`; the `on_*` methods inherit the docstring via `Unpack[Options]`.
- **`docs/` API reference:** `BackpressurePolicy` is exported wherever `ExecutionMode` is (check the
  `PUBLIC_MODULES` allowlist in `tools/docs/gen_ref_pages.py` if a new public symbol needs surfacing).
- Run `doc-persona-review` + `doc-accuracy-review` on the new/edited bus page before the PR
  (per `.claude/rules/doc-rules.md`).
- **CHANGELOG:** none — release-please generates it from the conventional-commit PR title (`feat:`).

## Impact

<!-- Gap check 2026-06-18: clean. The challenge's reverse-dependency pass already surfaced the hidden
     consumers (telemetry_repository.py INSERT/upsert → T03; the two integration tests fabricating the
     live_execution_counts tuple → T04; web_mocks.py → T04); all are in this inventory and assigned to
     tasks. No further unlisted dependencies found (frontend total_invocations denominator confirmed
     present at models.py:305 / listener-detail.tsx:41). -->

### Changed Files
- `src/hassette/core/bus_service.py` (modify) — **cross-cutting/high-risk**: the dispatch acquire-gate
  branch (reads `listener.options.backpressure`, increments `listener.invoker.bp_dropped`),
  `live_execution_counts` return-type widening (reads `listener.invoker.bp_dropped`), and
  `build_registration` (the struct field — the SQL itself is in `telemetry_repository.py`).
- `src/hassette/types/enums.py` (modify) — new `BackpressurePolicy` enum + default constant.
- `src/hassette/bus/listeners.py` (modify) — `ListenerOptions.backpressure` + `__post_init__` coercion
  + `config_matches`/`diff_fields`; **`HandlerInvoker.bp_dropped` counter** (slot + init).
- `src/hassette/bus/bus.py` (modify) — add explicit `backpressure` param to **both** `Bus.on()`
  (signature + forward) and `_on_internal` (signature + pass into `ListenerOptions`).
- `src/hassette/bus/options.py` (modify) — `backpressure` key on the `Options` TypedDict (covers the
  typed `on_*` methods).
- *(`src/hassette/execution_mode.py` is intentionally NOT modified — the counter lives on
  `HandlerInvoker`, keeping the overlap guard pure and excluding scheduler jobs.)*
- `src/hassette/core/registration.py` (modify) — `backpressure` field on `ListenerRegistration`.
- `src/hassette/core/telemetry_repository.py` (modify) — **the listeners INSERT/upsert SQL**:
  `_listener_insert_params`, the `INSERT INTO listeners` column+bind list, and the `DO UPDATE SET`
  upsert clause.
- `src/hassette/migrations_sql/008.sql` (create) — `listeners.backpressure` column.
- `src/hassette/web/models.py` (modify) — `ListenerWithSummary` fields.
- `src/hassette/web/mappers.py` (modify) — widen the `live_counts` unpack + type annotation; map new
  fields onto the summary.
- `src/hassette/web/routes/telemetry.py`, `src/hassette/web/routes/bus.py` (modify) — the two callers
  of `live_execution_counts`; pass the `NamedTuple`-valued dict through (type flow only).
- `src/hassette/test_utils/web_mocks.py` (verify) — mocks `live_execution_counts` returning `{}`;
  compatible with the wider struct, but confirm no test relies on the old tuple width.
- `frontend/src/components/app-detail/listener-detail.tsx` (modify) — new cell.
- `frontend/src/api/generated-types.ts`, `openapi.json`, `ws-schema.json`, `ws-types.ts` (regenerate).
- `tests/unit/core/test_bus_dispatch_semaphore.py`, `tests/unit/bus/test_listeners.py` (modify),
  plus a migration-runner integration test (modify/create).
- `tests/integration/web_api/test_telemetry.py`, `tests/integration/bus/test_execution_modes.py`
  (modify) — these fabricate the `live_execution_counts` tuple shape; migrate to the keyword-
  constructed `NamedTuple`.
- `docs/pages/core-concepts/bus/` page + `snippets/` (modify/create).

### Behavioral Invariants
- `BLOCK`/omitted dispatch timing and ordering — must remain identical to Layer 1 (the five existing
  semaphore tests are the pins).
- `_dispatch_pending` / `_dispatch_idle_event` accounting and `await_dispatch_idle` semantics —
  unchanged; drops must not perturb them.
- `suppressed` / `dropped` counters and their UI cells — unchanged; `bp_dropped` is additive.
- The await-free guarantee of `live_execution_counts`.
- Existing `listeners` rows and consumers — the new column defaults to `'block'`.

### Blast Radius
- Anything touching the `live_execution_counts` return shape — two production routes (pass-through),
  the `mappers.py` unpack, and two integration tests that fabricate the tuple — covered by migrating
  all of them to the keyword-constructed `NamedTuple`. The scheduler job path is unaffected.
- The OpenAPI/WS schema consumers (frontend) — covered by regenerating types.
- App authors: purely additive opt-in; no existing app changes behavior.

## Open Questions

- [ ] **KEEP_LATEST follow-up issue:** file it (labels `type:enhancement`, `area:bus`, `area:core`,
  `topic:events`, `size:medium`) capturing the deferred coalescing mailbox + drain design, the
  composition rules vs debounce/duration/mode, and the `CHECK`-widening migration. To be created when
  this design is approved.
- [x] **Surface the configured policy in the UI even at zero drops?** Resolved: show the policy chip
  only when non-default (`drop_newest`), consistent with how the UI avoids noise for default values.
  (See §7.)
