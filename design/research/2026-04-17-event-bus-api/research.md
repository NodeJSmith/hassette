---
topic: "Event Bus API Design"
date: 2026-04-17
status: Draft
---

# Prior Art: Event Bus API Design

## The Problem

Home automation frameworks need an event bus that lets developers subscribe to device state changes, service calls, and system events with expressive filtering — without drowning in callback management or leaking memory in long-running processes. The API surface matters enormously: too simple and users write filtering logic in every handler; too complex and the learning curve kills adoption. The core tension is between expressiveness (complex predicates, composition, type safety) and ergonomics (readable one-liners for "when the kitchen light turns on").

Beyond patterns and plumbing, there's a more practical question: does the method surface match what users actually do? The top 10 HA automation patterns (motion-activated lighting, presence detection, time/sun triggers, door/window sensors, numeric thresholds, media player state, button events, notifications, energy management, appliance cycle detection) expose specific ergonomic gaps that pattern-level analysis alone doesn't reveal.

## How We Do It Today

Hassette's Bus uses method-call registration (`on_state_change`, `on_attribute_change`, `on_call_service`, etc.) with a three-layer filtering architecture: Accessors (`A`) extract values, Conditions (`C`) test them, and Predicates (`P`) compose tests. All methods return a `Subscription` object with `unsubscribe()`. Debounce and throttle are first-class parameters. Entity IDs support auto-glob patterns. No decorator syntax — all subscriptions are imperative.

**Where the current API maps well:**
- `on_state_change` is the workhorse — covers motion, presence, media player, door/window patterns. The `changed_to` accepting callables is more ergonomic than AppDaemon.
- Glob patterns for entity_id (`"light.*kitchen*"`) are a strong differentiator.
- P/C/A composition handles complex filtering that kwargs-based systems can't express.
- Built-in `debounce`/`throttle` prevents a class of "my automation fires too often" complaints.
- Dependency injection for handler signatures avoids AppDaemon's verbose 6-parameter callbacks.

## Patterns Found

### Pattern 1: State Hold Time / Duration Guard

**Used by**: Home Assistant (`for:`), AppDaemon (`duration=`), Node-RED ("For" parameter)

**How it works**: The subscription includes a duration parameter. The handler only fires if the entity remains in the matching state for the specified duration. In AppDaemon, `listen_state("binary_sensor.garage_door", new="on", duration=900)` fires only if the door has been open for 15 minutes continuously. If the state changes away and back during the duration window, the timer resets.

This is distinct from debounce (which delays the first callback to wait for settling) and throttle (which rate-limits). Duration guard means "fire only if the condition is still true after N seconds." It's the single most common missing abstraction in HA automation frameworks that lack it.

**Why it matters**: "Garage door open for 15 minutes", "no motion for 5 minutes", "temperature above threshold for 30 minutes" are among the top automation patterns. Without native support, users must manually combine bus subscription + scheduler timer + state re-check, which is error-prone (timer cancellation on state change back, re-entrance on rapid changes).

**Strengths**: Covers an extremely common physical-world pattern. Eliminates a whole class of timer-management bugs. Semantically clear — the subscription itself declares the hold requirement.

**Weaknesses**: Adds internal timer management complexity to the bus. The bus now needs access to the scheduler or its own timer mechanism. Edge cases around what "remains in state" means when attributes change but state doesn't.

**Example**: https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html

### Pattern 2: Threshold Crossing Semantics

**Used by**: Home Assistant (`numeric_state` trigger), OpenHAB (dedicated `ItemStateChangedEvent`)

**How it works**: HA's `numeric_state` trigger with `above: 25` fires only when the value *crosses* from below 25 to above 25 — not every time the sensor reports a value above 25. This "crossing" semantic prevents duplicate callbacks when a sensor fluctuates above a threshold (e.g., temperature bouncing between 25.1 and 25.3 doesn't re-fire).

Without crossing semantics, a `changed_to=lambda v: float(v) > 25` predicate fires on every sensor update where the value happens to be above 25, potentially dozens of times per hour for a frequently-updating sensor.

**Why it matters**: Temperature, humidity, battery level, power consumption, and illuminance thresholds are among the most common automation triggers. Without crossing semantics, users either get flooded with duplicate callbacks or must track previous state themselves.

**Strengths**: Eliminates duplicate firings for the most common numeric automation patterns. Matches user mental model ("notify me when it gets hot", not "notify me every time it's hot").

