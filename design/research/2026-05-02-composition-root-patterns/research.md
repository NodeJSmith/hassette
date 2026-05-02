---
topic: "composition root patterns for async service frameworks"
date: 2026-05-02
status: Draft
---

# Prior Art: Composition Root Patterns for Async Service Frameworks

## The Problem

A central coordinator class that holds 15+ service references and lets other components reach into its private attributes is a god object by any definition. But "just use dependency injection" isn't a complete answer — the coordinator also orchestrates async lifecycle (init order, shutdown waves, readiness signals), manages dependency topology, and serves as the identity root for the resource tree. Decomposing it requires understanding which responsibilities should stay centralized (lifecycle orchestration) and which should be distributed (service access).

The specific challenge for async frameworks: services have startup order dependencies, some services need others to be "ready" before they can initialize, and shutdown must reverse the startup order with timeouts at each wave. A naive DI container doesn't handle this; a bootstrap function alone doesn't manage lifecycle.

## How We Do It Today

Hassette's `Hassette` class (core.py) is a Resource subclass with ~25 service slots initialized as `None`, then populated in `wire_services()`. User-facing resources (Bus, Scheduler, Api, StateManager) receive the `hassette` reference via the Resource base class constructor and reach into private attributes: `self.hassette._bus_service`, `self.hassette._scheduler_service`, etc.

**What Hassette actually does:**
1. **Slot storage**: Holds ~25 private attributes for services and facades
2. **Wiring**: `wire_services()` creates all services via `add_child()` in dependency order, passing explicit constructor args where needed
3. **Lifecycle orchestration**: Computes `_init_waves` via topological sort of `depends_on` declarations, starts database first, then remaining services wave-by-wave
4. **Shutdown**: Reverse wave ordering with per-wave and total timeout budgets

**How dependents access services:**
- All user-facing resources (Bus, Scheduler, Api, StateManager) grab backing services from `self.hassette._*` in their `__init__`
- Assert that the backing service is not None (construction order dependency)
- Resource base class signature: `__init__(self, hassette: Hassette, task_bucket=None, parent=None)`

**Existing lifecycle infrastructure:**
- Services declare `depends_on: ClassVar[list[type[Resource]]]`
- Hassette computes topological init waves
- Each service has `on_initialize` / `on_shutdown` hooks
- `mark_ready()` signals readiness to waiting dependents

## Patterns Found

### Pattern 1: Typed Facade (Coordinator as Namespace)

**Used by**: Home Assistant (`HomeAssistant` class), Unity (Application), many game engines

**How it works**: The coordinator exists but contains no business logic — it's a namespace holding typed references to self-contained sub-services. HA's `HomeAssistant` exposes `bus: EventBus`, `states: StateMachine`, `services: ServiceRegistry`, `config: Config` as public typed attributes. Components access `hass.bus.async_fire()` rather than reaching past the facade.

HA also uses `hass.data: dict[str, Any]` as a typed dict for integration-specific state that doesn't belong on the core class, preventing attribute proliferation.

The key: sub-services are the API surface. The coordinator just holds references and passes them through. No private attributes that others reach into.

**Strengths**: Simple to understand. IDE autocomplete works. No framework needed. Sub-services independently testable. Adding services requires no architectural change.

**Weaknesses**: Still a god object by SRP standards. Testing components in isolation still requires either the coordinator or extracting the specific sub-service. Can accumulate attributes (HA has ~30+).

**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/core.py

### Pattern 2: Bootstrap Function (Composition Root as a Function)

**Used by**: Cosmic Python (Architecture Patterns with Python), many production services

**How it works**: A single `bootstrap()` function at the entry point constructs the entire object graph and returns the top-level object. The function accepts overrides for testing. No class, no container — just a function that wires things.

```python
def bootstrap(uow=None, notifications=None, publish=None) -> MessageBus:
    if uow is None:
        uow = SqlAlchemyUnitOfWork()
    # ... wire handlers with dependencies
    return MessageBus(uow=uow, event_handlers=injected_handlers, ...)
```

The function is the ONLY place that knows about concrete implementations. All other code depends on abstractions passed via constructor injection.

