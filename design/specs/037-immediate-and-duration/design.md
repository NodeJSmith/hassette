# Design: Immediate Bootstrap and State Duration

**Date:** 2026-04-20
**Status:** approved
**Issues:** #65, #66
**Research:** design/research/2026-04-20-state-duration-immediate-fire/research.md

## Problem

Automation handlers cannot distinguish transient state flickers from sustained conditions, and cannot self-bootstrap when the target condition is already true at registration time.

Without duration gating, a motion sensor that flickers on for 2 seconds triggers the same handler as one that has been continuously active for 10 minutes. Users must implement their own timer management to verify state stability — a pattern so common that every major home automation framework provides it natively.

Without immediate-fire, handlers registered during app startup miss conditions that were already true before registration. Users must manually check current state and invoke the handler themselves — error-prone, easy to forget, and a frequent source of "my automation didn't fire" bug reports.

## Goals

- Handlers can require sustained state before firing, preventing false positives from transient changes
- Handlers can bootstrap themselves at registration time when the target condition is already met
- Both features compose naturally with existing bus options (once, throttle, debounce for immediate; once for duration)
- The API surface remains minimal and consistent with existing option patterns
- Duration timers are restart-resilient via last_changed consultation when combined with immediate-fire

## Non-Goals

- Timer persistence across framework restarts (in-memory only — matches Home Assistant behavior)
- Duration support with glob/wildcard entity patterns (no deterministic entity to track)
- Replacing or deprecating existing debounce/throttle options

## User Scenarios

### App Developer: Automation Author

- **Goal:** Write handlers that respond only to meaningful, sustained state changes
- **Context:** During app development, defining event handlers in `on_initialize`

#### Motion-activated lighting with hold verification

1. **Registers handler with duration gate**
   - Sees: API accepts `duration=` parameter on `on_state_change`
   - Decides: How long motion must be sustained (e.g., 300 seconds)
   - Then: Framework acknowledges registration; no immediate action

2. **Motion sensor triggers**
   - Sees: Nothing visible — framework starts internal timer
   - Decides: N/A — framework manages timer automatically
   - Then: If motion stays active for full duration, handler fires with the original triggering event

3. **Motion sensor deactivates before duration elapses**
   - Sees: Nothing visible — framework cancels timer silently
   - Decides: N/A
   - Then: Handler never fires; no side effects

#### Startup bootstrap with immediate-fire

1. **Registers handler with immediate option**
   - Sees: API accepts `immediate=True` on `on_state_change`
   - Decides: Whether to opt into immediate evaluation
   - Then: Framework checks current entity state at registration time

2. **Condition already satisfied at registration**
   - Sees: Handler fires immediately with synthetic event (previous state = None, current state = actual)
   - Decides: N/A — handler logic runs normally
   - Then: Subsequent live state changes continue to trigger the handler as usual

3. **Condition not satisfied at registration**
   - Sees: Nothing — no immediate fire
   - Decides: N/A
   - Then: Handler waits for future state changes as normal

#### Combined: restart-resilient duration check

1. **Registers handler with both `immediate=True` and `duration=300`**
   - Sees: API accepts both options together
   - Decides: N/A
   - Then: Framework checks current state AND how long it's been held

2. **Entity already in target state for longer than duration**
   - Sees: Handler fires immediately — condition already satisfied
   - Decides: N/A
   - Then: Duration requirement was already met per `last_changed` timestamp

3. **Entity in target state but for less than duration**
   - Sees: Nothing immediately
   - Decides: N/A
   - Then: Framework schedules timer for remaining time (duration minus elapsed)

## Functional Requirements

