---
topic: "State duration and immediate-fire patterns in reactive/home-automation systems"
date: 2026-04-20
status: Draft
---

# Prior Art: State Duration and Immediate-Fire Patterns

## The Problem

Home automation handlers need two common capabilities that pure event streams don't provide natively: (1) firing only after a state has been *stable* for N seconds (e.g., "motion detected for 5 minutes"), and (2) firing immediately upon registration if the condition is already true (the "bootstrap problem"). Without duration, users get false positives from transient states. Without immediate-fire, users must manually check current state after subscribing — error-prone and a frequent source of missed-trigger bugs at app startup.

## How We Do It Today

Hassette's bus has `debounce` (waits N seconds after *last* matching event) and `throttle` (rate-limits), but neither is "duration" (verify state held continuously). There is no `immediate` option — users must manually call `api.get_state()` after registration and invoke the handler themselves. The predicate system is synchronous and per-event; no timer lifecycle management exists in the bus layer.

## Patterns Found

### Pattern 1: Declarative Duration on State Trigger (Hold-For)

**Used by**: Home Assistant (`for:`), AppDaemon (`duration=`), Node-RED (stateFor node)

**How it works**: User declares a duration alongside a state trigger. When the entity enters the target state, an internal timer starts. If the entity leaves before the timer expires, the timer is cancelled. Only if held for the full duration does the handler fire. The timer is in-memory only.

HA syntax: `for: "00:05:00"` on a state trigger. AppDaemon: `self.listen_state(cb, "entity", new="on", duration=300)`.

**Strengths**: Simple, declarative, covers the 90% case. Users don't manage timer lifecycle. Intent is clear from the registration call.

**Weaknesses**: Does not survive restarts (HA explicitly documents this). Precision depends on implementation (AppDaemon had 1-second granularity issues due to polling). Wildcard listeners with duration produce unpredictable results. "What counts as a state change that resets the timer" must be clearly defined (attribute changes? same-value updates?).

**Example**: https://www.home-assistant.io/docs/automation/trigger/

### Pattern 2: Immediate-Fire on Registration (Check-Current-State)

**Used by**: AppDaemon (`immediate=True`), MobX (`fireImmediately: true`), MobX `autorun` (always immediate)

**How it works**: At registration time, the system evaluates current state against filter criteria. If already satisfied, handler fires immediately. Combined with duration, the countdown starts from registration time (or from `last_changed` in smarter implementations).

AppDaemon: `self.listen_state(cb, "light.kitchen", new="on", immediate=True)`. MobX: `reaction(() => data, effect, { fireImmediately: true })`.

**Strengths**: Eliminates the startup race condition. Makes handlers idempotent to registration timing. Essential for app boot scenarios.

**Weaknesses**: `old` state is undefined/None on immediate fire (AppDaemon documents this explicitly). Can cause surprising double-fires. Interacts complexly with duration — naive implementations don't subtract already-elapsed time (AppDaemon #2186).

**Example**: https://appdaemon.readthedocs.io/en/stable/AD_API_REFERENCE.html

### Pattern 3: Replay-Current-Value via Observable Type (BehaviorSubject)

**Used by**: RxJS (BehaviorSubject), Kotlin Flow (StateFlow), SwiftUI (@Published), Angular services

**How it works**: Rather than a flag on subscription, the observable *type itself* always holds a current value. New subscribers automatically receive it. "Fire immediately" is the default — you opt out by using a plain Subject.

```typescript
const state$ = new BehaviorSubject<string>("off");
state$.subscribe(val => console.log(val)); // immediately prints "off"
```

**Strengths**: No flag needed — type system communicates the contract. Composable with operators. No special-case logic in subscription path.

**Weaknesses**: Requires initial value at construction. Every subscriber gets replay even if unwanted. Conflates "current state" with "event stream." Not directly applicable to hassette's event-bus model (events are discrete occurrences, not continuous state holders).

**Example**: https://rxjs.dev/api/index/class/BehaviorSubject

### Pattern 4: Guaranteed-First-Execution Slot (handle_continue)

**Used by**: Elixir/OTP GenServer (`handle_continue/2`), some actor frameworks

**How it works**: After init, provides a guaranteed execution slot that runs before any external messages. Eliminates the self-messaging race (where real state changes arrive before the "check current state" message).

```elixir
def init(args), do: {:ok, state, {:continue, :post_init}}
def handle_continue(:post_init, state), do: # runs before any cast/call
```

**Strengths**: Eliminates race by design. Clear intent. Non-blocking to supervisor.

**Weaknesses**: Only solves "first time" — not general "fire on every subscription." Requires framework-level support.

**Relevance**: When hassette fires `immediate`, it must not race with other initialization. Since BusService registration is already `await`-ed during `on_initialize`, and immediate-fire happens inline after route addition, this race is naturally avoided — but only if immediate-fire is synchronous relative to the registration `await`.

**Example**: https://elixirschool.com/blog/til-genserver-handle-continue

### Pattern 5: Explicit Timer Entity (Persistent Duration)

**Used by**: Home Assistant Timer integration, custom helpers

**How it works**: Timer is a first-class entity with start/pause/cancel/finish lifecycle. Automation listens for timer.finished event rather than using `for:` on the trigger. Timer state survives restarts.

