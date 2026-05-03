---
topic: "Internal event system design for async frameworks"
date: 2026-05-02
status: Draft
---

# Prior Art: Internal Event System Design

## The Problem

Every event-driven framework eventually needs its own internal event system — service lifecycle transitions, component readiness signals, configuration reloads, shutdown coordination. The design choices around how these events are shaped, named, emitted, dispatched, and consumed have compounding effects on debuggability, type safety, and architectural flexibility. Get them right early and the framework scales cleanly; get them wrong and you end up with a stringly-typed, tightly-coupled mess that's hard to extend.

The challenge is especially acute when the framework *also* processes external events (like Home Assistant state changes). Internal lifecycle events have fundamentally different delivery semantics — low-volume, must-deliver, "current state" matters — compared to high-volume, temporal, loss-tolerant domain events. Whether these share infrastructure is a key architectural decision.

## How We Do It Today

Hassette has 4 concrete internal event types as frozen dataclasses with factory classmethods (`HassetteServiceEvent`, `HassetteSimpleEvent`, `HassetteFileWatcherEvent`, `HassetteAppStateEvent`), all flowing through a single anyio `MemoryObjectStream` shared with HA events. Events are distinguished by `origin="HASSETTE"` and `hassette.event.*` topic prefixes in a `Topic` StrEnum. Emission goes through `Hassette.send_event()` — called from a `LifecycleMixin` that reaches up to the coordinator via a back-reference. Subscription is through per-owner `Bus` instances with convenience methods like `bus.on_hassette_service_failed()`. Internal events get no topic expansion (unlike HA state_changed which fans out to entity/domain/base topics). The `HassettePayload` base has an auto-generated `event_id` (uuid4) and hardcoded `origin`, but notably no timestamp — unlike `HassPayload` which carries `time_fired`.

## Patterns Found

### Pattern 1: String-Keyed Event Bus with Dict Dispatch

**Used by**: Home Assistant, blinker (Flask), pymitter, Django signals
**How it works**: Events are identified by string keys. The bus maintains a `dict[str, list[listener]]` mapping. When an event fires, all listeners for that key are invoked. Some implementations add a `MATCH_ALL` wildcard. Blinker uses `signal('name')` singletons so decoupled code can register on the same signal by name without imports. HA adds separate `async_fire_internal()` for internal use vs `async_fire()` for public API. Listeners return a removal callable for RAII-style cleanup.

**Strengths**: Maximum extensibility — any code can define new event types. Simple implementation. Decoupled registration. O(1) lookup.
**Weaknesses**: No compile-time type safety. Typos cause silent failures. Event data is typically `dict[str, Any]`. Refactoring requires grep.
**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/core.py

### Pattern 2: Class-Hierarchy Messages with Convention-Based Dispatch

**Used by**: Textual, Qt signals, wxPython
**How it works**: Each event type is a Python class inheriting from a base `Message`. Dispatch uses naming convention: `Button.Pressed` → `on_button_pressed()`. The framework introspects the class hierarchy to build handler names automatically. Messages carry typed data as class attributes. Textual's `MessagePump` processes an asyncio queue per widget. Messages "bubble" up the DOM tree with `stop()` and `prevent_default()` controls. The `@on(MessageClass)` decorator provides an alternative to naming conventions for ambiguous cases.

**Strengths**: Full type safety. IDE autocompletion works. Refactoring propagates through the type system. Hierarchical dispatch suits tree-structured models.
**Weaknesses**: Class-per-event proliferation. Convention-based dispatch is fragile with nested classes. Tight coupling between message names and handler names. Textual itself had to add `@on()` decorator to fix convention-dispatch edge cases.
**Example**: https://textual.textualize.io/guide/events/

### Pattern 3: State Machine with Typed Transitions and Hooks

**Used by**: Prefect, actix (Rust), Celery (partially)
**How it works**: Instead of arbitrary events, the system defines a finite state machine with typed states (enum or sealed class). Transitions *are* the events. Hooks attach to specific transitions: `on_completion`, `on_failure`, `on_cancellation`. Prefect separates state *types* (enum for logic) from state *names* (strings for display). Hook signatures receive full context: `(entity, run, state)`. Hooks run in the same process but outside the active execution context, providing isolation.