1. A handler registered with `duration=N` (positive number, seconds) must fire only after the target entity has remained in the matching state continuously for N seconds
2. If the entity leaves the matching state before the duration elapses, the timer must be cancelled and the handler must not fire
3. If the entity leaves and re-enters the matching state, the timer must restart from zero
4. When the duration timer fires, the handler must receive the original triggering event (the event that started the timer), not a synthetic event
5. Before firing after duration elapses, the framework must re-verify that the entity is still in the matching state
6. A handler registered with `immediate=True` must evaluate the current entity state at registration time and fire the handler if predicates match
7. The immediate-fire event must have previous state set to None and current state set to the actual current state
8. If `immediate=True` and the entity does not exist or is unavailable, no error is raised and no handler fires
9. When both `immediate=True` and `duration=N` are specified on `on_state_change` and the entity is already in the matching state, the framework must consult the entity's last_changed timestamp to compute elapsed time. For `on_attribute_change`, restart-resilient elapsed-time computation is not supported — always start from zero elapsed time (known limitation: no reliable timestamp exists for attribute-level threshold crossings)
10. If elapsed time >= duration, the handler fires immediately
11. If elapsed time < duration, the framework schedules a timer for the remaining time (duration minus elapsed)
12. `duration` must not be combined with `debounce` or `throttle` (validation error)
13. `duration` may be combined with `once=True` — the handler fires at most once after the duration gate is satisfied
14. `immediate=True` must not be used with glob/wildcard entity patterns (validation error)
15. For `on_state_change` + duration: any change to the entity's state value resets the timer, regardless of whether the new state matches the predicate
16. For `on_attribute_change` + duration: the timer resets only when the predicate no longer matches (attribute changes that still satisfy the predicate do not reset)
17. Duration timers must be cancelled when the subscription is cancelled, with no resource leaks
18. The immediate-fire must pass through existing once/debounce/throttle guards (an immediate fire with `once=True` counts as the single invocation)

## Edge Cases

1. **Entity does not exist at registration with immediate=True** — no error, no fire, handler waits for future events
2. **State changes to same value (attribute-only update) during duration countdown for on_state_change** — does NOT reset the timer (only actual state value changes reset it)
3. **Rapid on/off/on flicker** — each "off" cancels timer, each "on" restarts from zero; handler fires only if final "on" holds for full duration
4. **Handler raises exception during duration-fire** — exception does not propagate to other listeners; error is captured by the existing execution tracking infrastructure
5. **Subscription cancelled while duration timer is pending** — timer is cancelled immediately, handler does not fire, no dangling tasks
6. **immediate + duration + once: entity already satisfies condition for longer than duration** — fires immediately, `once` flag consumed, no subsequent fires
7. **Multiple listeners on same entity with different durations** — each maintains independent timer state
8. **Entity becomes unavailable during duration countdown** — state change to "unavailable" triggers cancellation since it no longer matches the predicate
9. **last_changed is None or missing** — fall back to treating elapsed as 0 (start full duration timer)
10. **WebSocket disconnect during duration countdown** — StateProxy cache clears on disconnect; the DurationTimer callback re-reads state at fire time, gets None, and silently drops the fire. No false positive. The cancellation listener never fires (no events during disconnect), but the verification step produces the correct result.

## Acceptance Criteria

1. A handler with `duration=0.1` on a state change to "on" does not fire if the state returns to "off" within 0.05 seconds
2. A handler with `duration=0.1` fires after the entity holds "on" for at least 0.1 seconds, with the original triggering event
3. A handler with `immediate=True` fires at registration when the current state matches, with old_state=None
4. A handler with `immediate=True` does not fire at registration when the current state does not match
5. A handler with `immediate=True` and `duration=0.1` fires immediately when the entity has been in the target state for >0.1 seconds (per last_changed)
6. A handler with `immediate=True` and `duration=0.1` fires after remaining time when entity has been in target state for <0.1 seconds
7. Cancelling a subscription during a pending duration timer produces no handler invocation and no leaked tasks
8. `duration=5` combined with `debounce=1` raises a validation error at registration time
9. `immediate=True` on a glob entity pattern raises a validation error at registration time
10. Existing bus tests continue to pass with no regressions

## Dependencies and Assumptions

- Depends on `StateProxy` being populated before apps' `on_initialize` runs (guaranteed by Hassette's startup sequence: `on_running` syncs state before app lifecycle begins)
- Depends on Home Assistant providing `last_changed` in state objects (standard HA behavior since 0.1)
- Assumes `TaskBucket.spawn()` is available for timer task lifecycle management (existing infrastructure)
- Assumes `convert_datetime_str_to_system_tz()` correctly handles HA's ISO datetime format (existing utility, used elsewhere)