**Strengths**: Zero framework overhead. Explicit and readable. Testing is trivial (pass fakes). IDE navigation works. No import-time side effects.

**Weaknesses**: Doesn't scale well past ~20 dependencies without becoming unwieldy. No lifecycle management built in. Manual ordering — you must create dependencies before dependents.

**Example**: https://www.cosmicpython.com/book/chapter_13_dependency_injection.html

### Pattern 3: DI Container with Lifecycle Providers

**Used by**: python-dependency-injector, Dishka, Lagom, .NET built-in DI, Spring

**How it works**: A declarative container defines providers for each service. Providers declare dependencies via constructor types. The container resolves the dependency graph and manages lifecycle (singleton per scope, init order, shutdown in reverse). Async is native — async generators yield a resource and clean up after scope exit.

Dishka (2024-2025) adds scoped containers with nesting: APP scope (framework lifetime) > REQUEST scope (per-request) > custom scopes. Finalization runs in reverse creation order within each scope.

**Strengths**: Automatic dependency resolution. Built-in lifecycle management (ordering, shutdown). Scopes handle lifetime differences naturally. Testability via provider overrides. Async-native in modern implementations.

**Weaknesses**: Learning curve. Magic (hard to follow "who creates what"). Over-engineering for <10 services. Container can become a god object if not scoped carefully.

**Example**: https://python-dependency-injector.ets-labs.org/providers/resource.html, https://dishka.readthedocs.io/en/stable/concepts.html

### Pattern 4: Service Group with Lifecycle Protocol

**Used by**: Swift Service Lifecycle, Erlang/OTP supervisors, systemd

**How it works**: Each service implements a uniform protocol (a single `run()` method, or `start()`/`stop()` pair). A `ServiceGroup` orchestrates them: starts in registration order, monitors them, shuts down in reverse on signal. Each service runs in its own task.

Lifecycle ordering is expressed as **list ordering** rather than a dependency graph. The developer explicitly places services in the order they should start.

**Strengths**: Crystal clear lifecycle semantics. No graph resolution complexity. Structured concurrency integration (each service is a child task). Supervision built in. Graceful shutdown first-class.

**Weaknesses**: Ordering is manual (developer must know dependencies). No automatic resolution. Flat list doesn't express complex topologies well.

**Example**: https://github.com/swift-server/swift-service-lifecycle

### Pattern 5: Constructor Injection with Internal Delegation

**Used by**: Temporal Python SDK (Worker), many well-designed libraries

**How it works**: The public class accepts all dependencies via its constructor. Internally, it delegates to specialized sub-components created during init. A config transformation step between user-provided args and internal construction allows plugins to modify behavior.

```python
class Worker:
    def __init__(self, client, task_queue, workflows, activities, ...):
        config = WorkerConfig(...)
        for plugin in self._plugins:
            config = plugin.configure_worker(config)
        self._workflow_worker = WorkflowWorker(config)
        self._activity_worker = ActivityWorker(config)
```

External consumers see one unified API; internally it's three focused workers with shared config.

**Strengths**: Clean public API (constructor shows all dependencies). Internal complexity hidden. Plugins can extend without API changes. Sub-workers independently testable.

**Weaknesses**: Constructor grows large for complex systems (15+ params). Config transformation adds indirection. Internal components may need shared state.

**Example**: https://deepwiki.com/temporalio/sdk-python/5.1-worker-architecture

### Pattern 6: Phased Init with Submodule Lifecycle

**Used by**: Node-RED runtime, many server frameworks

**How it works**: The runtime splits into independent submodules (comms, flows, nodes, context). Each exports `init(settings)`, `start()`, `stop()`. The top-level coordinator calls lifecycle methods in sequence.

This is module-level organization — each submodule is a separate file/package with its own state, initialized via function call rather than constructor injection.

**Strengths**: Natural code organization. Lifecycle is explicit and ordered. Modules loadable/startable independently in tests. No DI framework needed.

**Weaknesses**: Module-level state (singletons — harder to run multiple instances). Init order hardcoded. Modules needing each other must import directly or receive references during init.