**Strengths**: Survives restarts. Full lifecycle control. Observable in UI. Shareable.

**Weaknesses**: More boilerplate (two automations instead of one). Timer must be declared separately. Harder to reason about at a glance.

**Example**: https://www.home-assistant.io/integrations/timer/

## Anti-Patterns

- **Duration timer not cancelled on state exit**: AppDaemon shipped this bug (#457). Every state change away from target MUST cancel the timer. Seems obvious but requires explicit wiring — it's the #1 footgun.

- **Ignoring elapsed time on restart/re-registration**: Both HA and AppDaemon restart timers from zero after restart, even if entity has been in target state for hours. Fix: consult `last_changed` and compute remaining time. (AppDaemon #2186, HA #92017)

- **Immediate-fire with wildcard listeners**: AppDaemon warns results are "unpredictable." Checking all entities at registration time can fire hundreds of callbacks simultaneously. Validate: immediate requires exact entity_id.

- **Self-messaging for immediate execution**: Creates a race window where real events arrive before the immediate-check message. Solved by making immediate-fire synchronous relative to registration (inline, not deferred).

## Emerging Trends

**Smart duration via `last_changed`**: Multiple projects are moving toward `remaining = duration - (now - last_changed)`. Makes duration restart-resilient without persistence. This is the clear best practice for `immediate=True` + `duration=` combo.

**Type-level "has current value" distinction**: RxJS BehaviorSubject vs Subject, Kotlin StateFlow vs SharedFlow. Eliminates need for flags by making replay intrinsic to the type. Not directly applicable to hassette's event-bus model, but worth noting as the direction reactive frameworks are moving.

## Relevance to Us

Our plan aligns well with Pattern 1 (declarative duration) and Pattern 2 (immediate flag). Key insights to incorporate:

1. **`last_changed` consultation** (from AppDaemon #2186): When `immediate=True` + `duration=N`, don't start from zero — compute `remaining = duration - (now - last_changed)`. If already elapsed, fire immediately. This is a clear improvement over our current plan's Step 11.

2. **Timer cancellation must be rock-solid** (from AppDaemon #457): Our plan uses a cancellation subscription (Approach A). This is correct, but the cancellation predicate must fire on ANY state change for that entity, not just "predicate doesn't match" — otherwise attribute-only changes could create gaps.

3. **Glob + immediate = ValueError** (from AppDaemon docs): Our plan already has this. Confirmed as industry best practice.

4. **Race-free immediate-fire** (from Elixir handle_continue): Our plan fires immediately inline after route addition within the same `await`. This naturally avoids the race — no self-messaging needed. Good.

5. **Same-value state updates**: Must decide whether `state_changed` events where `new == old` (attribute-only changes) reset the duration timer. HA says no (only state changes reset). Our plan should be explicit about this.

6. **Attribute-change duration semantics**: For `on_attribute_change` + duration, what resets the timer? Any attribute change? Only changes that don't match the predicate? This needs a design decision not in the current plan.

## Recommendation

Our plan is solid and aligns with established patterns. Three concrete improvements to incorporate:

1. **Add `last_changed` subtraction for `immediate + duration` combo** — when both are set and entity is already in target state, compute remaining duration from `last_changed` rather than starting fresh. This is the clear industry best practice emerging from AppDaemon #2186.

2. **Define "what resets the timer" explicitly** — attribute-only changes (where entity state string is unchanged) should NOT reset the duration timer for `on_state_change`. For `on_attribute_change` + duration, only changes that cause the predicate to no longer match should reset it.

3. **Consider making cancellation fire on any state update** (not just predicate-non-match) — simpler to reason about and matches HA's behavior. A state update where `new == old` (attribute-only) would not trigger the cancellation for `on_state_change` since the topic is `state_changed` and these events still have the same entity state.

## Sources

### Reference implementations
- https://appdaemon.readthedocs.io/en/stable/AD_API_REFERENCE.html — AppDaemon listen_state with duration and immediate
- https://www.home-assistant.io/docs/automation/trigger/ — HA state trigger with `for:` option
- https://www.home-assistant.io/integrations/timer/ — HA explicit timer entity
- https://rxjs.dev/api/index/class/BehaviorSubject — RxJS replay-on-subscribe pattern
- https://mobx.js.org/reactions.html — MobX reaction fireImmediately

### Bug reports & design discussions
- https://github.com/AppDaemon/appdaemon/issues/2186 — last_changed not consulted for immediate+duration
- https://github.com/AppDaemon/appdaemon/issues/457 — duration timer not cancelled on state exit
- https://github.com/AppDaemon/appdaemon/issues/249 — duration fires early due to polling granularity
- https://github.com/home-assistant/core/issues/92017 — state-for trigger fails after restart
- https://github.com/mobxjs/mobx/issues/1006 — reactions within reactions ordering

### Blog posts & community
- https://elixirschool.com/blog/til-genserver-handle-continue — guaranteed post-init execution
- https://community.home-assistant.io/t/understanding-the-for-time-based-condition/143986 — trigger-for vs condition-for confusion
- https://community.home-assistant.io/t/using-timer-vs-state-with-duration-in-a-trigger/696218 — timer entity vs for: tradeoffs