## Architecture

### Parameters and Listener extension

`immediate` and `duration` are **not** added to the shared `Options` TypedDict (which flows through `Bus.on()` to all event types). Instead, they are explicit named parameters on `on_state_change()` and `on_attribute_change()` only — the two methods that understand entity semantics.

Injection path: `on_state_change`/`on_attribute_change` extract `immediate` and `duration` from their parameter lists before calling `_subscribe`. These two values are passed as explicit optional parameters to `Listener.create()` directly (alongside existing params like `debounce`, `throttle`); `Bus.on()` and `_subscribe()` do not receive them.

Add to `Listener` dataclass (`src/hassette/bus/listeners.py`):
- `immediate: bool = False`
- `duration: float | None = None`
- `entity_id: str | None = None` — populated by `on_state_change`/`on_attribute_change` at registration time (avoids fragile topic-string parsing)

Validation in `Listener._validate_options()`:
- `duration` must be positive if provided
- `duration` + `debounce` → ValueError
- `duration` + `throttle` → ValueError
- (`once` + `duration` is explicitly allowed)
- `immediate` validation happens in `Bus.on_state_change()` / `Bus.on_attribute_change()`: reject if entity_id contains glob characters

### DurationTimer helper

New class in `src/hassette/bus/duration_timer.py`. Follows the `RateLimiter` pattern:
- Owns a single `asyncio.Task | None`
- `start(triggering_event, on_fire)` — cancels existing task, **re-creates the cancellation subscription** if it has been consumed or is None, then spawns new delayed task via `task_bucket.spawn()`. This ensures each timer cycle has an active cancellation path.
- `cancel()` — sets `self._cancelled = True` as the first operation (idempotency guard, mirroring `RateLimiter.cancel()`), cancels task, removes the cancellation listener from Router directly (synchronous, no `task_bucket.spawn()`), clears references
- `is_active` property for introspection
- Holds a reference to the cancellation `Subscription` for lifecycle chaining

Stored on `Listener` as `_duration_timer: DurationTimer | None` (non-init field, constructed in `Listener.create()` when `duration` is set). Cancelled in `Listener.cancel()` alongside `_rate_limiter`. `DurationTimer` must not import from `listeners.py` at runtime; use `TYPE_CHECKING` guard for any Listener type hints.

### Immediate-fire in BusService

Immediate-fire is spawned as a **separate task** (`task_bucket.spawn()`) after `_register_then_add_route()` completes route insertion and DB registration. This decouples the fire from registration, preventing serialization of N startup state reads.

The immediate-fire task:
1. If `listener.immediate` is False → no task spawned
2. Read current state from `StateProxy` via direct dict access (`state_proxy.states.get(entity_id)`) — lock-free, no retry, no exception path. Do NOT call `get_state()` which uses tenacity retries and raises `ResourceNotReadyError`.
3. If state is None (entity not found) → return silently; log at DEBUG
4. Construct synthetic `RawStateChangeEvent` with `old_state=None`, `new_state=current`, `time_fired=date_utils.now()` (returns `ZonedDateTime`), `context=HassContext(id=str(uuid4()), parent_id=None, user_id=None)`
5. For `on_attribute_change` listeners: `P.AttrDidChange` must treat `old_state=None` as a match (attribute present = considered changed for bootstrap purposes)
6. If `listener.duration` is set: compute elapsed time (see "Clock and elapsed-time computation" below); if elapsed >= duration → check and set `listener._fired` (once-guard), then dispatch immediately; else → start duration timer with remaining time
7. If no duration: run predicates against synthetic event; if match → dispatch via `_make_tracked_invoke_fn()`

The entire immediate-fire task is wrapped in `try/except Exception` — failures become "no bootstrap fire" (logged as WARNING) rather than silent registration crashes. Exception: `ResourceNotReadyError` (if somehow encountered) is logged at ERROR as a sequencing invariant violation — this indicates a startup ordering bug in the framework, not a missing entity.

If `changed=False` is specified (no state-change predicate added), the immediate-fire check fires for any entity that exists in StateProxy regardless of state value. This is the correct behavior — document and test explicitly.