**Strengths**: Exhaustive — the type system enforces all transitions are handled. Clear lifecycle semantics. Self-documenting hook signatures. Enables pattern matching.
**Weaknesses**: Rigid — new states require updating all handlers. Only suits lifecycle transitions, not arbitrary events. Context isolation can surprise developers.
**Example**: https://docs.prefect.io/v3/concepts/states

### Pattern 4: Middleware Pipeline (Chain of Responsibility)

**Used by**: Dramatiq, FastAPI, Django, Express.js, ASGI
**How it works**: Every event passes through a chain of middleware classes with `before_X` / `after_X` hooks. Middleware can modify, filter, or short-circuit. Dramatiq's built-in middleware includes AgeLimit, TimeLimit, Callbacks, and Retries.

**Strengths**: Every middleware sees every event — ideal for cross-cutting concerns. Composable and orderable.
**Weaknesses**: Every middleware pays the cost of every event. Ordering dependencies are subtle. Too low-level for user-facing subscription.
**Example**: https://dramatiq.io/motivation.html

### Pattern 5: Typed Channels (Different Channel Types for Different Patterns)

**Used by**: Tokio (Rust), Go channels, Erlang/OTP mailboxes
**How it works**: Instead of one bus for all events, use different channel types for different communication patterns. Tokio provides: `mpsc` (command queue), `broadcast` (pub/sub — every receiver sees every message), `watch` (state notification — receivers see latest value only), and `oneshot` (request-reply). Each is generic over its message type.

The key insight: lifecycle signals ("service is ready") have different semantics than event streams ("light turned on"). A `watch` channel for lifecycle state means late subscribers always see current state. A `broadcast` channel for events means late subscribers only see new events. These are fundamentally different delivery guarantees.

**Strengths**: Each channel provides exactly the right semantics. Type safety inherent in generic parameter. Different backpressure per channel type.
**Weaknesses**: Requires upfront design of communication patterns. More complex API. Can lead to channel proliferation.
**Example**: https://tokio.rs/tokio/tutorial/channels

### Pattern 6: Actor Model with Typed Messages and Supervision

**Used by**: Actix (Rust), Erlang/OTP GenServer, Thespian (Python), Pykka (Python)
**How it works**: Each component is an actor with a mailbox. Messages are typed objects. Actors implement `Handler<M>` per message type. Lifecycle is explicit: started → running → stopping → stopped. OTP separates `call` (sync) from `cast` (async fire-and-forget) and `info` (system messages). Supervisors restart children per strategy (one_for_one, one_for_all, rest_for_one). Actix allows restoring from Stopping to Running.

**Strengths**: True isolation. Typed messages with typed responses. Built-in supervision. Clear sync/async separation.
**Weaknesses**: Python actor libraries are immature (Pykka lacks supervision, Thespian uses processes). Message-per-type proliferates. Debugging message flows is harder than direct calls.
**Example**: https://actix.rs/docs/actix/actor/

### Pattern 7: Pydantic/Model-Based Event Schemas with Auto-Documentation

**Used by**: FastStream, Faust, bubus
**How it works**: Events are Pydantic models. The framework uses type annotations for validation, serialization, and auto-generated documentation (AsyncAPI specs). FastStream's `@broker.subscriber` infers schema from handler type annotation. bubus adds event forwarding between buses with loop prevention and WAL persistence.

**Strengths**: Single source of truth for event shape. Auto-docs stay in sync. Serialization is free.
**Weaknesses**: Pydantic validation overhead for trusted internal events. Model changes need migration. Tight Pydantic version coupling.
**Example**: https://github.com/ag2ai/faststream

### Pattern 8: Signal Taxonomy with Lifecycle Phases

