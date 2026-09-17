---
proposal: "Add await-style event consumption to hassette's Bus (wait_for) and Api (call_and_wait) for sequential automation logic"
date: 2026-09-17
status: Draft
flexibility: Exploring
motivation: "Real production friction — fire-and-forget call_service causes race conditions in sequential automations (TTS stepped on, stale-state matches, hand-rolled polling workarounds)"
constraints: "Must integrate with existing Bus listener system and Api service call infrastructure. Python 3.11+ async/await. Start narrow (wait_for + call_and_wait), note workflow/sequence abstractions as future direction only."
non-goals: "Designing a workflow engine, stream/async-iterator consumption (Tier 3 from prior art brief), expression-based triggers"
depth: deep
---

# Research Brief: Await-Style Event Consumption API

**Initiated by**: GitHub issue #528 — "Add wait_for() to Bus for await-style event consumption"

## Context

### What prompted this

A real homelab bedtime automation exposed the fire-and-forget gap. The automation's "TTS speak, 13 HA calls, play white noise" sequence completed in 14-20ms because every `call_service` returned immediately without waiting for the physical action to finish. Concrete failures:

1. **TTS stepped on by media play** — two `media_player` calls to the same entity landed near-simultaneously, with the second overwriting the first before it finished.
2. **Stale-state race** — a "LOTR done" watcher caught a *preceding* TTS's `idle` transition instead of the LOTR track's, because the watcher was armed after the call but the pre-existing `idle` state already matched.
3. **Hand-rolled polling** — the app author consolidated two instances of a snapshot-before-call, confirm-started poll, arm-idle-watcher, bounded-wait pattern into shared `_speak_and_wait` helpers. This pattern should be framework-provided.

The issue comment specifically flags the "two chained waits" problem: confirming an action *started* (state left its initial value) and then waiting for it to *end* (state returned to idle). A naive `wait_for(state==idle)` resolves instantly on the pre-existing state. HA's own `wait_for_trigger` docs warn about this same race.

### Current state

**Bus** (`src/hassette/bus/bus.py`) is the event dispatch engine. Registration methods (`on`, `on_state_change`, `on_attribute_change`, `on_call_service`) are async, return `Subscription` objects, and support filtering via predicates (`P`), conditions (`C`), and accessors (`A`). The `once=True` option on `ListenerOptions` already provides single-fire semantics with automatic cleanup — this is the primitive `wait_for` would build on.