### Clock and elapsed-time computation

For `immediate + duration` restart-resilient logic:
- `last_changed` is parsed via `convert_datetime_str_to_system_tz()` (from `hassette.events.hass`)
- `now` is `date_utils.now()` — returns `ZonedDateTime.now_in_system_tz()`, consistent with the rest of the codebase (same clock source as `App.now`)
- `elapsed` is clamped to `[0, duration]` — negative values (clock skew, NTP resync) become 0 (full timer restart); values ≥ duration fire immediately
- If `last_changed` is None or missing → elapsed = 0 (full timer restart)

For `on_attribute_change + immediate + duration`: restart-resilient elapsed-time computation is NOT supported. HA's `last_changed` reflects primary state changes, not attribute changes — there is no reliable timestamp for "when this attribute last crossed the threshold." Always start from zero elapsed time. This is a documented known limitation.

### Duration dispatch in BusService

In `BusService._dispatch()`, after `listener.matches(event)` passes:
- If `listener.duration is None` → proceed as today (delegate to `listener.dispatch(invoke_fn)`)
- If `listener.duration is not None` → start the duration timer with the current event and a callback that:
  1. Re-reads current state from `StateProxy` via direct dict access (in-memory, no HTTP)
  2. Re-evaluates predicates against current state
  3. If still matching → route through `listener.dispatch(invoke_fn)` which handles the once-guard atomically (check `_fired`, set `_fired`, invoke). This delegates once-guard responsibility to the existing audited code path.
  4. If not matching → silently drop (state reverted during timer window)

The `_dispatch()` `finally` block skips listener removal when `listener.duration is not None`. Instead, removal happens **unconditionally** (regardless of success or exception) inside the DurationTimer callback after `listener.dispatch()` returns — matching the non-duration `once` behavior. If the handler raises, the listener is still removed per the `once` contract.

### Duration cancellation

Both `on_state_change` and `on_attribute_change` use the **same cancellation model**: a separate internal framework-tier cancellation listener on the same entity that **re-evaluates predicates before cancelling**.

The cancellation listener fires on every `state_changed` event for that entity, but does NOT blindly cancel. Instead:
1. Re-evaluates the main listener's predicates against the new event
2. If predicates **still match** → do nothing (entity is still in the target state; timer continues)
3. If predicates **no longer match** → cancel the duration timer (entity left the target state)

This unified model correctly handles both listener types:
- `on_state_change`: cancels when the state value changes to a non-matching value (ignores attribute-only refreshes where state value is unchanged)
- `on_attribute_change`: cancels when the monitored attribute no longer satisfies the predicate (ignores unrelated attribute changes)

The cancellation listener:
- Uses `source_tier="framework"` (filtered from user-facing listener counts and telemetry)
- Bypasses DB registration (no telemetry row, no `ListenerRegistration`)
- Uses the **same `owner_id`** as the main listener (so `remove_listeners_by_owner()` cleans it up on app teardown; redundant with the teardown chain but safe since `Listener.cancel()` is idempotent via `_cancelled` guard)
- Its `Subscription` is stored on `DurationTimer`
- Teardown chain: `main_sub.cancel()` → `Listener.cancel()` → `DurationTimer.cancel()` → `cancel_sub.cancel()`
- `DurationTimer.cancel()` removes the cancellation listener from the Router directly (synchronous, no `task_bucket.spawn()`) to avoid shutdown-ordering dependency

### State reads — StateProxy, not HTTP

All state reads within `BusService` use `StateProxy` (in-memory, event-stream-backed cache). No HTTP calls to `Api.get_state_raw()` anywhere in the bus/dispatch path. This means:
- No network dependency in `_dispatch()` (remains I/O-free for the non-duration path)
- No network dependency in DurationTimer fire callback
- No serialization of startup immediate-fire checks
- `StateProxy` is guaranteed populated before apps' `on_initialize` runs (it syncs during Hassette's `on_running` phase, which completes before app lifecycle begins)

## Alternatives Considered

### Duration via explicit scheduler integration

