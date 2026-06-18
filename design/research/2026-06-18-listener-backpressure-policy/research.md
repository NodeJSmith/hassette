---
proposal: "Add a per-listener backpressure overflow policy (BLOCK/DROP_NEWEST/KEEP_LATEST) governing what happens when the Layer 1 dispatch concurrency semaphore is saturated."
date: 2026-06-18
status: Draft
flexibility: Exploring
motivation: "Implement issue #1076 (#72 Layer 2), building on the just-merged Layer 1 dispatch semaphore (#678/#1075). Let critical handlers block for capacity while noisy sensors drop or coalesce instead of adding to backlog."
constraints: "No `from __future__ import annotations`; `X | None` over Optional; immutability (new objects, not mutation); design-completeness (docs + frontend ship with the feature). Default must be BLOCK with zero behavior change for existing apps."
non-goals: "Layer 3 event-priority classification (#671). Replacing the inbound bounded channel. Persisting drop counts to the telemetry DB."
depth: deep
---

# Research Brief: Per-Listener Backpressure Overflow Policy (#1076, #72 Layer 2)

**Initiated by**: Implementing issue #1076 — let a subscription declare how it behaves when the Layer 1 dispatch concurrency semaphore is saturated, with three prescribed policies: `BLOCK` (default), `DROP_NEWEST`, `KEEP_LATEST`.

## Context

### What prompted this