**Api** (`src/hassette/api/api.py`) has a three-mode `call_service`: fire-and-forget (default, `ws_send_json`), `wait_for_ack=True` (awaits HA's WS-level acknowledgment that the command was processed), and `return_response=True` (awaits and returns the response body). Neither `wait_for_ack` nor `return_response` waits for the *downstream effect* (e.g., the light actually turning on) — they wait for HA's RPC envelope, not the domain event.

**WebsocketService.send_and_wait** (`websocket_service.py`) is the closest architectural precedent for a Future-based call-and-wait: it creates an `asyncio.Future`, registers it in `_response_futures` keyed by message ID *before* sending, then `await asyncio.wait_for(fut, timeout)` with `finally: pop(msg_id)` cleanup. This is the exact shape a Bus-level `wait_for` would follow.

**State reads are synchronous** — `self.states.get(entity_id)` reads the in-memory `StateProxy` cache. This matters because `wait_for` can cheaply check "is the desired state already current?" before blocking.

**No Future-bridge exists on the Bus today.** Events are dispatched to handler callbacks; there is no mechanism to deliver an event back to a caller via `asyncio.Future` or `asyncio.Queue`. The `pending_done` / `drain_pending_done` pattern in `execution_mode.py` is about handler-task completion, not event delivery.

**Prior art brief exists** — `design/research/2026-04-17-event-bus-api/research.md` (PR #531) is the canonical prior research. It ranks `wait_for` as Tier 2 / MEDIUM priority (item 4), citing Discord.py and Lahja as reference implementations. Issue #528 was one of five issues generated directly from that research.

### Key constraints

- **Python 3.11+ async/await** — the implementation is async-only; no sync facade equivalent is meaningful.
- **Must compose with existing Bus infrastructure** — predicates, conditions, `once=True`, listener lifecycle, app shutdown cleanup.
- **Mandatory timeout** — issue #528's acceptance criteria require this. Unbounded waits leak coroutines in long-running processes (flagged as an anti-pattern in the prior art brief).
- **`Api` and `Bus` are siblings** — both are children of `App`, with no cross-reference. `call_and_wait` needs both, which is a structural question: does it live on `Api` (requiring a `Bus` reference), on `App` (which already has both), or as a standalone composing function?
- **Naming collision** — `hassette.testing.wait_for` already exists as a polling-based test utility (`predicate, timeout, interval`). A new `Bus.wait_for` shares the name with different semantics.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| `Bus.wait_for()` | `bus/bus.py` (new method) | Low | Low — builds on `once=True` + existing pipeline |
| Future-cancellation on shutdown | `bus/bus.py` or `bus/listeners.py` | Low | Medium — new cleanup path needed |
| `call_and_wait` | `api/api.py` or `app/app.py` (new method) | Medium | Medium — cross-component coordination |
| Tests | 4-6 new test files across unit/integration | Medium | Low |
| Docs | `docs/pages/core-concepts/bus/methods.md`, `api/methods.md`, new snippets | Medium | Low |
| Frontend | None | N/A | N/A — no UI surface |

### What already supports this

1. **`once=True`** is a first-class `ListenerOptions` field with automatic cleanup. `HandlerInvoker.dispatch()` checks/sets a `fired` flag, and `BusService._dispatch()` removes the listener after firing. No new listener type needed.
2. **`WhereClause`** (predicates/conditions/accessors) composes identically for `wait_for` as for `on_state_change` — the filtering vocabulary is generic over all listener registrations.
3. **`send_and_wait`** on `WebsocketService` is the exact Future-bridge pattern: create future, register before action, await with timeout, cleanup in `finally`.
4. **`asyncio.wait_for(event.wait(), timeout)`** is the dominant async wait idiom across the codebase (6+ usage sites in `resources/`, `websocket_service`, `state_proxy`, etc.).
5. **Synchronous state reads** via `StateProxy` allow a "check-current-state-first" optimization that avoids unnecessary blocking when the desired state is already true.

### What works against this

1. **No future registry on Bus** — unlike `WebsocketService._response_futures`, there is no centralized tracking of pending `wait_for` futures. The shutdown path (`Bus.on_shutdown` -> `remove_all_listeners`) removes listeners but does not resolve or cancel associated futures. A `wait_for` future left unresolved on shutdown would hang the caller's coroutine.
2. **`Api` cannot reach `Bus`** — they are sibling resources under `App` with no cross-reference. `call_and_wait` needs both. Either `Api` gains a bus reference, or the composing method lives higher up.
3. **The TOCTOU race** — checking current state, then registering a listener, leaves a gap where the state could change between check and registration. The fix (register first, then check, per the Inngest article's double-check pattern) requires careful ordering.
4. **`guard_await` wrapping** — `Bus.on()` and all registration methods are wrapped in the forgotten-await detector (spec 071). `wait_for` returns a `Future`/`Coroutine`, not a `Subscription`, so it needs to either integrate with or bypass this guard.

## Options Evaluated

### Option A: `Bus.wait_for()` + `App.call_and_wait()`

**How it works**: Two new methods at two levels.

`Bus.wait_for(topic, *, where=None, timeout, name)` registers a `once=True` listener whose handler resolves an `asyncio.Future` with the matched event. Returns the event or raises `TimeoutError`. The implementation:

1. Creates an `asyncio.Future`.
2. Defines a handler closure that calls `future.set_result(event)`.
3. Calls `_on_internal(topic, handler=closure, once=True, where=where, name=name)` to register through the existing pipeline.
4. Wraps in `try: await asyncio.wait_for(future, timeout=timeout)` / `finally: subscription.cancel()`.

`App.call_and_wait(domain, service, *, wait_for_topic, wait_for_where, timeout, **service_data)` composes `self.bus.wait_for()` + `self.api.call_service()` atomically:

1. Arms `self.bus.wait_for(...)` *before* the service call (listener registered first).
2. Fires `self.api.call_service(...)`.
3. Awaits the `wait_for` future (the listener was already registered, so no race).
4. Returns the matched event.

```python
# App-author usage: wait_for on Bus
async def on_initialize(self):
    await self.api.call_service("light", "turn_on", entity_id="light.kitchen")
    event = await self.bus.wait_for(
        "state_changed",
        where=P.EntityId("light.kitchen") & P.StateTo("on"),
        timeout=5,
        name="kitchen_on_confirm",
    )
    # Now safe to proceed — light is confirmed on
    await self.api.call_service("light", "turn_on", entity_id="light.kitchen", brightness=255)

# App-author usage: call_and_wait on App
async def on_initialize(self):
    event = await self.call_and_wait(
        "light", "turn_on",
        entity_id="light.kitchen",
        wait_for_topic="state_changed",
        wait_for_where=P.EntityId("light.kitchen") & P.StateTo("on"),
        timeout=5,
    )
```

**Pros**:
- `Bus.wait_for()` is a pure bus primitive — no cross-component coupling.
- `call_and_wait` on `App` is natural because `App` already owns both `bus` and `api`.
- Builds entirely on existing `once=True` + `WhereClause` infrastructure. No new listener types.
- Follows `WebsocketService.send_and_wait`'s proven pattern.
- Power users can use `bus.wait_for()` alone for non-service-call waits (e.g., waiting for a sensor reading).

**Cons**:
- `call_and_wait` on `App` means adding to `_APP_PUBLIC_API` — App's surface grows.
- The `name=` requirement (inherited from Bus's `ListenerNameRequiredError`) adds friction for one-shot waits. Could be auto-generated with a default like `"_wait_for_{topic}_{counter}"`.
- Two parameters on `call_and_wait` (`wait_for_topic` + `wait_for_where`) feel verbose for the common case "call service, wait for the entity's state to change."

**Effort estimate**: Small — `bus.wait_for()` is ~40 lines; `call_and_wait` is ~20 lines of composition. Tests and docs are the bulk.

**Dependencies**: None — pure Python, existing infrastructure.

### Option B: `Bus.wait_for()` + convenience `Api.call_and_confirm()`

**How it works**: Same `Bus.wait_for()` as Option A. But instead of a generic `call_and_wait` on `App`, add a domain-specific `Api.call_and_confirm(domain, service, *, entity_id, target_state, timeout, **data)` that handles the most common case: "call a service targeting an entity, wait for that entity's state to reach a target value."

This requires `Api` to hold a reference to its sibling `Bus`. One way: `App.__init__` passes `bus=self.bus` to `Api` after both are created (or uses a deferred reference).

```python
# App-author usage: common case is dead simple
async def on_initialize(self):
    await self.api.call_and_confirm(
        "light", "turn_on",
        entity_id="light.kitchen",
        target_state="on",
        timeout=5,
    )
    # Kitchen light is confirmed on

# Power user: raw wait_for for anything else
event = await self.bus.wait_for(
    "state_changed",
    where=P.EntityId("media_player.living_room") & P.StateTo("idle"),
    timeout=30,
    name="media_idle",
)
```

**Pros**:
- The common case ("call service, confirm entity reached target state") is a one-liner with no predicate construction.
- `entity_id` and `target_state` are the two parameters users think in — they don't need to know about topics or predicates for the 80% case.
- `Api` is where users go for service calls, so `call_and_confirm` is discoverable.

**Cons**:
- Creates coupling: `Api` needs a `Bus` reference, which doesn't exist today and violates the current sibling-resource architecture.
- `call_and_confirm` is opinionated about what "confirm" means (`state == target_state`). For attribute changes, media player `idle` detection, or multi-step confirmations, users still need `bus.wait_for()`.
- Two methods with overlapping purpose (`call_and_confirm` vs. `bus.wait_for()` + manual `call_service`) — users must learn when each applies.
- The "stale state" problem (pre-existing `idle`) isn't solved by `target_state` alone; it needs the same snapshot-before-call pattern regardless.

**Effort estimate**: Medium — same `bus.wait_for()` plus wiring `Bus` into `Api`, plus the convenience method.

**Dependencies**: None.

### Option C: `Bus.wait_for()` only (no `call_and_wait` in v1)

**How it works**: Ship only `Bus.wait_for()`. Document the composition pattern for `call_service` + `wait_for` as a recipe in the docs. Defer `call_and_wait` / `call_and_confirm` until real usage reveals which convenience shape users need.

```python
# App-author usage: explicit composition
async def on_initialize(self):
    # Arm the listener BEFORE the call (critical for correctness)
    wait_task = asyncio.create_task(
        self.bus.wait_for(
            "state_changed",
            where=P.EntityId("light.kitchen") & P.StateTo("on"),
            timeout=5,
            name="kitchen_on_confirm",
        )
    )
    await self.api.call_service("light", "turn_on", entity_id="light.kitchen")
    event = await wait_task
```

**Pros**:
- Smallest possible scope. Ships one primitive that composes freely.
- No cross-component coupling (Bus stays independent of Api).
- Real usage patterns inform the convenience API shape instead of guessing.
- The composition pattern (arm-then-fire via `create_task`) is explicit and correct, and can be documented in a recipe.

**Cons**:
- The `create_task` + `await` pattern is easy to get wrong — arm *after* fire is a silent race condition that works most of the time (fast local bus) but fails under load or with slow state propagation.
- Every app author must independently discover and correctly implement the arm-before-fire pattern. This is the exact class of bug that prompted the issue.
- The bedtime-automation author already hand-rolled this pattern twice before consolidating — pushing the same pattern onto every user is not a framework-level solution.

**Effort estimate**: Small — `bus.wait_for()` only.

**Dependencies**: None.

## Concerns

### Technical risks

**Future cancellation on shutdown** is the one genuinely new mechanism. Today, `Bus.on_shutdown()` -> `remove_all_listeners()` calls `Listener.cancel()` on each listener, which sets `_cancelled` and marks the invoker as fired. But it does not resolve or cancel any associated `asyncio.Future`. A `wait_for` caller suspended on `await future` would hang. The implementation must either: (a) cancel the future in `Listener.cancel()` (requiring the listener to know about the future — new coupling), or (b) maintain a registry of pending `wait_for` futures on `Bus` that `on_shutdown` iterates and cancels (parallel to `WebsocketService._response_futures`). Option (b) is cleaner — it keeps `Listener` unmodified.

**The TOCTOU race** when checking current state before arming the listener. The Inngest article's solution (register the watcher first, then check current state, so any transition during the gap is captured by the already-registered watcher) applies directly. A `state_check_now=True` parameter (borrowed from pyscript's naming) could make this the default behavior for state-change waits.

**`guard_await` interaction** — Bus registration methods return `Coroutine[Any, Any, Subscription]` and are wrapped in the forgotten-await detector. `wait_for` returns `Event[Any]` (the matched event), not `Subscription`. It should bypass `guard_await` since its return type is already a natural await target — forgetting to await it would produce a runtime warning from Python's own coroutine-not-awaited machinery.

### Complexity risks

**The stale-state problem** is the hardest DX challenge. A `wait_for(state==idle)` that resolves instantly on pre-existing state is a correct but surprising behavior. Four approaches:

1. **`state_check_now=False` (default)**: Only match on *new* events arriving after registration. Avoids stale matches but misses the case where the desired state is already true (user must check manually first).
2. **`state_check_now=True` (default)**: Check current state immediately; if it matches, return without waiting. Handles "already true" but fails when the current state is a *stale* match (the media player `idle` problem).
3. **`since=` parameter**: Accept a timestamp or state snapshot; only match events newer than that reference. Solves the stale-match problem but adds API complexity.
4. **Document the pattern**: Teach users to snapshot state before the call, then wait for a *different* state, then wait for the target state. This is what the bedtime automation does.

The right default appears to be `state_check_now=False` — only match new transitions, not pre-existing state. This is what Discord.py does (only events arriving after the `wait_for` call), and it avoids the stale-match class of bugs. Users who want "already true or wait" can check `self.states.get()` before calling `wait_for`, which is explicit and correct.

### Maintenance risks

- `wait_for` is a permanent addition to the public API surface. Once shipped, it must be maintained through every Bus refactor.
- The `name=` requirement for telemetry tracking adds friction for one-shot waits. An auto-generated name for `wait_for` listeners (not user-specified) would reduce friction but sacrifice telemetry clarity. Consider making `name` optional on `wait_for` specifically, with a generated default.

## Open Questions

- [ ] **Should `name=` be optional on `wait_for`?** Every other Bus registration requires it for telemetry. One-shot waits are ephemeral and high-frequency — mandatory naming adds friction with questionable telemetry value. A counter-based default (`_wait_for_0`, `_wait_for_1`) might suffice.
- [ ] **Should `timeout` be truly mandatory, or just default to a generous value?** The issue says mandatory. But `timeout=None` meaning "wait forever" is the house style (`wait_ready`, etc.). A middle ground: mandatory with no default (forces the caller to think about it), but `None` is accepted and means "no timeout" for power users who genuinely want it.
- [ ] **Does `call_and_wait` belong in v1, or should it ship later?** The bedtime automation's friction is real, but `bus.wait_for()` alone plus documented composition may be sufficient for a first release. User feedback would reveal whether the convenience method is needed and what shape it should take.
- [ ] **Where does `call_and_wait` live if it ships?** `App` (no coupling, but App surface grows), `Api` (requires Bus reference, new coupling), or a standalone async function that accepts both (functional composition, no coupling, but unconventional for this codebase)?
- [ ] **How should the `wait_for` listener appear in telemetry?** It's a real listener with a DB row, but it's framework-managed, not user-managed. Should it use a special `source_tier` or `registration_source` to distinguish it from user-registered listeners in the monitoring UI?

## Recommendation

**Ship `Bus.wait_for()` first (Option A, bus half only). Defer `call_and_wait` to a follow-up issue.**

The core primitive — `await bus.wait_for(topic, where=, timeout=, name=)` — solves the fundamental gap: suspending a coroutine until a matching event arrives. It builds entirely on existing infrastructure (`once=True`, `WhereClause`, the `on()`/`_on_internal()` pipeline) and follows the proven `send_and_wait` pattern from `WebsocketService`.

The `call_and_wait` composition is valuable but involves a real architectural question (Api/Bus coupling) that should not block the primitive from shipping. Document the arm-before-fire composition pattern (`create_task` + `await`) as a recipe in the `wait_for` docs, and open a follow-up issue for `call_and_wait` once `wait_for` has real usage.

This is consistent with the prior art brief's ranking (Tier 2, MEDIUM) and the issue's own scope ("start narrow"). Discord.py ships `wait_for` without a `call_and_wait` equivalent and it is widely used.

**Key design decisions to lock in before implementation:**

1. **`state_check_now=False` as default** — only match events arriving after registration, not pre-existing state. Users check `self.states.get()` first if they want "already true or wait."
2. **`timeout` mandatory, `None` allowed** — force the caller to declare their timeout intent, but don't prohibit unbounded waits for power users.
3. **`name` optional with auto-generated default** — reduces friction for the ephemeral one-shot use case.
4. **Future registry on Bus for shutdown cleanup** — a `dict[int, asyncio.Future]` parallel to `WebsocketService._response_futures`, iterated and cancelled in `Bus.on_shutdown()`.

### Suggested next steps

1. Write a design doc via `/mine-define` — the codebase analysis is complete; the remaining decisions are API shape choices that benefit from the structured interview.
2. File a separate issue for `call_and_wait` / `call_and_confirm` as a future enhancement that composes on `wait_for`.
3. Consider whether the `hassette.testing.wait_for` naming collision needs resolution (rename the test utility, or accept the coexistence since they live in different namespaces).

## Future Direction

The prior art brief (Pattern 4) identifies three consumption tiers: `subscribe` (what `on_*` does today), `wait_for` (this issue), and `stream` (async iterator, Tier 3). A `stream()` method returning `AsyncIterator[Event]` would complete the triple and enable patterns like "process the next N sensor readings" with natural backpressure. This is worth noting but not designing now.

Beyond the triple, the bedtime automation's "snapshot-before-call, confirm-started, arm-done-watcher" pattern hints at a higher-level `Sequence` or `Step` abstraction — a builder that chains service calls and state confirmations with proper arm-before-fire ordering. This is the workflow engine the prompt explicitly defers, but it would compose cleanly on top of `wait_for` + `call_and_wait` once both exist.

## Sources

- [AppDaemon API Reference — listen_state, wait_state, oneshot](https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html)
- [Home Assistant wait_for_trigger documentation](https://www.home-assistant.io/docs/scripts/#wait-for-trigger)
- [Pyscript reference — task.wait_until, state_trigger, service calls](https://hacs-pyscript.readthedocs.io/en/latest/reference.html)
- [Node-RED HA Wait Until node](https://zachowj.github.io/node-red-contrib-home-assistant-websocket/node/wait-until.html)
- [What Python's asyncio primitives get wrong about shared state (Inngest)](https://www.inngest.com/blog/no-lost-updates-python-asyncio)
- [Discord.py wait_for examples](https://gist.github.com/Soheab/e73ab6f66881ee4102be37815da3a24e)
- [Lahja — Ethereum event bus with subscribe/stream/wait_for](https://github.com/ethereum/lahja)
- [HA race condition with wait_for_trigger (GitHub #160023)](https://github.com/home-assistant/core/issues/160023)
- [hassette prior art brief — design/research/2026-04-17-event-bus-api/research.md](https://github.com/NodeJSmith/hassette/blob/main/design/research/2026-04-17-event-bus-api/research.md)