**Example**: https://nodered.org/docs/api/modules/v/1.3/@node-red_runtime.html

### Pattern 7: Scoped Containers (Nested Lifetime Management)

**Used by**: Dishka, ASP.NET Core DI, Autofac, Dagger

**How it works**: Dependencies are categorized by lifetime scope. Nested child containers manage each scope. When a scope exits, dependencies created within it finalize in reverse order.

For a framework like Hassette:
- **APP scope**: WebSocket connection, event bus service, scheduler service (framework lifetime)
- **PER_APP scope**: App instances, per-app bus subscriptions, per-app schedulers
- **PER_HANDLER scope**: Individual event handling, DI resolution for handler args

**Strengths**: Correct resource cleanup guaranteed. Memory-efficient. Natural modeling of framework > app > request lifetimes. Prevents scope leaks.

**Weaknesses**: Developers must think about scope assignment. Scope boundaries hard to define in event-driven systems ("what is a request in pub/sub?"). Runtime overhead from container nesting.

**Example**: https://dishka.readthedocs.io/en/stable/container/index.html

## Anti-Patterns

- **Service Locator Disguised as Constructor**: Accepting the coordinator and reaching into it (`self.hassette._bus_service`) hides dependencies. You can't tell from the constructor what the class actually needs. Testing requires mocking the entire coordinator. **This is hassette's current pattern.** Source: https://blog.ploeh.dk/2010/02/03/ServiceLocatorisanAnti-Pattern/