Layer 1 (#678, merged via #1075, commit `cb544558`) bounded concurrent dispatch with a single global `asyncio.Semaphore`. Before it, `BusService.dispatch` spawned one task per matching listener per event with no ceiling — under a Home Assistant state storm, task count grew as `events x listeners`, exhausting memory and starving the loop. Layer 1 fixed unbounded fan-out but applied one implicit policy to every listener: **block and wait for a slot**.

The design research (`design/research/2026-05-02-bus-backpressure/research.md`) lays out a three-layer plan. Layer 2 (this issue) makes that tolerance a per-listener choice. The research explicitly recommends Pattern 6 (Per-Subscription Policy), quoting: *"Allow listeners to declare their backpressure tolerance: `BackpressurePolicy.BLOCK` (wait for capacity — default), `BackpressurePolicy.DROP_NEWEST` (skip if at capacity), `BackpressurePolicy.KEEP_LATEST` (replace pending with newest)."* (Direct — research.md). Layer 3 (#671) is event-priority classification and is out of scope here.

### Current state

The dispatch path is well understood from reading the code. Confidence: **Direct** (quoted from source).

**The dispatch loop** — `src/hassette/core/bus_service.py:348-406`. After matching and dedup, the loop fans out per-listener:

```python
for listener in listeners:
    # locked() exactly predicts a blocking acquire here: no await separates the two
    if self._dispatch_semaphore.locked():
        self.warn_dispatch_saturated()
    await self._dispatch_semaphore.acquire()          # <-- line 391: this IS the BLOCK policy

    self._dispatch_pending += 1
    self._dispatch_idle_event.clear()
    try:
        task = self.task_bucket.spawn(self._dispatch(route, event, listener), name="bus:dispatch_listener")
    except BaseException:
        self._dispatch_semaphore.release()
        self.decrement_dispatch_pending()
        raise
    task.add_done_callback(self.release_dispatch_slot)
    task.add_done_callback(self.on_dispatch_done)
```

Key facts that shape the whole feature:

1. **Dispatch is per-listener, not per-event.** One event matching N listeners acquires N slots. The semaphore is created once at startup (`bus_service.py:85-87`) from `lifecycle.max_concurrent_dispatches` (default 50, min 1). Resizing requires a restart.
2. **The semaphore is acquired *before* `spawn`, deliberately.** A blocked acquire stalls the dispatch loop -> serve loop -> inbound channel -> WS reader. That is the real backpressure. `DROP`/`KEEP_LATEST` must intercept *at this acquire point* (line 389-391); they cannot simply move work inside the spawned task, or they lose the upstream propagation property.
3. **`locked()` is race-free here.** The comment at `bus_service.py:387-388` is correct: in single-threaded asyncio with no `await` between `locked()` and `acquire()`, no other task mutates the counter in between. A non-blocking saturation check at this exact point is sound. Confidence: **Supported** (CPython issue #97028 notes `locked()` can return `False` with waiters queued, but that is irrelevant here — we check `locked()==True` to detect saturation, and the no-await window guarantees the acquire that immediately follows reflects the same state).
4. **Per-listener overlap state already exists.** `ExecutionModeGuard` (`src/hassette/execution_mode.py:34-161`) holds `suppressed` and `dropped` live counters and a bounded `pending: deque` for QUEUED mode. This is the closest existing analog to KEEP_LATEST coalescing and the model for the drop counter.
5. **The option plumbing path is well-trodden.** An option travels: `on_*` method `**opts: Unpack[Options]` -> `_subscribe` -> `_on_internal` -> `ListenerOptions(...)` construction (`bus.py:600-608`) -> stored on `Listener.options` -> read at dispatch. `ExecutionMode` (a `StrEnum` in `types/enums.py:58-72`) is the exact precedent for a new policy enum, including tier-aware default resolution in `_on_internal` (`bus.py:567-580`).

**Instrumentation precedent is strong.** The `suppressed`/`dropped` counters demonstrate the exact "live, in-memory, never persisted" pipeline a drop count should follow:
- Counter lives on the in-memory guard (`execution_mode.py:49-61`).
- `BusService.live_execution_counts()` (`bus_service.py:232-253`) snapshots `{db_id: (suppressed, dropped)}` from active listeners' guards — no DB, no awaits, race-safe.
- The web route (`web/routes/telemetry.py:188-189`) calls it per request and merges via `to_listener_with_summary` (`web/mappers.py:173-227`).
- Response model `ListenerWithSummary` (`web/models.py:296-336`) carries `suppressed_count`/`dropped_count`, defaulting to 0.
- Frontend renders them conditionally when `> 0` in `frontend/src/components/app-detail/listener-detail.tsx:57-59`.

### Key constraints

- **Default = BLOCK, zero behavior change.** Acceptance criteria and the regression test `test_dispatch_under_limit_runs_all_without_blocking` pin this.
- Project rules: no `from __future__ import annotations`; `X | None`; immutable dataclasses where the codebase already is (note: `ListenerOptions` is `@dataclass(slots=True)` but **not** `frozen` today — match the existing struct, do not introduce frozen unilaterally).
- Design-completeness: docs page + frontend display ship in the same PR.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Policy enum | `src/hassette/types/enums.py` (new `BackpressurePolicy` StrEnum) | Low | Low — mirrors `ExecutionMode` |
| Options TypedDict | `src/hassette/bus/options.py` | Low | Low |
| Listener struct | `src/hassette/bus/listeners.py` (`ListenerOptions` field + `config_matches`/`diff_fields`) | Low | Med — must update both comparison methods or `if_exists="skip"` silently mismatches |
| Plumbing | `src/hassette/bus/bus.py` (`on`, `_on_internal`, and `**opts` flows through `on_state_change`/`on_attribute_change`/`on_call_service` automatically) | Low | Low |
| Dispatch enforcement | `src/hassette/core/bus_service.py:384-406` (the per-listener loop) | **High** | **High** — coalescing state + the acquire/release accounting are the crux |
| Drop counter | `execution_mode.py` or a new per-listener counter + `live_execution_counts` tuple widening | Med | Med — `(suppressed, dropped)` 2-tuple is consumed in 3+ places (`mappers.py`, `web/utils.py`) |
| Telemetry models | `core/telemetry_models.py`, `web/models.py` | Low | Low |
| Frontend | `frontend/src/components/app-detail/listener-detail.tsx`, regenerated types | Low | Low |
| Tests | `tests/unit/core/test_bus_dispatch_semaphore.py`, `tests/unit/bus/test_listeners.py` | Med | Med |
| Docs | `docs/pages/core-concepts/bus/` + a snippet | Low | Low |

### What already supports this

- **The option-plumbing rails are complete.** Adding a field to `Options` + `ListenerOptions` + `_on_internal` is a mechanical, well-precedented change. `ExecutionMode` is a working template down to tier-aware defaults.
- **The instrumentation pipeline already carries live, non-persisted per-listener counters end-to-end.** A drop count slots into the identical path with no new architecture.
- **`locked()` saturation detection is race-free at the exact enforcement point.** `DROP_NEWEST` is genuinely cheap: check `locked()`, if true increment a counter and `continue`.
- **`ExecutionModeGuard.pending` deque (cap-bounded, drop-on-overflow)** is a working precedent for bounded per-listener buffering, useful as a reference for KEEP_LATEST.

### What works against this

- **KEEP_LATEST does not fit the current control flow.** The dispatch loop is synchronous-until-acquire and stateless per listener across events. "Replace any pending event for this listener with the newest" requires *per-listener cross-event state* (a 1-slot mailbox) plus a *draining mechanism* that fires the latest pending event when a slot frees. Nothing in the dispatch loop holds cross-event per-listener state today; the guard's `pending` deque is per-listener but lives *inside* the spawned invocation, after the semaphore, not at the acquire gate. KEEP_LATEST is the hard 80% of this feature.
- **Coalescing semantics are ambiguous against duration/debounce/throttle.** A KEEP_LATEST listener that also has `debounce`, `duration`, or `mode=queued` composes two coalescing layers. The issue does not specify the interaction. (Inferred: KEEP_LATEST at the dispatch gate and debounce inside the invoker are orthogonal but stack confusingly.)
- **The 2-tuple `live_execution_counts` return is consumed in multiple places.** Widening to a 3-tuple or a small struct touches `mappers.py`, `web/utils.py`, and the scheduler-job enrichment path. A dataclass/NamedTuple is cleaner than a positional 3-tuple.
- **Per-listener semantics conflict with a global semaphore.** The semaphore is global; saturation is a system-wide condition, not per-listener. `DROP_NEWEST` for one listener drops based on a global signal — correct, but means "this listener drops when the *whole bus* is saturated," not "when this listener is overloaded." That is the intended meaning per the research, but worth stating plainly in docs to avoid user confusion with throttle/debounce (which *are* per-listener-rate).

## Options Evaluated

The caller is **Exploring** and explicitly invited alternative shapes. Three options below: the issue's prescribed enum (A), a reduced "do less" scope (B), and an alternative abstraction (C).

### Option A: Three-value `BackpressurePolicy` enum, enforced at the acquire gate

**How it works**: Add `BackpressurePolicy(StrEnum)` with `BLOCK`/`DROP_NEWEST`/`KEEP_LATEST`, mirroring `ExecutionMode`. Thread it through `Options` -> `ListenerOptions.backpressure` -> dispatch.

In the per-listener loop (`bus_service.py:384-406`), branch *before* the acquire:

- `BLOCK` (default): unchanged — `await self._dispatch_semaphore.acquire()` then spawn.
- `DROP_NEWEST`: `if self._dispatch_semaphore.locked(): listener.invoker.guard.bp_dropped += 1; log; continue` (no acquire, no spawn). Race-free per the no-await guarantee.
- `KEEP_LATEST`: maintain a per-listener 1-slot mailbox `{listener_id: (route, event)}` on `BusService`. When saturated, store/replace the latest event for that listener (counting a coalesced drop) instead of spawning. A drain step — triggered from `release_dispatch_slot` or a dedicated drain task — re-attempts dispatch of any mailboxed event when a slot frees. The drain must re-acquire and spawn, and must handle the listener being removed/cancelled meanwhile.

Drop counts live on the existing `ExecutionModeGuard` (or a sibling counter), surfaced through the existing `live_execution_counts` -> `ListenerWithSummary` -> frontend pipeline.

**Pros**:
- Matches the issue and the design research exactly; lowest spec-interpretation risk.
- `BLOCK` and `DROP_NEWEST` are small, low-risk, and independently shippable.
- Reuses the entire instrumentation pipeline and the `ExecutionMode` plumbing template.
- A `StrEnum` reads well in config/DB (`"block"`, `"drop_newest"`, `"keep_latest"`) and matches `mode`.

**Cons**:
- KEEP_LATEST introduces genuinely new cross-event per-listener state and a drain mechanism in the hottest path of the bus — the single highest-risk change in this feature.
- Drain correctness is subtle: re-entrancy with `release_dispatch_slot` (a done-callback running in loop context), listener removal between mailboxing and drain, and ordering against newly-arriving BLOCK listeners.
- Three policies x composition with debounce/throttle/duration/mode is a large test matrix.

**Effort estimate**: Medium for BLOCK+DROP_NEWEST; **Large** once KEEP_LATEST and its drain/instrumentation land. The issue's `size:medium` label is optimistic if KEEP_LATEST is in scope.

**Dependencies**: None new.

### Option B: Ship `BLOCK` + `DROP_NEWEST` now; defer `KEEP_LATEST` ("do less")

**How it works**: Same enum and plumbing as A, but the enum initially carries only `BLOCK` and `DROP_NEWEST`. `DROP_NEWEST` is a 5-line change at the acquire gate plus the drop counter. `KEEP_LATEST` becomes a follow-up issue once the mailbox/drain design is prototyped.

**Pros**:
- Delivers the high-value, low-risk slice immediately: noisy sensors stop contributing to backlog.
- Keeps the dispatch loop simple — no cross-event state, no drain task, no re-entrancy risk.
- The whole instrumentation + docs + frontend surface ships and is validated on the easy policy first, de-risking the KEEP_LATEST follow-up.
- Honors subtract-first / laziness: KEEP_LATEST is speculative complexity until a user demands coalescing over plain dropping.

**Cons**:
- Doesn't fully close #1076 as written; needs a tracking follow-up.
- KEEP_LATEST is arguably the more "interesting" policy for the metrics-aggregator use case in the research; shipping without it is a partial story.

**Effort estimate**: Small-to-Medium. This is the recommended first PR.

**Dependencies**: None.

### Option C: Bounded per-listener mailbox with a single `overflow` policy (alternative abstraction)

**How it works**: Instead of a flat three-value enum, give each listener an optional bounded mailbox of depth K with an overflow rule (`drop_newest` | `drop_oldest`). `BLOCK` = no mailbox (current behavior). `DROP_NEWEST` = mailbox depth 0. `KEEP_LATEST` = mailbox depth 1 with `drop_oldest`. This generalizes the three policies into two orthogonal knobs (depth + overflow rule), mirroring RxJava's `onBackpressureBuffer(capacity, strategy)` and the existing `ExecutionModeGuard.pending` deque (which is exactly a bounded mailbox with drop-newest-on-overflow).

**Pros**:
- One mechanism subsumes all three policies; KEEP_LATEST stops being a special case (it is "depth 1, drop oldest").
- Directly reuses the proven `pending`-deque pattern from `ExecutionModeGuard`.
- More expressive (depth 3 buffer is reachable) without more enum values.

**Cons**:
- More configuration surface than the issue asks for; risks violating laziness/experience-first ("say no to 1,000 options"). Depth > 1 has no demonstrated use case.
- Diverges from the issue's named policies, which are clearer to users than `(depth, overflow)` tuples.
- Still requires the same drain mechanism as KEEP_LATEST — it does not reduce the hard part, only renames it.
- A general buffer at the dispatch gate competes conceptually with `mode=queued`'s buffer inside the invoker; two bounded queues in the same path is a reader-load and reasoning hazard.

**Effort estimate**: Large. Same drain risk as A, plus a broader API.

**Dependencies**: None.

## Concerns

### Technical risks

- **KEEP_LATEST drain re-entrancy.** Draining from `release_dispatch_slot` (a `task.add_done_callback`) runs synchronously in loop context on task completion. Re-acquiring the semaphore and spawning from there must not deadlock or double-count `_dispatch_pending`. A separate drain task awaiting a "slot freed" event is safer but adds a moving part. (Inferred — needs a prototype.)
- **Listener lifecycle vs mailbox.** An event mailboxed for a listener that is then removed/cancelled (hot reload, `once` fired) must be discarded. The mailbox needs the same cancellation checks `_dispatch` already does (`listener.is_cancelled`).
- **`_dispatch_pending` / idle-event accounting.** Tests rely on `await_dispatch_idle`. A mailboxed-but-not-spawned event must not leave the idle event permanently cleared, or tests hang. Coalesced drops must not increment `_dispatch_pending`.
- **Tuple widening.** `live_execution_counts` returning a positional 3-tuple is a footgun across `mappers.py` and `web/utils.py`. Use a small `NamedTuple`/dataclass.

### Complexity risks

- KEEP_LATEST adds a new *concept* (per-listener coalescing mailbox) to the bus's mental model, on top of debounce, throttle, duration-hold, and four execution modes. Reader load in `bus_service.dispatch` — currently a single readable loop — rises sharply.
- Composition matrix (3 policies x {debounce, throttle, duration, 4 modes, once}) is large and mostly untested-by-default. Most combinations are nonsensical; the design should *forbid* the incoherent ones in `ListenerOptions.__post_init__` (precedent: it already rejects `debounce`+`throttle` and `once`+`debounce`).

### Maintenance risks

- Coalescing semantics, once shipped, are a compatibility contract. Getting KEEP_LATEST drain ordering wrong and fixing it later is a behavior change for anyone relying on it.
- Drop counts are live-only and reset on restart (matching `suppressed`/`dropped`). This is the right call (research FR#15), but users may expect historical drop totals; document the non-persistence explicitly.

## Open Questions

- [ ] **KEEP_LATEST drain trigger**: drive the drain from `release_dispatch_slot`, or a dedicated drain task gated on a "slot available" event? Needs a prototype to settle re-entrancy and accounting. (Searched the codebase: no existing slot-freed signal exists; `_dispatch_idle_event` is for full-drain, not single-slot.)
- [ ] **Composition rules**: should `KEEP_LATEST` + `debounce`/`duration`/`mode=queued` be forbidden in `__post_init__`, or defined? The issue is silent. Recommend forbidding the clearly-incoherent combos initially.
- [ ] **Drop-count granularity**: one counter for both DROP_NEWEST and KEEP_LATEST drops, or separate? The frontend already shows distinct "Suppressed"/"Dropped" cells; a third "Backpressure dropped" cell is consistent.
- [ ] **Scope of `KEEP_LATEST` for this PR**: in or deferred? (This is the central decision — see recommendation.)
- [ ] **DB persistence of the policy choice**: the `listeners` table persists `mode`, `debounce`, etc. Should `backpressure` be persisted as a config column too (migration), for the UI to show the configured policy even at zero drops? Likely yes, for parity with `mode`.

## Recommendation

**Ship Option B first** — the enum plus `BLOCK` and `DROP_NEWEST` — as one coherent PR with full instrumentation, docs, and frontend, then implement `KEEP_LATEST` as a fast follow-up (Option A's hard half) behind its own design pass. Confidence in this split: **Supported** (the dispatch loop, the acquire-gate enforcement point, and the instrumentation pipeline are all verified in source; the KEEP_LATEST drain has no existing precedent in the codebase and carries the only High-risk subtasks).

Rationale, grounded in the code:

1. `BLOCK` is already implemented (line 391) — Option B's `BLOCK` is "do nothing, just make it the named default."
2. `DROP_NEWEST` is a genuinely small, race-free change at lines 389-391 (`locked()` + counter + `continue`), reusing the full instrumentation pipeline. High value (noisy sensors stop adding backlog), low risk.
3. `KEEP_LATEST` is the only part that introduces new cross-event per-listener state and a drain mechanism in the bus's hottest path. It deserves its own prototype and challenge pass rather than riding in on a `size:medium` issue. Shipping B first validates the entire API/telemetry/docs surface so the KEEP_LATEST follow-up is purely the dispatch-mechanics problem.

Keep the **three-value `BackpressurePolicy` StrEnum** (Option A's shape), not the generalized `(depth, overflow)` of Option C — the named policies are clearer to users, match the issue, and Option C does not reduce the hard drain work it shares with A. If a future use case demands buffer depth > 1, revisit then (subtract-first).

Persist the configured `backpressure` policy as a `listeners` column for parity with `mode`; keep drop *counts* live-only (matching `suppressed`/`dropped`).

### Suggested next steps

1. Run `/mine-define` to spec the `BLOCK`+`DROP_NEWEST` PR: enum, plumbing through `_on_internal`, the acquire-gate branch, the drop counter on the guard, `live_execution_counts` returning a small struct (not a wider positional tuple), `ListenerWithSummary` field, frontend cell, a `listeners` migration for the config column, and forbidden-combination validation in `ListenerOptions.__post_init__`.
2. Add tests to `test_bus_dispatch_semaphore.py` mirroring the existing saturation harness: `DROP_NEWEST` skips under a locked semaphore and increments the counter; `BLOCK` still waits; under-limit behavior unchanged.
3. File a follow-up issue for `KEEP_LATEST` and **prototype the drain mechanism in a branch** before committing — settle the `release_dispatch_slot`-vs-drain-task question and the `_dispatch_pending`/idle accounting against the existing `await_dispatch_idle` test contract. Run `/mine-challenge` on the drain design before implementing.
4. Docs: add a "backpressure policy" section to the bus concept pages with a tested snippet, distinguishing dispatch-gate backpressure (system-wide saturation) from per-listener `throttle`/`debounce` (rate), per the issue's orthogonality note.

## Sources

- [Battle-Tested Patterns — Backpressure / Flow Control](https://totoro-jam.github.io/battle-tested-patterns/patterns/backpressure/)
- [Backpressure Patterns — Flow Control for Resilient Distributed Systems](https://codelit.io/blog/backpressure-flow-control)
- [Python asyncio Synchronization Primitives (Semaphore.locked / acquire)](https://docs.python.org/3/library/asyncio-sync.html)
- [CPython issue #97028 — should locked() return True with waiters queued?](https://github.com/python/cpython/issues/97028)
- [RxJava Backpressure (2.0) — onBackpressureDrop / onBackpressureLatest / onBackpressureBuffer](https://github.com/ReactiveX/RxJava/wiki/Backpressure-(2.0))
- [ReactiveX — Backpressure operators](https://reactivex.io/documentation/operators/backpressure.html)
- [Baeldung — Dealing with Backpressure with RxJava](https://www.baeldung.com/rxjava-backpressure)
