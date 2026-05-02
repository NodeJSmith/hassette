---
topic: "inter-app communication and dependency patterns in automation frameworks"
date: 2026-05-02
status: Draft
---

# Prior Art: Inter-App Communication and Dependency Patterns

## The Problem

Automation frameworks divide logic into isolated units (apps, flows, automations, rules). But real systems have cross-cutting concerns: one automation's output triggers another, apps need to coordinate startup order, shared state must flow between isolated units without creating tight coupling. The design question: how much inter-app communication should a framework support, and through what mechanisms — direct calls, shared state, event bus, or explicit dependency declarations?

Too little communication infrastructure and users build brittle workarounds (global state, polling). Too much and isolation breaks down, making apps hard to reason about and test independently.

## How We Do It Today

Hassette apps communicate through three mechanisms (all informal):

1. **Event Bus (primary)**: All apps share a centralized `BusService`. One app can fire custom events (`self.send_event("topic", data)`) that another app listens to (`self.bus.on(topic="topic", handler=...)`). Also: `self.bus.on_app_running(app_key="other_app", handler=...)` for lifecycle events.

2. **Shared State (HA entities)**: All apps see the same `StateProxy` cache. One app can set an HA entity that another app watches. This is implicit coordination via Home Assistant state.

3. **Direct Reference (escape hatch)**: `self.hassette.get_app("other_app", index=0)` returns another app instance. This works but is undocumented and creates tight coupling.

No explicit inter-app dependency system exists. No startup ordering between apps. No typed contracts for inter-app events. Issue #581 is open for declarative app-to-app dependencies.

## Patterns Found

### Pattern 1: Event Bus / Pub-Sub (Fire-and-Forget Coordination)

**Used by**: Home Assistant (custom events + automation.trigger), AppDaemon (events), microservice event-driven architectures

**How it works**: Apps communicate by publishing events to a shared bus and subscribing to topics of interest. The publisher doesn't know or care who listens. Events carry data payloads. Subscribers filter by topic, entity, or payload content.

