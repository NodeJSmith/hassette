# Context: Per-Listener Backpressure Overflow Policy (BLOCK + DROP_NEWEST)

## Problem & Motivation
Layer 1 (#1075) bounded concurrent event dispatch with a single global `asyncio.Semaphore`, but it
applies one implicit policy to every listener: block and wait for a slot. A noisy, low-value sensor
(e.g. a power meter emitting every 250ms) stalls the dispatch loop exactly as much as a critical
handler, and an app author has no way to opt that sensor out. #1076 (issue #72, Layer 2) makes the
saturation policy a per-listener choice. This PR ships `BLOCK` (default, current behavior) and
`DROP_NEWEST` (skip the event when the bus is saturated). `KEEP_LATEST` is a deferred non-goal.

## Visual Artifacts
None.

## Key Decisions
1. **Three-value enum shape, two values now.** `BackpressurePolicy(StrEnum)` mirrors `ExecutionMode`
   (`src/hassette/types/enums.py:58`). Ships `BLOCK` + `DROP_NEWEST`; `KEEP_LATEST` joins in a follow-up.
   Chosen over a generalized `(depth, overflow)` buffer — named policies are clearer and the buffer
   doesn't reduce the deferred KEEP_LATEST drain work.
2. **Enforce at the acquire gate, before spawn.** The semaphore is acquired per-listener before
   spawning (`bus_service.py:384-406`). `DROP_NEWEST` branches on `self._dispatch_semaphore.locked()`
   *before* the acquire: if locked, increment the drop counter and `continue` (no acquire, no spawn, no
   pending/idle bookkeeping). `BLOCK` and an omitted policy take the existing path byte-for-byte.
3. **`locked()` is race-free here.** No `await` separates `locked()` from the branch, so in
   single-threaded asyncio the immediately-following decision reflects the same state. Do NOT insert an
   await between them.
4. **Drop counter on `HandlerInvoker`, NOT `ExecutionModeGuard`.** The guard is documented overlap-only
   and is shared with the scheduler; a bus-decided counter there would be a cohesion violation and give
   every job a dead field. `HandlerInvoker` is per-listener and bus-only — `bp_dropped` lives there.
5. **Separate counter + UI cell.** Backpressure drops are distinct from `suppressed` (single-mode) and
   `dropped` (queued-cap). `live_execution_counts` widens to a `NamedTuple` (not a positional 3-tuple).
   The UI shows a drop *rate* (fraction of total), not a bare count.
6. **Persist the policy; counts stay live-only.** A `listeners.backpressure` column (migration 008,
   two-value `CHECK`) persists the configured policy for parity with `mode`. Drop *counts* are live-only
   and reset on restart, matching `suppressed`/`dropped`.

## Constraints & Anti-Patterns
- **Default must be `BLOCK` with ZERO behavior change.** The five existing tests in
  `tests/unit/core/test_bus_dispatch_semaphore.py` (lines 38, 84, 104, 120, 152) must pass unchanged.
- **No `await` between `locked()` and the `bp_dropped += 1` / branch.** Breaks both the TOCTOU-freedom
  and the single-writer atomicity of the counter.
- **A dropped event must NOT touch `_dispatch_pending` / `_dispatch_idle_event`.** It never spawns, so
  it must not enter pending/idle accounting, or `await_dispatch_idle`-based tests hang.
- **Do NOT put `bp_dropped` on `ExecutionModeGuard`** (`src/hassette/execution_mode.py`). It goes on
  `HandlerInvoker` (`src/hassette/bus/listeners.py:137`).
- **`live_execution_counts` must stay await-free.** It snapshots `router.owners` on the loop without
  synchronization.
- **Do NOT use `from __future__ import annotations`; use `X | None` not `Optional[X]`; create new
  objects, don't mutate.** Line length 120.
- **Out of scope (non-goals):** `KEEP_LATEST` coalescing/mailbox/drain; Layer 3 priority (#671); making
  saturation per-listener; runtime semaphore resizing.
- **Migration `CHECK` lists only `'block'` and `'drop_newest'`** — the values the code can emit. Do not
  pre-add `'keep_latest'`.

## Design Doc References
- `## Architecture` — the 7-part recommended approach (enum, plumbing, config equality, enforcement,
  instrumentation, persistence, web/frontend) with exact file:line anchors.
- `## Migration` — migration 008 shape and the CHECK-convention rationale.
- `## Test Strategy` — existing tests to adapt (incl. the two integration tests that fabricate the
  `live_execution_counts` tuple), new coverage mapped to FR/AC, pre-ship note (system + e2e suites).
- `## Edge Cases` — warning-text accuracy, fan-out-order sensitivity, sustained-saturation starvation.
- `## Documentation Updates` — the bus concept-page section and the non-obvious properties to document.
- `## Key Constraints` — default-BLOCK, no-await window, no pending/idle leak, single-writer invariant.

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
**DON'T** add an `await` inside this loop or return a wider *positional* tuple — use a `NamedTuple`.

### Conditional summary cell (frontend pattern to mirror)
**Source:** `frontend/src/components/app-detail/listener-detail.tsx:58-59`
```tsx
if (listener.suppressed_count > 0) cells.push({ label: "Suppressed", value: listener.suppressed_count });
if (listener.dropped_count > 0) cells.push({ label: "Dropped", value: listener.dropped_count });
```
`listener.total_invocations` (the "Calls" cell, line 41) is available as the drop-rate denominator.