- **Global Accessor as Primary Pattern**: Making the coordinator globally accessible (HA's `async_get_hass()`) is pragmatic but dangerous as the primary mechanism. Hides dependencies, prevents multiple instances, makes testing harder. HA explicitly warns it's a last resort. Source: https://developers.home-assistant.io/blog/2022/08/24/globally_accessible_hass/

- **Container as Service Locator**: Injecting the DI container itself (then resolving from it anywhere) negates DI benefits. The container should only be touched at the composition root. Source: Mark Seemann's blog

- **Lifecycle in the Wrong Layer**: Putting init/shutdown logic inside the coordinator rather than inside each service makes the coordinator grow unboundedly. Each service should own its own lifecycle; the coordinator only orchestrates ordering. Source: https://github.com/swift-server/swift-service-lifecycle

## Emerging Trends

- **Scoped Async DI Frameworks (2024-2025)**: Dishka represents a new generation designed for async-first Python. Explicit scopes, generator-based lifecycle (yield for init/cleanup), no wiring/decoration of user code. Active development through 2025.

- **Structured Concurrency for Service Lifecycle**: Using task trees (Swift Service Lifecycle, trio/anyio patterns) rather than explicit start/stop. Each service is a long-running task; cancellation and graceful shutdown are handled by the concurrency runtime.

- **Type-Based Auto-Wiring**: Modern DI (Lagom, Dishka) resolves from type annotations alone — no registration ceremony. The type annotation IS the dependency declaration.

## Relevance to Us

Hassette's current architecture maps to the **Service Locator anti-pattern** (Pattern 1 in anti-patterns): components accept the coordinator and reach into privates. But the underlying infrastructure — `depends_on` declarations, topological wave computation, `mark_ready()` signals — is actually closer to **Pattern 4 (Service Group with Lifecycle Protocol)**. The lifecycle orchestration is solid; the *access pattern* is the problem.

**What hassette already has that's good:**
- Services declare `depends_on` (explicit topology)
- Topological init waves (correct ordering)
- `mark_ready()` readiness signals (Pattern 3 in async API contracts research — "scoped spawn with readiness signal")
- Wave-based shutdown with timeouts
- Per-resource task buckets (lifecycle scoping)

**What needs to change (the actual #423 scope):**
- Resources currently receive `hassette` and reach into privates → should receive their backing service directly
- The assertion pattern (`assert self.hassette._bus_service is not None`) should become a constructor parameter that can't be None

**Pattern comparison for hassette's constraints:**

| Pattern | Lifecycle mgmt | Fits hassette? | Migration cost |
|---------|---------------|----------------|----------------|
| 1. Typed Facade | No (orthogonal) | Partially — make attrs public | Low |
| 2. Bootstrap Function | No | Good for tests, not for lifecycle | Low |
| 3. DI Container | Yes (built-in) | Overkill — hassette already has lifecycle | High |
| 4. Service Group | Yes | Already implemented (waves) | N/A |
| 5. Constructor Injection | No (orthogonal) | Direct fix for #423 | Medium |
| 6. Phased Init | Yes | Already implemented (wire_services) | N/A |
| 7. Scoped Containers | Yes | Natural fit for framework/app/handler lifetimes, but heavy | High |

## Recommendation

Hassette doesn't need a DI framework or architectural overhaul. The lifecycle orchestration (waves, `depends_on`, `mark_ready()`) is already well-designed — it's Pattern 4 done right. The problem is narrower: **the access pattern is Service Locator when it should be Constructor Injection.**

**Recommended approach — two-step refactoring:**

### Step 1: Constructor Injection for User-Facing Resources (Pattern 5)

Change Bus, Scheduler, Api, StateManager to receive their backing service as a typed constructor parameter rather than pulling from `self.hassette._*`:

```python
# Before (service locator)
class Bus(Resource):
    def __init__(self, hassette, ...):
        self.bus_service = self.hassette._bus_service  # hidden dependency

# After (constructor injection)
class Bus(Resource):
    def __init__(self, hassette, *, bus_service: BusService, ...):
        self.bus_service = bus_service  # explicit dependency
```

The `hassette` reference remains (for the Resource tree hierarchy and child management), but private attribute access is eliminated. `wire_services()` passes the service explicitly when constructing the resource.

This is the minimum viable fix for #423. It makes dependencies explicit, enables testing without full Hassette, and doesn't disrupt the existing lifecycle.

### Step 2 (Future): Typed Facade (Pattern 1)

Once private access is eliminated, consider making Hassette's remaining service references public typed attributes (like HA's `hass.bus`, `hass.states`). This signals "these are the API surface" rather than "these are implementation details." The `_` prefix currently implies "don't touch" — but components DO touch them, so the prefix is a lie.

This is cosmetic but communicates intent: Hassette is a namespace/coordinator, not a logic container.

### What NOT to do:

- **Don't adopt a DI framework** — hassette's lifecycle orchestration (waves, depends_on, mark_ready) already solves the hard problem. A DI container would duplicate this and fight with it.
- **Don't make services module-level singletons** (Pattern 6) — hassette needs to support multiple instances for testing and potentially multi-home setups.
- **Don't add scoped containers** (Pattern 7) — the framework/app/handler lifetime hierarchy is already managed by the Resource tree and task buckets. Adding a container on top would be a parallel system.

## Sources

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/core.py — HA's HomeAssistant typed facade
- https://developers.home-assistant.io/docs/dev_101_hass/ — HA developer docs on hass object
- https://nodered.org/docs/api/modules/v/1.3/@node-red_runtime.html — Node-RED runtime submodules
- https://deepwiki.com/temporalio/sdk-python/5.1-worker-architecture — Temporal Worker constructor injection
- https://github.com/swift-server/swift-service-lifecycle — Swift Service Group lifecycle

### Blog posts & design rationale
- https://www.cosmicpython.com/book/chapter_13_dependency_injection.html — Cosmic Python bootstrap pattern
- https://blog.ploeh.dk/2011/07/28/CompositionRoot/ — Mark Seemann on composition roots
- https://blog.ploeh.dk/2010/02/03/ServiceLocatorisanAnti-Pattern/ — Service Locator anti-pattern
- https://developers.home-assistant.io/blog/2022/08/24/globally_accessible_hass/ — HA global accessor tradeoffs
- https://www.swift.org/blog/swift-service-lifecycle/ — Swift Service Lifecycle blog post

### Documentation & libraries
- https://python-dependency-injector.ets-labs.org/providers/resource.html — python-dependency-injector lifecycle
- https://dishka.readthedocs.io/en/stable/concepts.html — Dishka scoped DI
- https://lagom-di.readthedocs.io/en/latest/ — Lagom auto-wiring DI
- https://github.com/reagento/dishka — Dishka source (modern async-native DI)