HA uses two mechanisms: `automation.trigger` (directly invoke another automation's action sequence, bypassing conditions) and custom events (`event: my_custom_event` with data payload). Community workarounds include helper entities (input_boolean) as coordination signals.

**Strengths**: Maximum decoupling — publisher and subscriber are independent. Adding new subscribers requires no change to the publisher. Natural fit for event-driven systems. Scales to many-to-many communication.

**Weaknesses**: No request/response (fire-and-forget only). Debugging chains is hard (who's listening?). No delivery guarantee (if subscriber isn't running, event is missed). No typed contracts — payload schema is informal.

**Example**: https://www.home-assistant.io/docs/automation/services/

### Pattern 2: Shared State / State Publishing (Blackboard Pattern)

**Used by**: AppDaemon (`set_state`), Home Assistant (helper entities), Node-RED (global/flow context), Airflow XCom

**How it works**: Apps write to a shared state store that others read from. The state is persistent (survives restarts) and observable (subscribers get notifications on change). This is the "blackboard" pattern — apps communicate by writing to and reading from a shared surface.

Node-RED implements this with three scope levels: node context (private), flow context (shared within a tab), global context (shared everywhere). Subflows get their own flow context with `$parent.` access to the enclosing flow.

Airflow's XCom (cross-communication) is more structured: tasks push key-value pairs that downstream tasks pull. XComs are scoped to a DAG run.

**Strengths**: Simple mental model (read/write shared data). Persistent — survives restarts. Observable (change notifications). Natural for "current state" coordination. Decoupled in time (writer and reader don't need to be running simultaneously).

**Weaknesses**: Race conditions if multiple writers. Implicit coupling (hard to discover who reads/writes what). No schema enforcement. Becomes a dumping ground for arbitrary data. Difficult to test in isolation.

**Example**: https://nodered.org/docs/user-guide/context

### Pattern 3: Direct Reference / Method Call

**Used by**: AppDaemon (`get_app("other_app")`), VS Code (`vscode.extensions.getExtension("id").exports`)

**How it works**: One unit directly references another by name/ID and calls methods on it. The calling unit depends on the implementation of the called unit — tightest possible coupling.

AppDaemon's `get_app("other_app")` returns the live app instance. VS Code extensions export a public API object that other extensions can access via `getExtension().exports`.

**Strengths**: Strongest contracts (typed method calls, immediate return values). Simple to understand. IDE support (autocomplete, type checking). Natural for "service" patterns where one app provides functionality to others.

**Weaknesses**: Tight coupling (caller depends on callee's implementation). Startup ordering sensitivity (what if the referenced app isn't running yet?). Testing requires the dependency to exist. Changes to the called app can break callers.

**Example**: https://code.visualstudio.com/api/references/vscode-api#extensions

### Pattern 4: Command Registry / Named Procedures (RPC)

**Used by**: VS Code (commands), n8n (Execute Sub-workflow), Node-RED (Link Call nodes)

**How it works**: A central registry maps names to callable procedures. Apps register commands they provide; other apps invoke commands by name. The registry mediates — callers don't hold direct references to providers.

n8n's "Execute Sub-workflow" node calls another workflow synchronously, passing data in and receiving results back. The called workflow declares its input schema. Node-RED's "Link Call" nodes send a message to a linked flow and wait for a return message.

**Strengths**: Looser coupling than direct reference (mediated by registry). Supports request/response pattern. Typed contracts possible (input schema). Provider can be swapped without changing callers. Natural for "I need a result" interactions.

**Weaknesses**: Still synchronous (caller blocks waiting for response). Registry is a single point of failure. Name collisions. Harder to discover available commands. Testing requires registry setup.

**Example**: https://docs.n8n.io/flow-logic/subworkflows/

### Pattern 5: Declarative Dependencies / Dataset-Aware Scheduling

**Used by**: Airflow (Datasets), Make/build systems, systemd (After=, Requires=)

**How it works**: Units declare what they produce and consume. The framework resolves ordering automatically. Airflow Datasets: a DAG declares `outlets=[Dataset("s3://bucket/path")]`; downstream DAGs trigger when that dataset is updated. No explicit trigger — the framework infers the dependency graph.

systemd uses `After=` (ordering) and `Requires=` (hard dependency) to express inter-service relationships declaratively.

**Strengths**: Framework-resolved ordering (no manual startup coordination). Declarative (easy to visualize the dependency graph). Automatic triggering. No runtime coupling between units.

**Weaknesses**: Limited to "A finishes before B starts" patterns. Cannot express complex interactions (conditional dependencies, bidirectional communication). Requires framework support for dependency resolution. Graph cycles must be detected and rejected.

**Example**: https://airflow.apache.org/docs/apache-airflow/stable/authoring-and-scheduling/datasets.html

### Pattern 6: Actor Model / Message Passing

**Used by**: Erlang/OTP, Akka, Elixir GenServer, Pykka

**How it works**: Each unit is an actor with a private mailbox. Communication is exclusively via asynchronous message passing. Messages are processed sequentially by the receiving actor. No shared state — actors own their data and only expose it via message responses.

The supervision tree determines lifecycle relationships. Actors can monitor each other (receive notifications on death). Message patterns (call vs. cast) distinguish request/response from fire-and-forget.

**Strengths**: Strongest isolation (no shared state). Sequential message processing eliminates races within an actor. Natural supervision hierarchy. Location-transparent (works across processes/machines). Well-proven for fault-tolerant systems.

**Weaknesses**: Message serialization overhead. No compile-time contract enforcement (messages are dynamic). Debugging message flows is complex. Overkill for in-process communication between cooperative units. Python lacks native actor support.

**Example**: https://www.erlang.org/doc/system/actors.html

### Pattern 7: Supervision Tree with Ordered Startup

**Used by**: Erlang/OTP supervisors, systemd, hassette's Resource hierarchy

**How it works**: Units are organized in a tree. Parent nodes control child lifecycle. Startup order follows the tree structure (children start after parent). Shutdown is reverse order. Dependencies between siblings are expressed via declaration (`depends_on`), and the parent resolves ordering.

**Strengths**: Deterministic startup/shutdown. Failure isolation (crashed child doesn't crash siblings under `one_for_one`). Natural for hierarchical systems. Restart strategies handle transient failures.

**Weaknesses**: Only expresses parent-child relationships naturally. Sibling dependencies require additional mechanism. Tree structure may not match communication patterns.

**Example**: https://www.erlang.org/doc/system/sup_princ.html

### Pattern 8: Choreography / Event Chain (Saga Pattern)

**Used by**: Microservice architectures, n8n (workflow chaining via webhooks)

**How it works**: Multi-unit workflows are expressed as event chains — each unit reacts to events from the previous unit and emits events for the next. No central coordinator. Failure handling uses compensating transactions (undo previous steps).

**Strengths**: Fully decoupled (no unit knows about the full chain). Each unit is independently deployable and testable. Natural for eventual consistency patterns.

**Weaknesses**: Hard to understand the full flow (no single place shows the chain). Compensating transactions are complex. Debugging requires distributed tracing. No single point of failure but also no single point of visibility.

**Example**: https://learn.microsoft.com/en-us/dotnet/architecture/microservices/architect-microservice-container-applications/communication-in-microservice-architecture

## Anti-Patterns

- **Direct method calls without dependency declaration**: AppDaemon's `get_app()` lets apps call each other freely, but startup ordering is not guaranteed. If App A calls `get_app("B")` before B has initialized, it gets None or a partially-constructed instance. Dependency declarations (like hassette's `depends_on`) must accompany direct references.

- **Global mutable state as communication channel**: Using module-level globals or class variables for inter-app data creates invisible coupling, testing nightmares, and race conditions. Even HA's community has learned this — helper entities (explicit, observable state) are preferred over hidden globals.

- **Implicit dependency via import**: One app importing from another's module creates a hard dependency that the framework can't see. The framework cannot order startup, detect cycles, or isolate failures if dependencies are hidden in import statements.

## Emerging Trends

- **Dataset-Driven Scheduling (Airflow Datasets)**: Declarative "produces/consumes" relationships that the framework resolves automatically. No explicit triggers — upstream completion triggers downstream. This is gaining adoption as the cleanest declarative dependency pattern.

- **Typed Inter-Unit Contracts**: n8n's sub-workflow input schema and VS Code's extension API exports show a trend toward declaring what an automation unit offers/expects with type information, enabling validation before runtime.

## Relevance to Us

Hassette already has the building blocks for inter-app communication:

**What exists:**
- Event bus with custom topics (Pattern 1) — apps can fire and subscribe to arbitrary events
- Shared HA state (Pattern 2) — apps see the same entity states
- App lifecycle events (Pattern 1 variant) — `on_app_running`, `on_app_state_changed`
- Resource hierarchy with `depends_on` (Pattern 7) — but only for services, not apps

**What's missing (Issue #581 scope):**

1. **Declarative app dependencies** — apps cannot declare "I need App B to be running before I start." The `depends_on` mechanism exists for services but not for App subclasses. This is the #1 gap.

2. **Typed inter-app events** — custom events (`self.send_event("topic", data)`) have no schema enforcement. Neither publisher nor subscriber can validate the payload at registration time.

3. **Request/response between apps** — the bus is fire-and-forget only. If App A needs a result from App B, there's no built-in RPC-like mechanism (Pattern 4).

4. **Discoverability** — no way for an app to find "what events does App B publish?" or "what services does App B offer?" without reading its source code.

## Recommendation

For Issue #581, the recommended approach is a **layered solution**:

**Layer 1 (Minimum viable — startup ordering):**
Add `depends_on` support at the App level (analogous to the existing Resource `depends_on`). Apps declare which other apps must be running before they initialize. The framework resolves ordering and fails fast on cycles.

```python
class MyApp(App[MyConfig]):
    depends_on_apps = ["other_app"]  # must be running before on_initialize
```

This is Pattern 5 (Declarative Dependencies) applied to apps. systemd's `After=` is the closest analog.

**Layer 2 (Event contracts — optional):**
Typed event declarations on App classes that document what events they publish/subscribe to. Not enforced at runtime initially, but enables tooling (discoverability, documentation generation).

```python
class MyApp(App[MyConfig]):
    publishes = [AppEvent("my_topic", schema=MyEventData)]
    subscribes_to = [AppEvent("other_topic", schema=OtherEventData)]
```

**Layer 3 (Request/response — future):**
A command registry (Pattern 4) where apps register callable procedures. Other apps invoke by name with typed arguments and receive results. Only add this if real user demand emerges — the event bus handles most coordination needs.

**What NOT to do:**
- Don't encourage `get_app()` — it's a service locator anti-pattern that bypasses the framework's lifecycle management
- Don't add shared mutable state beyond HA entities — it creates invisible coupling
- Don't implement actors — overkill for in-process coordination between cooperative Python apps

## Sources

### Reference implementations
- https://www.home-assistant.io/docs/automation/services/ — HA inter-automation communication
- https://nodered.org/docs/user-guide/context — Node-RED context (shared state) system
- https://docs.n8n.io/flow-logic/subworkflows/ — n8n sub-workflow execution
- https://flowfuse.com/node-red/core-nodes/link/ — Node-RED Link Call (RPC-like)
- https://nodered.org/docs/developing-flows/flow-structure — Node-RED flow structure

### Documentation & architecture
- https://learn.microsoft.com/en-us/dotnet/architecture/microservices/architect-microservice-container-applications/communication-in-microservice-architecture — Microservice communication patterns
- https://community.home-assistant.io/t/how-to-trigger-another-automation-in-an-automation/611809 — HA community inter-automation patterns

### Community feedback
- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.executeworkflow/ — n8n Execute Sub-workflow node