**Used by**: Celery, Django, Scrapy
**How it works**: The framework defines a comprehensive, fixed catalog of signals organized by lifecycle phase. Celery's taxonomy: task lifecycle (before_task_publish → task_prerun → task_started → task_success/failure → task_postrun → task_revoked), worker lifecycle (worker_init → worker_ready → worker_shutdown), and app lifecycle (setup_logging). Each signal is a module-level object. Handlers connect via `signal.connect(handler)`. The catalog is exhaustive, documented, and framework-controlled.

**Strengths**: Complete, discoverable lifecycle coverage. Phase-organized naming. Framework controls catalog, preventing proliferation.
**Weaknesses**: Users can't define custom signals (by design). New signals require framework releases. Signal catalog is a stable API surface.
**Example**: https://docs.celeryq.dev/en/stable/userguide/signals.html

## Anti-Patterns

- **Mixing internal and external events on a single channel**: Internal lifecycle events are low-volume, must-deliver, and need "current state" semantics (late subscribers should know current lifecycle state). External events are high-volume, temporal, and loss-tolerant. Mixing them means internal events get lost in noise or external processing blocks on lifecycle handling. ([event-driven.io](https://event-driven.io/en/internal_external_events/))

- **Stringly-typed events without a central catalog**: Bare strings as event identifiers lead to typo-driven bugs, impossible event discovery, and no type checker coverage. Every framework that starts with strings eventually adds an enum or class hierarchy. ([source](https://utkuapaydin.medium.com/event-driven-architecture-design-patterns-and-anti-patterns-from-the-trenches-92c411ede5a8))

- **Using events as RPCs**: Events should be notifications ("this happened"), not commands ("do this"). Imperative events create hidden coupling worse than direct function calls because it's invisible to the type system. ([source](https://codeopinion.com/beware-anti-patterns-in-event-driven-architecture/))

- **Ignoring handler failure isolation**: If handler exceptions propagate to the dispatch loop, one bad handler crashes the entire bus. pyee addresses this by auto-emitting exceptions as `error` events. Celery isolates signal handlers. ([pyee](https://pyee.readthedocs.io/en/latest/), [Celery](https://docs.celeryq.dev/en/stable/userguide/signals.html))

## Emerging Trends

- **Typed event catalogs as single source of truth**: TypeScript's typed EventEmitter maps, Rust's Message trait, and Python's Pydantic/dataclass models all point toward defining the complete event catalog as a type-level construct — enabling IDE support, compile-time checking, and auto-documentation.

- **Separation of lifecycle signals from domain events**: Celery's distinct signal categories, Tokio's differentiated channel types, and the event-driven.io guidance all converge on: lifecycle and domain events deserve different infrastructure.

- **Scoped buses with forwarding**: Rather than one global bus, frameworks use per-component buses with explicit forwarding rules (bubus with loop prevention, Textual's message bubbling). Preserves isolation with cross-cutting visibility when needed.

## Relevance to Us

**What hassette does well:**
- Frozen dataclasses for internal events are validated as the right performance choice (faster than Pydantic for trusted internal data)
- The `Topic` StrEnum avoids the worst of stringly-typed dispatch — events are centrally catalogued with type-checker coverage
- Explicit registration (`bus.on()`) is safer than convention-based dispatch (Textual learned this the hard way)
- The convenience method pattern (`on_hassette_service_failed()`) matches Prefect/Celery's hook naming and is discoverable

**What looks like it needs attention:**
1. **Single channel for internal + external events** — this matches anti-pattern #1 directly. The Tokio pattern (different channel types for different semantics) and Celery's signal separation both suggest splitting these. Internal lifecycle events need "current state" semantics that a shared `MemoryObjectStream` can't provide (late subscribers miss past events).

2. **No timestamp on internal events** — `HassettePayload` lacks `time_fired` while `HassPayload` has it. Every framework surveyed includes timestamps on lifecycle events. This matters for debugging, telemetry, and understanding event ordering.

3. **Emission via coordinator back-reference** — `LifecycleMixin` reaches up to `self.hassette.send_event()`. The OTP/actix pattern is to emit lifecycle events from the supervision infrastructure itself, not from the supervised component. Celery's signals are module-level objects that don't require a reference to a coordinator.

4. **No event forwarding between scoped buses** — per-app `Bus` instances are isolated, but there's no explicit forwarding mechanism. bubus's event forwarding with loop prevention suggests this could become a need as the framework grows.

5. **Missing lifecycle phases** — Celery's taxonomy has pre/post hooks for each phase (before_task_publish, task_prerun, task_postrun). Hassette's lifecycle events are status transitions but don't cover pre/post phases for operations like service start, app initialization, or WebSocket connection.

## Recommendation

Three changes worth investigating, in priority order:

1. **Separate internal lifecycle signals from the HA event stream.** This is the most impactful change. The Tokio "different channels for different patterns" model is the gold standard, but even Celery's simpler approach (separate signal objects for lifecycle vs. domain) would be a significant improvement. Internal signals should support "current state" queries (what's the service status right now?) in addition to "state changed" notifications.

2. **Add timestamps to internal events.** Small change, big debugging payoff. Every surveyed framework includes this.

3. **Consider a signal taxonomy organized by lifecycle phase.** Celery's approach — a documented, fixed catalog of signals organized as task/worker/app × pre/during/post — is the most mature pattern for framework lifecycle events. This would make hassette's internal event catalog exhaustive and discoverable, rather than growing ad-hoc as new events are needed.

Lower priority but worth noting: the emission pattern (mixin reaching up to coordinator) works today but will create coupling issues if hassette ever supports distributed or multi-process deployment. Module-level signal objects (blinker/Celery pattern) or a dedicated `LifecycleEmitter` service would decouple this.

## Sources

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/core.py — HA core event bus implementation
- https://github.com/ag2ai/faststream — FastStream async messaging with Pydantic event schemas
- https://github.com/browser-use/bubus — Production event bus with forwarding and WAL persistence
- https://github.com/riga/pymitter — Python EventEmitter with wildcards and TTL

### Documentation & standards
- https://developers.home-assistant.io/docs/integration_listen_events/ — HA event listener docs
- https://textual.textualize.io/guide/events/ — Textual message system guide
- https://textual.textualize.io/api/message/ — Textual Message API reference
- https://docs.prefect.io/v3/concepts/states — Prefect state types and transitions
- https://docs.prefect.io/v3/how-to-guides/workflows/state-change-hooks — Prefect lifecycle hooks
- https://docs.celeryq.dev/en/stable/userguide/signals.html — Celery signal taxonomy
- https://dramatiq.io/motivation.html — Dramatiq middleware lifecycle
- https://faust.readthedocs.io/en/latest/ — Faust stream processing with typed events
- https://blinker.readthedocs.io/en/latest/ — Blinker signal library
- https://pyee.readthedocs.io/en/latest/ — pyee Python EventEmitter
- https://actix.rs/docs/actix/actor/ — Actix actor lifecycle and typed messages
- https://tokio.rs/tokio/tutorial/channels — Tokio channel types
- https://pykka.org/ — Pykka Python actor library
- https://thespianpy.com/doc/in_depth — Thespian distributed actors
- https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/event — .NET event design guidelines

### Blog posts & writeups
- https://serokell.io/blog/elixir-otp-guide — Elixir OTP supervision and GenServer
- https://blog.makerx.com.au/a-type-safe-event-emitter-in-node-js/ — TypeScript typed EventEmitter
- https://basarat.gitbook.io/typescript/main-1/typed-event — TypeScript typed event per instance
- https://event-driven.io/en/internal_external_events/ — Internal vs external event separation
- https://utkuapaydin.medium.com/event-driven-architecture-design-patterns-and-anti-patterns-from-the-trenches-92c411ede5a8 — Event-driven anti-patterns
- https://textual.textualize.io/blog/2023/05/03/textual-0230-improves-message-handling/ — Textual message system evolution
- https://hrekov.com/blog/pydantic-vs-dataclasses-speed-comparison — Dataclass vs Pydantic performance
- https://amplitude.com/explore/data/event-taxonomy — Event taxonomy design principles