Instead of embedding timer logic in the bus layer, users could compose `on_state_change` + `scheduler.run_in()` manually. Rejected because: (a) the cancellation lifecycle is error-prone to wire manually, (b) every automation framework that implements this finds it belongs at the subscription level, (c) the 4-line pattern is common enough that it's not "just a convenience" — it's a correctness feature (missed cancellations cause bugs).

### BehaviorSubject-style observable type for immediate

Instead of an `immediate` flag, make the bus topic itself hold current state (like RxJS BehaviorSubject). Rejected because: (a) hassette's bus is event-based, not state-based — events are discrete occurrences, not continuous values; (b) would require fundamental architecture changes; (c) the flag approach matches AppDaemon's proven API that users of home automation frameworks expect.

### Persistent duration timers (DB-backed)

Store timer state in the database to survive restarts. Rejected because: (a) adds complexity with minimal benefit — the `immediate + duration + last_changed` combo provides restart resilience without persistence; (b) matches Home Assistant's explicit design decision that `for:` timers don't survive restarts; (c) can be added later if demand exists without breaking the API.

## Test Strategy

Two new integration test files following TDD (RED → GREEN per test):

- `tests/integration/test_bus_immediate.py` — covers immediate-fire scenarios: match/no-match, entity-not-found, synthetic event structure, interaction with once/debounce/throttle, glob rejection
- `tests/integration/test_bus_duration.py` — covers duration scenarios: hold-and-fire, cancel-on-exit, reset-on-re-entry, double-check-before-fire, once+duration, immediate+duration combo, subscription cancellation, last_changed computation

Both use `AppTestHarness` with seeded state (existing test pattern). Duration tests use short real-time delays (0.05–0.1s) consistent with existing debounce tests in `test_bus.py`. **Important**: `await_dispatch_idle()` does not track duration timer tasks (they are spawned via `task_bucket.spawn()` outside the `_dispatch_pending` counter). Duration tests must use `asyncio.sleep(duration + margin)` instead of `await_dispatch_idle()` — this is the same pattern used by existing debounce tests.

Tests for `immediate + duration` must explicitly pass `last_changed` to `make_state_dict()` when seeding state; without it, the elapsed-time path always falls into the "None → elapsed=0" edge case.

Unit test for `DurationTimer` in isolation (start, cancel, is_active lifecycle).

## Documentation Updates

- Update `docs/` site bus reference to document `immediate` and `duration` parameters
- Add usage examples to `on_state_change()` and `on_attribute_change()` docstrings
- CLAUDE.md Architecture section: add duration mention to Bus description

## Impact

**Files modified:**
- `src/hassette/bus/bus.py` — `on_state_change`/`on_attribute_change` signatures (new `immediate`/`duration` params); validation
- `src/hassette/bus/listeners.py` — Listener fields (`immediate`, `duration`, `entity_id`), `create()`, `cancel()`, `_validate_options()`
- `src/hassette/core/bus_service.py` — `_register_then_add_route()` (immediate-fire task spawn), `_dispatch()` (duration timer start, once-guard skip in finally)
- `src/hassette/core/registration.py` — Add `immediate: bool = False` and `duration: float | None = None` as **optional fields with defaults** (appended after existing fields to preserve all 15+ existing construction sites without modification)
- `src/hassette/core/telemetry_repository.py` — DB migration for new `ListenerRegistration` columns

**Files created:**
- `src/hassette/bus/duration_timer.py` — DurationTimer helper class (holds timer task + cancellation subscription)
- `tests/integration/test_bus_immediate.py`
- `tests/integration/test_bus_duration.py`

**Blast radius:** Medium. Changes are additive to the bus layer. No existing behavior changes. The dispatch path gains a conditional branch but the default (no duration) follows the existing code path exactly. `Options` TypedDict is NOT modified — `immediate`/`duration` are method-specific parameters only.

**Known production limitation:** Duration timer tasks and immediate-fire tasks are not tracked by `_dispatch_pending`. Production monitoring via `dispatch_pending_count` will not reflect pending duration fires. `TaskBucket.shutdown()` cancels outstanding timer tasks (safe — handler never fires). A `duration_timer_pending_count` signal is a future enhancement if needed.

## Open Questions

None — all design decisions resolved during challenge review.
