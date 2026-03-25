# Research Brief: BusService Dispatch Consolidation & Rate Limiter Ownership

**Date**: 2026-03-25
**Status**: Ready for Decision
**Proposal**: Consolidate BusService's two near-duplicate dispatch paths (`_dispatch_internal` and `_dispatch_tracked`) into a single flow, move rate limiter ownership from HandlerAdapter to Listener, and add throttle/debounce observability.
**Initiated by**: Follow-up to audit findings and challenge review of design/018-rate-limiter-ownership

## Context

### What prompted this

Three related GitHub issues (#427, #428, #429) target the same architectural seam: BusService orchestrates rate limiting but the RateLimiter lives on HandlerAdapter, creating a 3-layer reach-through (`listener.adapter.rate_limiter`) that appears 8 times across `bus_service.py`. A prior design doc (018) proposed moving the RateLimiter to Listener, but a challenge review found this was a "shallow fix" -- reducing dot-depth without actually encapsulating the concern. This research investigates the deeper restructuring.

### Current state

**Dispatch flow (event arrival to handler invocation):**

```
BusService.dispatch(topic, event)
  |
  +-- _expand_topics() -> [specific, domain.*, generic]
  |
  +-- Router.get_topic_listeners(route) -> [Listener, ...]
  |
  +-- listener.matches(event) -> predicate check
  |
  +-- task_bucket.spawn(_dispatch(route, event, listener))
        |
        +-- once guard: check/set listener._fired
        |
        +-- BRANCH on listener.db_id:
              |
              +-- db_id is None --> _dispatch_internal()
              |     |
              |     +-- read listener.adapter.rate_limiter
              |     +-- define safe_invoke() (try/except around listener.invoke())
              |     +-- rate_limiter.call(safe_invoke) OR safe_invoke()
              |     +-- if once: remove_listener()
              |
              +-- db_id is set --> _dispatch_tracked()
                    |
                    +-- read listener.adapter.rate_limiter
                    +-- define execute_fn() (builds InvokeHandler at call time, delegates to executor)
                    +-- rate_limiter.call(execute_fn) OR execute_fn()
                    +-- if once: remove_listener()
```

The two paths differ only in what the "invoke function" does:
- `_dispatch_internal`: wraps `listener.invoke()` in a try/except for error logging
- `_dispatch_tracked`: builds an `InvokeHandler` command and delegates to `CommandExecutor.execute()`

Both paths share identical rate limiter orchestration, once-listener cleanup, and rate_limiter access patterns.

**Rate limiter ownership chain:**
- `Listener.create()` passes `debounce`/`throttle` to `HandlerAdapter.__init__()`
- `HandlerAdapter.__init__()` constructs `RateLimiter` and stores it as `self.rate_limiter`
- `HandlerAdapter.call()` never invokes the rate limiter (comment explicitly says so)
- `BusService` accesses `listener.adapter.rate_limiter` at 8 sites across 4 methods

**SchedulerService comparison (lines 233-267 of scheduler_service.py):**
SchedulerService has an analogous dual path in `run_job()`: if `job.db_id is None`, run directly; otherwise build `ExecuteJob` command and delegate to executor. But it uses a simple inline if/else without separate methods, and has no rate limiting concern. This is the precedent for "db_id determines the dispatch strategy."

### Key constraints

- Debounce closures must capture the correct event at fire time, not registration time (the `execute_fn` closure in `_dispatch_tracked` reads `listener.db_id` lazily for this reason)
- `cancel()` is terminal on RateLimiter and must happen on listener removal
- `once=True` combined with rate limiting is already prohibited by validation in `Listener.create()`
- The project's coding style mandates immutability ("ALWAYS create new objects, NEVER mutate existing ones"), but Listener is already a mutable dataclass with `_fired`, `db_id`, and runtime state
- Scope should be a coherent architectural unit, not artificially reduced or expanded

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Dispatch consolidation | 1 file (`bus_service.py`) | Low | Low -- both paths are well-tested and the merge is mechanical |
| Rate limiter ownership move | 2 files (`listeners.py`, `bus_service.py`) | Low | Low -- straightforward field relocation |
| Rate limiter encapsulation (invoke-level) | 2 files (`listeners.py`, `bus_service.py`) | Medium | Medium -- changes the dispatch contract |
| HandlerAdapter simplification | 1 file (`listeners.py`) | Low | Low -- removal of unused fields |
| Observability (DEBUG logging) | 1 file (`rate_limiter.py`) | Low | Low -- additive change |
| Test updates | 3 files (`test_listeners.py`, `test_bus.py`, `test_registration.py`) | Medium | Low -- updating access paths and adding new test cases |

### What already supports this

1. **SchedulerService precedent**: `run_job()` already uses the "db_id determines strategy" pattern inline (lines 255-267), just without separate methods. This validates the consolidated approach.

2. **HandlerAdapter.call() already ignores rate limiting**: The docstring explicitly states "Rate limiting is orchestrated by BusService._dispatch, not here." Moving it out is completing a migration that was already started.

3. **Listener.create() already validates rate limiting**: All validation (mutual exclusion of debounce+throttle, positive values, once+rate_limiting prohibition) lives in `Listener.create()`. Moving construction there too is natural.

4. **Protocol usage**: The codebase uses `Protocol` types in multiple places (`_ListenerLike`, `TriggerProtocol`, `Predicate`, etc.), so adding a protocol or callback type for dispatch strategy would be idiomatic.

5. **Well-tested dispatch paths**: `test_bus.py` has thorough integration tests for both internal and tracked dispatch, including debounce coalescing and throttle dropping through the executor. These tests provide a strong safety net for refactoring.

### What works against this

1. **Mutable Listener dataclass**: Listener already has `_fired` (set during dispatch), `db_id` (set asynchronously after registration), and would gain `rate_limiter`. The immutability principle from the coding style is already violated. Adding more mutable state deepens this departure.

2. **Debounce timing constraint**: The `execute_fn` closure in `_dispatch_tracked` is designed so that `InvokeHandler` is built AFTER debounce fires, reading `db_id` at execution time. Any encapsulation of rate limiting into Listener must preserve this lazy-evaluation semantic, which means the Listener can't just wrap its own `invoke()` -- it needs to wrap whatever callable the dispatch path provides.

3. **Error handling asymmetry**: `_dispatch_internal` catches and logs exceptions from the handler. `_dispatch_tracked` delegates all error handling to `CommandExecutor._execute_handler()`. A consolidated path must preserve this asymmetry.

## Options Evaluated

### Option A: Consolidate dispatch + move rate limiter to Listener + encapsulate via `Listener.dispatch()`

**How it works**: Merge the two dispatch methods into one, where the only variable is the "invoke function." Rate limiter moves from HandlerAdapter to Listener. Listener gains a `dispatch(invoke_fn)` method that applies rate limiting around whatever callable is passed in.

```python
# In BusService._dispatch():
async def _dispatch(self, topic, event, listener):
    # once guard (unchanged)
    if listener.once and listener._fired:
        return
    if listener.once:
        listener._fired = True

    if listener.db_id is None:
        invoke_fn = self._make_internal_invoke(topic, event, listener)
    else:
        invoke_fn = self._make_tracked_invoke(topic, event, listener)

    try:
        await listener.dispatch(invoke_fn)
    finally:
        if listener.once:
            self.remove_listener(listener)

# In Listener:
async def dispatch(self, invoke_fn: Callable[[], Awaitable[None]]) -> None:
    if self._rate_limiter:
        await self._rate_limiter.call(invoke_fn)
    else:
        await invoke_fn()
```

BusService builds the invoke function (preserving the lazy `db_id` read for tracked dispatch and the try/except for internal dispatch), then hands it to `Listener.dispatch()` which applies rate limiting. BusService never touches the rate limiter directly except through `cancel()` on removal (which could also be encapsulated).

**Pros**:
- Eliminates all 8 `listener.adapter.rate_limiter` reach-throughs in one shot
- BusService no longer knows about RateLimiter at all (except cancellation)
- The dispatch contract becomes: "BusService builds the invoke function, Listener applies rate limiting"
- Debounce timing is preserved: `execute_fn` still builds `InvokeHandler` lazily
- Single dispatch path eliminates the near-duplicate code
- Matches SchedulerService's inline approach to the db_id branch

**Cons**:
- Changes the dispatch contract (Listener now has dispatch behavior, not just data + invoke)
- Adds a method to the Listener dataclass, moving it further from a pure data holder
- `cancel()` on removal still needs to reach through to `_rate_limiter` (or add a `cancel()` method to Listener)
- Slightly more complex than the shallow fix for reviewers unfamiliar with the motivation

**Effort estimate**: Medium -- the dispatch consolidation is straightforward, but testing the new contract thoroughly requires updating the integration tests in `test_bus.py`.

**Dependencies**: None -- all existing libraries and patterns suffice.

### Option B: Consolidate dispatch + move rate limiter to Listener (no encapsulation)

**How it works**: Same dispatch consolidation as Option A, but rate limiter moves to Listener as a direct field (the original design doc approach). BusService reads `listener.rate_limiter` instead of `listener.adapter.rate_limiter`. This is the "Finding 1, Option A" from the challenge review.

```python
# In BusService._dispatch() - still one method, but BusService still orchestrates rate limiting:
async def _dispatch(self, topic, event, listener):
    # once guard
    ...
    if listener.db_id is None:
        invoke_fn = self._make_internal_invoke(topic, event, listener)
    else:
        invoke_fn = self._make_tracked_invoke(topic, event, listener)

    try:
        if listener.rate_limiter:
            await listener.rate_limiter.call(invoke_fn)
        else:
            await invoke_fn()
    finally:
        if listener.once:
            self.remove_listener(listener)
```

**Pros**:
- Simpler than Option A -- less conceptual change
- Still eliminates the 3-layer reach-through (reduces to 1 layer)
- Still consolidates the two dispatch methods
- Rate limiter ownership is correctly placed (Listener, not HandlerAdapter)
- Easier to review and understand

**Cons**:
- BusService still orchestrates rate limiting (reads `listener.rate_limiter` at 3 sites: dispatch, remove_listener, remove_listeners_by_owner)
- Split-brain ownership remains: Listener owns the RateLimiter, BusService calls it
- Does not address Finding 1's concern about "coupling surface identical"

**Effort estimate**: Small -- dispatch consolidation plus a mechanical field move.

**Dependencies**: None.

### Option C: Rate limiter owned by BusService (dict keyed by listener_id)

**How it works**: Instead of rate limiter living on Listener or HandlerAdapter, BusService owns a `dict[int, RateLimiter]` keyed by listener_id. Co-locates the rate limiter with its only caller.

```python
class BusService(Service):
    _rate_limiters: dict[int, RateLimiter]

    def add_listener(self, listener):
        if debounce or throttle on listener:
            self._rate_limiters[listener.listener_id] = RateLimiter(...)
        ...

    async def _dispatch(self, topic, event, listener):
        rl = self._rate_limiters.get(listener.listener_id)
        ...
```

**Pros**:
- Co-locates data with its only consumer (BusService)
- Listener becomes a purer data object
- Clean lifecycle management (add on registration, remove on removal)

**Cons**:
- Rate limiter configuration (debounce/throttle values) still originates from `Listener.create()` -- BusService would need to receive these values somehow
- Breaks the `_register_then_add_route` flow which reads `listener.adapter.rate_limiter.debounce` for DB registration metadata (line 112-113 of bus_service.py)
- Adds state management to BusService (another dict to maintain, cleanup on removal)
- Unusual pattern -- no other component in the codebase separates configuration from its runtime state holder this way
- Makes testing harder -- rate limiter is no longer accessible through the Listener in tests

**Effort estimate**: Medium -- more invasive than Options A/B with less clear benefit.

**Dependencies**: None.

## Analysis of Specific Questions

### Q1: Dispatch path consolidation

Both `_dispatch_internal` and `_dispatch_tracked` follow the same structure:
1. Read rate limiter
2. Define an invoke function
3. Call rate_limiter.call(invoke_fn) or invoke_fn()
4. If once: remove_listener()

The only difference is the invoke function body. The cleanest consolidation is to extract the invoke function construction into separate helper methods and merge the dispatch logic:

```python
async def _dispatch(self, topic, event, listener):
    # once guard (unchanged)
    ...
    if listener.db_id is None:
        invoke_fn = self._make_internal_invoke_fn(topic, event, listener)
    else:
        invoke_fn = self._make_tracked_invoke_fn(topic, event, listener)

    try:
        # rate limiting + invocation (single path)
        ...
    finally:
        if listener.once:
            self.remove_listener(listener)
```

This works regardless of where rate limiting is orchestrated (Options A, B, or C).

### Q2: Rate limiter ownership

**Recommendation: Option A (Listener.dispatch() encapsulation).**

The key insight is that debounce requires the invoke function to be built by BusService (because `_dispatch_tracked` needs lazy `db_id` reading), but the rate limiter itself doesn't need to know anything about BusService. The `dispatch(invoke_fn)` pattern solves this cleanly: BusService builds the callable, Listener wraps it with rate limiting.

The `cancel()` lifecycle also fits naturally: add a `cancel()` method to Listener that delegates to `_rate_limiter.cancel()` if present. BusService calls `listener.cancel()` on removal instead of reaching through.

### Q3: HandlerAdapter fate

After moving rate limiting out, HandlerAdapter is:
```python
class HandlerAdapter:
    def __init__(self, handler_name, handler, signature, task_bucket):
        self.handler_name = handler_name
        self.handler = handler
        self.task_bucket = task_bucket
        self.injector = ParameterInjector(handler_name, signature)

    async def call(self, event, **kwargs):
        kwargs = self.injector.inject_parameters(event, **kwargs)
        await self.handler(**kwargs)
```

**Recommendation: Do NOT inline HandlerAdapter in this PR.** It still separates two concerns (DI parameter injection vs. handler invocation) and is imported in tests (`from hassette.bus.listeners import HandlerAdapter`). Inlining would merge DI into Listener, which is a separate design question about whether Listener should know about dependency injection. File as a follow-up issue.

### Q4: Listener mutability

Listener already violates the immutability principle with `_fired` (set during dispatch), `db_id` (set asynchronously post-registration), and now `_rate_limiter`. The challenge correctly identified this tension.

**Recommendation: Acknowledge but defer.** Splitting Listener into an immutable definition and a mutable runtime envelope (e.g., `ListenerState`) would be a significant refactor affecting every consumer. The pragmatic path is:
1. Make `_rate_limiter` private with a read-only property (as the challenge recommended)
2. Document the mutability contract in a docstring
3. File a follow-up issue for the definition/state split if the mutable surface continues to grow

This is not worth doing now because:
- The existing `_fired` and `db_id` mutations are well-understood and tested
- Adding `_rate_limiter` doesn't change the risk profile
- The split would touch every test that creates Listeners

### Q5: Observability

**Recommendation: Module-level logger with handler_name context (Finding 5, Option A).**

```python
class RateLimiter:
    def __init__(self, task_bucket, debounce=None, throttle=None, handler_name="unknown"):
        self._logger = getLogger(__name__)
        self._handler_name = handler_name
        ...

    async def _throttled_call(self, handler, *args, **kwargs):
        now = time.monotonic()
        if now - self._throttle_last_time < self.throttle:
            self._logger.debug("Throttle drop for handler=%s (window=%.1fs)", self._handler_name, self.throttle)
            return
        ...
```

This avoids circular references (Listener -> RateLimiter -> Listener's logger) and provides sufficient context for debugging. Counters should be deferred until a consumer exists (Finding 3).

## Concerns

### Technical risks

- **Debounce closure semantics**: The `execute_fn` in `_dispatch_tracked` deliberately reads `listener.db_id` at call time, not capture time. Option A's `Listener.dispatch(invoke_fn)` preserves this because it receives the callable and passes it through to the rate limiter, which calls it after the debounce delay. But any future refactoring that tries to simplify this (e.g., pre-binding the db_id) would break the contract. The lazy-read behavior needs a prominent docstring.

- **cancel() timing on removal**: `remove_listener()` and `remove_listeners_by_owner()` both call `cancel()` before the route removal task runs. If a dispatch is in-flight concurrently, the rate limiter could be cancelled while a debounced handler is about to fire. This is existing behavior and handled by the `_cancelled` guard in `RateLimiter.call()`, but it deserves a test.

### Complexity risks

- Adding `dispatch()` and `cancel()` methods to Listener moves it from "data holder with invoke()" to "data holder with dispatch behavior." This is a small conceptual shift but makes Listener a more active participant in the dispatch flow.

### Maintenance risks

- The `dispatch(invoke_fn)` pattern creates an implicit contract: BusService is responsible for building the invoke function, Listener for rate-limiting it. If a third dispatch strategy is ever needed, this contract must be understood by the implementer.

## Open Questions

- [ ] Should `Listener.cancel()` also set `_fired = True` as a guard against post-cancellation dispatch? Currently only `_cancelled` on the RateLimiter prevents this.
- [ ] The `_register_then_add_route` method reads `listener.adapter.rate_limiter.debounce` for DB registration metadata (lines 112-113). After the move, should `Listener` expose `debounce`/`throttle` as properties delegating to `_rate_limiter`, or should registration read them from the Listener's creation args directly?
- [ ] Should `Listener.dispatch()` also handle the once-listener cleanup (the `finally: if listener.once: self.remove_listener(listener)` block), or should that remain in BusService? Moving it into Listener would require Listener to know about BusService (for the remove call), which is a dependency inversion.

## Recommendation

**Pursue Option A (consolidate dispatch + move rate limiter + encapsulate via `Listener.dispatch()`)** as a single coherent PR addressing all three issues (#427, #428, #429).

This is the right scope because:
1. The three changes are interdependent -- moving rate limiter ownership without consolidating dispatch just shuffles the same code around
2. The dispatch consolidation is low-risk and well-tested
3. The encapsulation via `dispatch()` is the natural endpoint that the challenge review identified as the "deeper fix" (Finding 1, Option B)
4. Observability (DEBUG logging) is trivially additive and belongs in the same PR

**Do NOT include in this PR:**
- HandlerAdapter inlining (follow-up issue)
- Listener definition/state split (follow-up issue if mutable surface grows)
- Counters on RateLimiter (defer until a metrics consumer exists)

### Suggested next steps

1. **Update the design doc** (design/018) to reflect Option A's approach, incorporating the challenge findings. Use `/mine.design` to produce the updated design.
2. **Implement via TDD**: Start with a test for `Listener.dispatch()` behavior, then consolidate the dispatch paths, then add observability logging.
3. **File follow-up issues**: HandlerAdapter inlining, Listener mutability split, RateLimiter counters when metrics consumer exists.

## Sources

No external web research was performed -- all findings are grounded in the codebase.

## Appendix: File Inventory

### Files that would change

| File | Change type |
|------|------------|
| `src/hassette/bus/listeners.py` | Add `_rate_limiter` field + property, `dispatch()` method, `cancel()` method; remove debounce/throttle from HandlerAdapter |
| `src/hassette/core/bus_service.py` | Merge `_dispatch_internal`/`_dispatch_tracked` into one path; replace all `listener.adapter.rate_limiter` access; use `listener.dispatch()` |
| `src/hassette/bus/rate_limiter.py` | Add `handler_name` param, module logger, DEBUG logging for throttle drops and debounce resets |
| `tests/integration/test_listeners.py` | Update `listener.adapter.rate_limiter` to `listener.rate_limiter`; add tests for `Listener.dispatch()` |
| `tests/integration/test_bus.py` | Verify consolidated dispatch path (existing tests should largely pass as-is) |
| `tests/integration/test_registration.py` | Update mock listener construction (line 95: `listener.adapter.rate_limiter = None` -> `listener.rate_limiter = None`) |

### Files that should NOT change

| File | Reason |
|------|--------|
| `src/hassette/bus/bus.py` | Bus delegates to BusService; no rate limiter knowledge |
| `src/hassette/core/command_executor.py` | CommandExecutor receives commands; no rate limiter knowledge |
| `src/hassette/core/commands.py` | Frozen dataclasses; unchanged |
| `src/hassette/bus/injection.py` | DI is orthogonal to rate limiting |