**Weaknesses**: Requires the bus to track previous values per subscription. "Crossing" needs clear definition: does unavailable→above count? Does startup count? What about non-numeric intermediary states?

**Example**: https://www.home-assistant.io/docs/automation/trigger/#numeric-state-trigger

### Pattern 3: Multi-Entity Subscription

**Used by**: Home Assistant (list of entity_ids in triggers), pyscript (multiple entities in `@state_trigger`)

**How it works**: HA YAML allows listing multiple entity_ids in a single state trigger — any matching entity fires the automation. Pyscript goes further: `@state_trigger("binary_sensor.motion_hall == 'on' or binary_sensor.motion_kitchen == 'on'")` auto-detects referenced entities and subscribes to all of them.

The "any" pattern (fire when any entity matches) is straightforward. The "all" pattern (fire when all entities are in a target state) is harder — it requires checking the current state of non-triggering entities when any one triggers.

**Why it matters**: "Any motion sensor detects motion" and "all persons are away" are top-10 automation patterns. Currently in Hassette, users must loop to register N separate listeners or rely on glob patterns (which require naming conventions). Presence-based automations are the #2 most common pattern and inherently multi-entity.

**Strengths**: Reduces boilerplate for the most common multi-entity pattern. A list of entity_ids is simple, explicit, and covers "any" well.

**Weaknesses**: The "all" pattern is inherently stateful and can't be fully solved at the subscription level — it always requires checking other entities' current state. Accepting lists adds complexity to entity matching (list + glob interaction).

**Example**: https://www.home-assistant.io/docs/automation/trigger/#state-trigger

### Pattern 4: Triple Consumption API (subscribe / stream / wait_for)

**Used by**: Lahja (Ethereum event bus), Discord.py, bubus, Broadway (Elixir)

**How it works**: The event bus offers three distinct ways to consume events, each optimized for different use cases:

1. **subscribe(event_type, handler)** — callback-based, fire-and-forget. Handler is called for every matching event. Returns a disposer/unsubscribe. Best for long-lived subscriptions. This is what hassette's `on_state_change` already does.

2. **stream(event_type)** — returns an async iterator. Enables `async for event in bus.stream(StateChanged):` loops. Best for processing sequences of events with natural backpressure (the consumer controls the pace by how fast it iterates).

3. **wait_for(event_type, check=predicate, timeout=seconds)** — one-shot await. Returns the first matching event or raises TimeoutError. Discord.py's `await bot.wait_for('message', check=lambda m: m.author == ctx.author, timeout=30)` is the cleanest example. Best for "wait until X happens" patterns.

Hassette currently only has pattern 1 (plus `once=True` for single-fire). The `wait_for` pattern would map naturally: `await bus.wait_for("state_changed", check=lambda e: e.entity_id == "light.kitchen" and e.new_state == "on", timeout=30)`. The `stream` pattern is less common in HA automations but useful for batch processing or sequential event chains.

**Strengths**: Each pattern is optimized for its use case. `wait_for` eliminates callback hell for sequential automation logic ("turn on light, wait for confirmation, then set brightness"). The stream pattern provides natural backpressure. All three coexist on the same bus.

**Weaknesses**: Three APIs means more surface area. `wait_for` can leak without timeout. The stream pattern requires lifecycle management (who closes the iterator?).

**Example**: https://gist.github.com/Soheab/e73ab6f66881ee4102be37815da3a24e (Discord.py wait_for), https://github.com/ethereum/lahja (Lahja triple API)

### Pattern 5: Expression-Based Triggers with Auto-Tracking

**Used by**: pyscript

**How it works**: Pyscript's `@state_trigger("sensor.temp > 25 and binary_sensor.window == 'off'")` automatically detects which state variables are referenced in the expression and subscribes to all of them. When any referenced entity changes, the full expression is re-evaluated. Combined with `@state_active` (a condition gate evaluated before the handler runs), this creates a declarative system that handles multi-entity and cross-entity patterns naturally.

**Why it matters**: This elegantly solves the hardest coordination problem — "when entity A changes AND entity B is in state X" — without requiring users to write the coordination logic. The auto-tracking means users just write the condition they care about, and the framework figures out what to subscribe to.

**Strengths**: Most natural API for complex conditions. No explicit subscription management. Multi-entity coordination is free. Reads like a human description of the desired behavior.

**Weaknesses**: Not directly applicable to method-call APIs (requires parsing expressions or using AST magic). Performance overhead of re-evaluating full expressions on every entity change. Debugging "why did this fire?" is opaque.

**Example**: https://hacs-pyscript.readthedocs.io/en/latest/reference.html

### Pattern 6: Kwargs-Based Declarative Filtering

**Used by**: AppDaemon, Home Assistant (partially)

**How it works**: Subscription calls accept keyword arguments that act as filters on event data. In AppDaemon, `listen_state("light.kitchen", attribute="brightness", old="off", new="on", duration=10)` subscribes to brightness changes, but only on off→on transitions, and only after the state has been stable for 10 seconds.

AppDaemon also supports `immediate=True` (fire on registration if current state matches) and `oneshot=True` for single-fire listeners.

**Strengths**: Extremely readable and discoverable. Filters are co-located with the subscription.

**Weaknesses**: No type safety — typos in kwarg names are silently ignored (caused HABApp's breaking v1.0 migration). Complex predicates don't fit the kwargs model. AppDaemon's `old` value behavior is confusing when `attribute=` is used.

**Example**: https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html

### Pattern 7: Structured Filter Objects

**Used by**: HABApp (v1.0+), OpenHAB (EventFilter interface)

**How it works**: Subscriptions require explicit filter objects instead of kwargs. HABApp v1.0 made this a breaking change — `listen_event()` now requires an `EventFilter` instance. Items are first-class objects with `.listen_event()` directly on the item.

**Strengths**: Type-safe, composable, testable. IDE autocomplete works.

**Weaknesses**: More verbose than kwargs for simple cases. Can feel over-engineered for common patterns.

**Example**: https://habapp.readthedocs.io/en/v1.0.4/interface_openhab.html

### Pattern 8: Reaction Split — Separate "What to Watch" from "What to Do"

**Used by**: MobX (`reaction`), Vue (`watch`), SolidJS (`createEffect` with explicit deps)

**How it works**: MobX's `reaction(dataFn, effectFn, options)` separates the tracking function from the side-effect function. The `dataFn` selects what to watch and returns the watched data. The `effectFn` receives the result and runs the side effect. The effect only fires when the data function's *return value* changes, not when any accessed observable changes.

```javascript
reaction(
    () => room.temperature,           // what to watch (returns a value)
    (temp) => adjustThermostat(temp),  // what to do (receives the value)
    { delay: 5000, fireImmediately: true }
)
```

Options include `delay` (built-in debounce), `fireImmediately` (run on subscription), `equals` (custom comparison to avoid spurious updates), and `onError` (per-reaction error handling).

MobX's `when(predicateFn)` returns a promise when no effect is given: `await when(() => room.temperature > 25)`. This is the reactive equivalent of `wait_for`.

**Why this matters for hassette**: The current API conflates "what to watch" and "what to do" — the entity_id + predicates define what to watch, and the handler is what to do, but they're all parameters to the same method call. The reaction split makes each concern independently testable and composable. A predicate that checks "temperature crossed above 25" is reusable across different handlers.

**Strengths**: Clean separation of concerns. Data function is independently testable. Built-in debounce, immediate-fire, custom equality, and per-reaction error handling as options rather than separate mechanisms. The `when` + promise form is the most ergonomic `wait_for` variant found.

**Weaknesses**: Two functions per subscription is more verbose than one. Auto-tracking in Python requires explicit descriptors (no property interception). The data function runs on every change to determine if the effect should run, which can be expensive.

**Example**: https://mobx.js.org/reactions.html

### Pattern 9: Event Recording for Test Assertions

**Used by**: AWS IATK (EventBridge), Broadway (Elixir), Cosmic Python, hassette (HassetteHarness partially)

**How it works**: Three complementary sub-patterns:

1. **Test listener** (AWS IATK): A dedicated `TestBusListener` captures events during tests. `poll_events()` retrieves captured events. `wait_until_event_matched(assertion_fn, timeout)` polls until a match or timeout. Listeners are tagged for cleanup.

2. **Test injection** (Broadway): `test_message(ref)` injects a single message and returns a ref for asserting on acknowledgment: `assert_receive {:ack, ^ref, [success], []}`. Tests verify processing without real producers.

3. **Domain event recording** (Cosmic Python): Domain objects collect events in a `.events` list. Tests assert on recorded events rather than mocking handlers — testing "what happened" without coupling to "how it was handled."

**Why this matters for hassette**: HassetteHarness already records some bus activity, but purpose-built test utilities for the bus (like `wait_until_event_matched` with timeout) would improve the testing story. The "test the events, not the handlers" principle from Cosmic Python is particularly relevant — it prevents brittle handler-mock tests.

**Strengths**: Each sub-pattern addresses a different testing need. Event recording is implementation-agnostic. Test injection verifies processing without real event sources. Purpose-built test utilities ship with the bus rather than relying on generic mocking.

**Weaknesses**: Time-dependent tests (debounce, throttle, `for_duration`) need clock manipulation regardless. Event recording requires discipline in what gets recorded.

**Example**: https://awslabs.github.io/aws-iatk/tutorial/examples/eb_testing/ (AWS IATK), https://www.cosmicpython.com/book/chapter_08_events_and_message_bus.html (Cosmic Python)

## Anti-Patterns

- **Silent kwargs typos**: Misspelled filter keys silently match everything instead of nothing. HABApp's v1.0 breaking migration was directly motivated by this. Hassette avoids it with explicit method parameters. ([source](https://habapp.readthedocs.io/en/v1.0.4/interface_openhab.html))

- **Leaked listeners**: Long-running systems accumulate handlers when subscriptions are never removed. Hassette handles this via automatic cleanup on app shutdown. ([source](https://www.techyourchance.com/event-bus/))

- **Verbose callback signatures**: AppDaemon's `def callback(self, entity, attribute, old, new, kwargs)` — 6 parameters for every callback, most ignored. Community complaint. Hassette's dependency injection avoids this. ([source](https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html))

- **Duplicate firings on numeric thresholds**: Without crossing semantics, subscriptions with `changed_to=lambda v: float(v) > 25` fire on every sensor update where the value is above 25. Both AppDaemon and current Hassette have this problem. ([source](https://community.home-assistant.io/t/logic-to-automation-crossing-a-numeric-state-threshold/654610))

- **Event cascade chains**: Components that both subscribe and publish can create infinite loops. bubus addresses this with `event_path` tracking. ([source](https://www.techyourchance.com/event-bus/))

- **Unbounded event queues**: Async frameworks default to accepting unlimited work and buffering silently until OOM. A sensor polling at 1Hz can generate events faster than a slow handler processes them. The fix must be architectural (bounded queues, demand-driven flow, or load shedding), not tactical. ([source](https://lucumr.pocoo.org/2020/1/1/async-pressure/))

- **Testing handlers instead of events**: Testing "handler X was called with args Y" is fragile and couples tests to implementation. Better to test that the right events were recorded/produced — verifies behavior without depending on dispatch mechanics. ([source](https://www.cosmicpython.com/book/chapter_08_events_and_message_bus.html))

## Emerging Trends

- **Expression-based triggers replacing imperative subscriptions**: Pyscript's auto-tracking approach. Not directly applicable to Hassette's method-call API, but the concept of "evaluate a condition involving multiple entities whenever any of them change" could inform a future `on_condition()` or `when()` method.

- **Pydantic-based event models**: bubus and similar libraries use Pydantic as the event base class, getting validation, serialization, and type safety for free.

- **Bus composition over global bus**: Multiple scoped buses with explicit forwarding rules. Aligns with Hassette's per-app Bus architecture.

- **Event bus testing as first-class concern**: Broadway's `test_message`, AWS IATK's `add_listener/poll_events`, and Cosmic Python's event-recording pattern all treat bus testing as a design concern, not an afterthought. Purpose-built test utilities shipping with the bus rather than relying on generic mocking.

- **Context propagation for automation tracing**: OpenTelemetry's W3C TraceContext becoming standard for tracing causality through event chains. For HA: "show me the full chain from motion sensor trigger → automation fired → light turned on." Hassette's telemetry system could propagate trace context through bus events.

## The State/Attribute Split

**Verdict: Keep it.**

In HA's data model, every entity has one `state` value (a string) and a dict of `attributes`. These change independently. An entity might have its state unchanged while attributes update frequently (e.g., a climate entity stays "heating" while `current_temperature` changes every minute).

In practice, users overwhelmingly care about the primary state value (80%+ of automations). Attribute monitoring is less common but important for: battery levels, brightness values, temperature readings as attributes, HVAC current temp.

AppDaemon unifies them (`listen_state` with `attribute=`) but this muddies semantics — the `old`/`new` behavior changes when `attribute=` is used, causing confusion. Hassette's split is cleaner. Optionally adding `attribute=` to `on_state_change` as a convenience alias (delegating to `on_attribute_change`) could bridge the gap for users who think of it as "the same thing with a parameter."

## Relevance to Us

### What Hassette already does well (validated by prior art)

1. **P/C/A composition system** is ahead of all comparables. AppDaemon uses kwargs (no type safety), HABApp moved to structured filters (similar direction), but neither has the three-layer split. Genuine differentiator.
2. **Explicit method signatures** avoid the silent-kwarg-typo anti-pattern that caused HABApp's breaking v1.0 migration.
3. **Debounce/throttle as first-class parameters** — more precise than AppDaemon's single `duration` parameter.
4. **Dependency injection for handlers** — eliminates the 6-parameter callback complaint that's common in AppDaemon forums.
5. **Auto-glob on entity_id** — covers the common "any" multi-entity pattern for well-named entities.
6. **Per-app Bus scoping** — aligns with the bus-composition trend and avoids the "false coupling" anti-pattern.

### Gaps to address (ranked by user impact)

1. **State hold time (`for_duration=`)** — HIGH priority. "Has been in state X for N seconds" is top-5 in frequency. HA YAML has `for:`, AppDaemon has `duration=`. Hassette has nothing equivalent. Users currently must combine bus + scheduler + state re-check. This is the most impactful missing feature.

2. **Threshold crossing semantics** — HIGH priority. Without `C.CrossedAbove(25)` / `C.CrossedBelow(10)` (or an `on_numeric_state` method), numeric threshold subscriptions fire on every sensor update where the value is above the threshold, not just when it crosses. This is the #5 most common automation pattern.

3. **Multi-entity subscription** — MEDIUM priority. Accepting a list of entity_ids in `on_state_change` would cover the common "any of these" pattern. Glob patterns handle it when entities share naming conventions, but explicit lists are needed for "all persons" patterns. The "all" pattern is inherently stateful and better served by documentation + examples.

4. **Expect/await** — MEDIUM priority. `bus.expect(event_type, predicate, timeout)` for "call a service, wait for state confirmation." Valuable but less common than the patterns above.

5. **State guard / cross-entity conditions** — LOW priority (future). A predicate that checks current state of *other* entities (not just the triggering event) would address cross-entity patterns. Inspired by pyscript's `@state_active`. Could be a `state_guard=` parameter or a predicate like `P.CurrentState("sensor.temp", C.GreaterThan(20))`.

## Recommendation

The current method surface (`on_state_change`, `on_attribute_change`, `on_call_service`, `on`) is the right decomposition. The state/attribute split is correct. The convenience lifecycle methods are cheap and improve discoverability. P/C/A composition is ahead of all comparables found.

### Tier 1 — High-impact ergonomic gaps (address these first)

1. **`for_duration=` parameter on `on_state_change`** — "fire only if the entity has been in this state for N seconds." Semantically distinct from `debounce` (which delays the callback) — this means "check that the condition is still true after the duration." Covers the garage-door, motion-timeout, and appliance-cycle patterns. This is the single highest-impact addition. HA YAML has `for:`, AppDaemon has `duration=`, Node-RED has "For". Every comparable offers this.

2. **`C.CrossedAbove(threshold)` / `C.CrossedBelow(threshold)` conditions** — fire only on the transition from below→above or above→below. Can be used with existing `on_state_change` via `changed_to=C.CrossedAbove(25)`. Requires the condition to see both old and new values, which means it might work better as a predicate than a condition. Covers temperature, humidity, battery, power threshold patterns. Without this, users get duplicate firings on every sensor update — a known complaint in both AppDaemon and HA community forums.

3. **Accept `list[str]` for entity_id in `on_state_change`** — `on_state_change(["person.jessica", "person.alex"], ...)` registers a listener for any of them. Simple, explicit, no new methods needed. Covers presence detection without requiring naming conventions. HA YAML already supports this.

### Tier 2 — New consumption patterns (expand what the bus can do)

4. **`wait_for(event_type, check=, timeout=)`** — one-shot await, returns the first matching event. Discord.py and Lahja both implement this cleanly. Covers "call service, wait for state confirmation" and sequential automation logic. More useful than the broader `expect()` from bubus because it's simpler and maps directly to asyncio patterns.

5. **`immediate=True` on `on_state_change`** — fire handler once on registration if current state already matches. Already on the issue tracker. AppDaemon has this. Low complexity, high ergonomic value.

### Tier 3 — Worth studying, not urgent

6. **Event stream / async iterator** — `async for event in bus.stream(StateChanged):` for processing event sequences with natural backpressure. Less common in HA automations but valuable for data-processing patterns (energy monitoring, sensor aggregation). From Lahja's triple API.

7. **State guard / cross-entity conditions** — a predicate that checks current state of *other* entities (not just the triggering event). Inspired by pyscript's `@state_active` and MobX's `reaction(dataFn, effectFn)` split. Could be a `state_guard=` parameter or a predicate like `P.CurrentState("sensor.temp", C.GreaterThan(20))`. Addresses the hardest multi-entity pattern ("when A changes AND B is in state X").

8. **Bus test utilities** — purpose-built `TestBusListener` with `wait_until_event_matched(assertion_fn, timeout)`, inspired by AWS IATK. HassetteHarness partially covers this but dedicated test helpers would improve the testing story. The "test events, not handlers" principle from Cosmic Python is worth adopting.

## Sources

### Reference implementations
- https://github.com/browser-use/bubus — Pydantic event bus with expect/await and bus composition
- https://habapp.readthedocs.io/en/v1.0.4/interface_openhab.html — HABApp: structured EventFilter, items as objects
- https://blinker.readthedocs.io/en/stable/ — Blinker signal library with weakref support
- https://pyee.readthedocs.io/en/latest/ — Python EventEmitter with async support
- https://hacs-pyscript.readthedocs.io/en/latest/reference.html — Pyscript: expression-based triggers with auto-tracking

### Blog posts & writeups
- https://www.thecandidstartup.org/2025/10/20/home-assistant-concurrency-model.html — Deep dive on HA's event concurrency model
- https://www.techyourchance.com/event-bus/ — Event bus pros, cons, and anti-patterns
- https://quantlane.com/blog/aiopubsub/ — aiopubsub with key-based wildcard filtering

### Documentation & standards
- https://developers.home-assistant.io/docs/asyncio_thread_safety/ — HA core event helpers and async safety
- https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html — AppDaemon listen_state/listen_event API
- https://zachowj.github.io/node-red-contrib-home-assistant-websocket/node/events-state.html — Node-RED HA events:state node
- https://www.openhab.org/docs/developer/utils/events.html — OpenHAB event bus architecture
- https://www.home-assistant.io/docs/automation/trigger/ — HA automation triggers (numeric_state, state, template)

### Reactive patterns & event bus design
- https://mobx.js.org/reactions.html — MobX reactions: reaction/autorun/when with disposers and delay
- https://dev.to/ryansolid/a-hands-on-introduction-to-fine-grained-reactivity-3ndf — SolidJS signals and auto-tracking
- https://github.com/day8/re-frame/blob/master/docs/Interceptors.md — re-frame data-oriented interceptor chains
- https://lucumr.pocoo.org/2020/1/1/async-pressure/ — Ronacher on async backpressure (unbounded queue anti-pattern)
- https://github.com/ethereum/lahja — Lahja: subscribe/stream/wait_for triple API
- https://gist.github.com/Soheab/e73ab6f66881ee4102be37815da3a24e — Discord.py wait_for examples

### Testing & observability
- https://awslabs.github.io/aws-iatk/tutorial/examples/eb_testing/ — AWS IATK: test listeners for event bus
- https://www.cosmicpython.com/book/chapter_08_events_and_message_bus.html — Cosmic Python: event recording, test events not handlers
- https://hexdocs.pm/broadway/Broadway.html — Broadway: test_message injection and demand-driven backpressure
- https://opentelemetry.io/docs/concepts/context-propagation/ — OpenTelemetry context propagation for event tracing
- https://eventsourcing.readthedocs.io/ — Python eventsourcing: event replay and time-travel debugging

### MQTT & IoT patterns
- https://www.hivemq.com/blog/mqtt-essentials-part-5-mqtt-topics-best-practices/ — MQTT hierarchical topic wildcards
- https://docs.emqx.com/en/emqx/latest/messaging/mqtt-wildcard-subscription.html — MQTT 5.0 shared subscriptions

### Community discussions (automation patterns & pain points)
- https://community.home-assistant.io/t/what-is-your-most-useful-automation/648543 — Top automation patterns
- https://community.home-assistant.io/t/pyscript-vs-appdaemon-vs-yaml/481286 — Framework comparison
- https://community.home-assistant.io/t/ha-automation-in-python-from-a-developers-pov/530291 — Developer POV on HA automation
- https://community.home-assistant.io/t/what-is-the-future-of-appdaemon/666610 — AppDaemon sustainability concerns
- https://community.home-assistant.io/t/logic-to-automation-crossing-a-numeric-state-threshold/654610 — Threshold crossing confusion
- https://community.home-assistant.io/t/how-are-you-automation-notifying-on-groups-of-entities-when-one-changes/849947 — Multi-entity patterns
