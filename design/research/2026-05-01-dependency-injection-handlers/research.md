---
topic: "Dependency Injection for Event Handlers"
date: 2026-05-01
status: Draft
---

# Prior Art: Dependency Injection for Event Handlers

## The Problem

Event handlers need data from events — the new state, the entity ID, service call parameters. Without DI, every handler starts with boilerplate extraction: `entity_id = event.payload.data.entity_id`, `new_state = StateRegistry.convert(event.payload.data.new_state)`. This is repetitive, error-prone (wrong path → runtime KeyError), and couples handlers to the event's internal structure.

The alternative is letting handlers declare what data they need in their function signature and having the framework extract, convert, and inject it. This is well-established for HTTP handlers (FastAPI's `Depends()`, Litestar's `Provide()`) but novel for event handlers. The design space covers: how to declare dependencies (type annotations, markers, parameter names), when to inspect signatures (registration vs call time), how to handle extraction failures (missing data, wrong type), and how to support testing (inject values directly without constructing full events).

## How We Do It Today

Hassette's D module uses **`Annotated[T, AnnotationDetails(extractor, converter)]` type aliases** for handler parameter injection. Users write `new_state: D.StateNew[LightState]` and the framework extracts the new state dict from the event, converts it to a `LightState` Pydantic model, and injects it as a keyword argument. Signature inspection happens **at registration time** via `ParameterInjector`, which caches `param_details` as a dict mapping parameter names to `(type, AnnotationDetails)`. At invocation time, `inject_parameters(event)` applies extractors and converters. Available dependencies include `D.StateNew[T]`, `D.StateOld[T]`, `D.EntityId`, `D.Domain`, `D.EventContext`, with `D.Maybe*` variants for optional injection. Failures raise `DependencyResolutionError` with full context (handler name, param name, extracted type, target type). Handlers receive **only injected parameters** — no raw event unless explicitly annotated.

## Patterns Found

### Pattern 1: Signature-Based Dependency Resolution (FastAPI Depends)

**Used by**: FastAPI, Litestar (`Provide`), Sanic Extensions, starlette-di

**How it works**: The framework inspects handler signatures at registration time using `inspect.signature()`. Each parameter is classified based on type annotation and metadata markers (`Depends()`, `Query()`, `Body()`). A dependency tree (`Dependant` object in FastAPI) is built once. At invocation time, the tree is walked: each dependency callable is called (recursively if it has its own dependencies), and results are passed as keyword arguments. Per-invocation caching ensures the same dependency runs only once per request.

The `Annotated[T, Depends(callable)]` pattern moves DI metadata into the type annotation itself, enabling reusable type aliases: `CurrentUser = Annotated[User, Depends(get_current_user)]`. This is now the recommended approach over bare `Depends()` default values.

**Strengths**: Type-safe, IDE autocompletion works, testing bypasses DI (pass values directly as kwargs). Dependency tree built once, reused per invocation. Supports async. Reusable aliases via `Annotated`.

**Weaknesses**: Circular dependencies error at registration (good but confusing). `Depends()` is framework-specific. Deeply nested trees hard to debug. `use_cache=True` default can cause subtle bugs with side-effecting dependencies.

**Example**: https://fastapi.tiangolo.com/tutorial/dependencies/ / https://github.com/fastapi/fastapi/blob/master/fastapi/dependencies/utils.py

### Pattern 2: Name-Based Fixture Resolution (pytest)

**Used by**: pytest, some internal testing frameworks

**How it works**: Parameter names are matched to registered fixture names. `def test_foo(db, client)` looks up fixtures named `db` and `client`. Resolution follows a precedence chain: local → conftest → plugin. Fixtures form a dependency graph with scoped lifecycles (function, class, module, session) and automatic teardown.

**Strengths**: Extremely ergonomic for testing — no imports needed. Scope system provides automatic resource management. Parametrize enables test matrix generation.

**Weaknesses**: Name-based coupling — renaming a fixture silently breaks consumers. No type safety. Name collisions across layers cause surprising behavior. Discovery is hard — IDEs struggle with completions. The pytest community actively debates these issues ([source](https://github.com/pytest-dev/pytest/discussions/9946)).

**Example**: https://docs.pytest.org/en/stable/how-to/fixtures.html

### Pattern 3: Container-Based DI with Wiring

**Used by**: python-dependency-injector, Lagom, punq

**How it works**: A central `Container` defines providers (Factory, Singleton, Resource). `@inject` decorator + `Provide[]` markers in signatures tell the wiring system what to inject. `container.wire(modules=[...])` patches functions at startup. At runtime, patched functions resolve providers from the container. Providers support lifecycle: Singleton (once), Factory (per-call), Resource (context manager).

**Strengths**: Explicit dependency graph in container definition. Provider overriding for testing. Lifecycle management built in. Framework-agnostic.

**Weaknesses**: Boilerplate-heavy. "Decorator must be first" constraint is fragile. Wiring is a global side effect. Container is essentially a Service Locator. Implemented in Cython for performance, confirming that inspection overhead is a real concern.

**Example**: https://python-dependency-injector.ets-labs.org/wiring.html

### Pattern 4: Layered Scope Resolution (Litestar / NestJS)

**Used by**: Litestar, NestJS, Angular (hierarchical injectors)

**How it works**: Dependencies declared at multiple application layers (app, router, controller, handler). Lower scopes override higher. Litestar builds a memoized "signature model" per handler by merging all applicable layers. NestJS has three scopes (DEFAULT/singleton, REQUEST, TRANSIENT) with "scope bubbling" — a singleton depending on request-scoped becomes request-scoped.

**Strengths**: Natural for hierarchical apps. Common dependencies at app level, specific at handler level. Override semantics enable testing. Memoized merge keeps runtime constant.

**Weaknesses**: Scope bubbling causes unexpected behavior. Hard to determine which provider wins at a handler. Debugging requires understanding full hierarchy.

**Example**: https://docs.litestar.dev/2/usage/dependency-injection.html

### Pattern 5: Type-Annotation Auto-Injection

**Used by**: Sanic Extensions, python-inject (`@autoparams`), Google Pinject (deprecated)

**How it works**: Parameters are resolved purely by their type annotation — `param: DatabaseService` triggers lookup of a registered `DatabaseService` provider. No explicit marker needed. Pinject went further with implicit binding (auto-instantiating unregistered types).

**Strengths**: Minimal boilerplate. Reads as natural Python. Good when types map 1:1 to implementations.

**Weaknesses**: Ambiguous with multiple implementations of same type. Implicit binding creates objects with wrong defaults silently. Every annotation becomes an injection point — no way to say "I just want to type-hint this." This is why FastAPI moved to explicit `Depends()` markers.

**Example**: https://sanic.dev/en/plugins/sanic-ext/injection.html

### Pattern 6: Composition Root / Manual DI

**Used by**: Cosmic Python architecture, DDD projects, Starlette applications

**How it works**: A single `bootstrap.py` constructs the entire dependency graph using plain constructors and function arguments. No framework, no decorators, no signature inspection. Handlers are closures capturing their dependencies. The message bus receives pre-wired handler functions.

**Strengths**: No magic — explicit, traceable, debuggable. Works with any IDE. Testing trivial. No framework lock-in. Zero runtime reflection overhead.

**Weaknesses**: Boilerplate scales linearly with dependencies. Every new dependency updates the bootstrap. No automatic lifecycle management. Composition root becomes a God Function for large apps.

**Example**: https://www.cosmicpython.com/book/chapter_13_dependency_injection.html

### Pattern 7: Accessor/Extractor Pattern (FastAPI Path/Query/Body)

**Used by**: FastAPI (`Path()`, `Query()`, `Body()`), Litestar, AWS Lambda Powertools, hassette (A + D modules)

**How it works**: Instead of injecting services, this extracts specific fields from payloads into typed handler parameters. `entity_id: Annotated[str, Path()]` or `user: Annotated[User, Body()]` tells the framework where to look, what to extract, and what type to convert to. FastAPI implements this within the same `get_dependant` mechanism as `Depends()`. AWS Lambda Powertools' `@event_source` parses raw Lambda events into typed models.

Hassette's D module is an application of this pattern to event payloads: `D.StateNew[LightState]` = "extract new_state from event, convert to LightState." The accessor (A module) and converter are bundled in the `AnnotationDetails` metadata.

**Strengths**: Self-documenting signatures. Automatic type conversion/validation. Composable with DI. Testing simple — pass extracted values directly.

**Weaknesses**: Each extraction point needs a new marker type. Extraction logic hidden behind markers. Complex payloads lead to a mini-DSL of extractors.

**Example**: https://fastapi.tiangolo.com/tutorial/path-params/

## Anti-Patterns

- **Service Locator masquerading as DI**: Functions reach into a global container at runtime (`container.resolve(MyService)`) instead of declaring dependencies in signatures. Hides true dependencies, breaks testing, creates implicit coupling. ([source](https://www.sciencedirect.com/science/article/pii/S0164121221002223))

- **Implicit auto-binding**: The DI framework auto-instantiates unregistered types by inspecting constructors. Missing bindings become silent wrong-default instantiations instead of loud errors. python-inject documents this as the `bind_in_runtime` footgun. ([source](https://github.com/ivankorobkov/python-inject))

- **Captive dependency (scope mismanagement)**: A singleton holds a per-event/per-request dependency, reusing stale state across invocations. In NestJS, manifests as scope bubbling. ([source](https://docs.nestjs.com/fundamentals/injection-scopes))

- **Over-injection**: Handler declares 10+ injected parameters, signaling single-responsibility violation. Each additional dependency increases injection failure surface. ([source](https://www.sciencedirect.com/science/article/pii/S0164121221002223))

## Emerging Trends

**PEP 746 — static validation of Annotated metadata**: Would let type checkers verify that `Annotated[int, FromEvent("brightness")]` is valid (the accessor returns something convertible to `int`). Closes the gap between runtime DI and static analysis. Not yet widely implemented. ([source](https://peps.python.org/pep-0746/))

**Convergence on `Annotated[T, Marker]`**: FastAPI, Litestar, and Pydantic have all adopted `Annotated[T, metadata]` as the standard for framework-specific type annotation behavior, replacing default-value patterns (`param: str = Depends(...)`). Makes type aliases reusable and separates type hints from DI markers. ([source](https://www.francoisvoron.com/blog/typing-annotated-the-new-python-cool))

**Event-driven frameworks adopting web DI patterns**: Pyventus is actively discussing handler DI ([source](https://github.com/mdapena/pyventus/discussions/28)). Sanic already injects into signal handlers. The distinction between "request handler DI" and "event handler DI" is collapsing into a single pattern.

## Relevance to Us

Hassette's D module is **well-aligned with the modern Python DI ecosystem** and in some ways ahead of it — applying FastAPI's signature-based DI to event handlers is novel, and the integration with the A (accessor) layer provides a clean extractor pattern.

**What we're doing well:**

- **`Annotated[T, AnnotationDetails]` pattern** — matches the industry convergence on `Annotated[T, Marker]` as the standard. Reusable type aliases (`D.StateNew[LightState]`) follow FastAPI's recommended approach.

- **Registration-time signature inspection** — matches FastAPI's pattern of building the dependency model once and reusing per invocation. `ParameterInjector` caches `param_details`, avoiding per-call reflection overhead.

- **Integrated accessor/extractor pattern** (Pattern 7) — `AnnotationDetails(extractor, converter)` bundles "where to look" and "how to convert" into the type annotation. This is the same concept as FastAPI's `Path()`/`Query()`/`Body()` but applied to event payloads.

- **Explicit failure handling** — `DependencyResolutionError` with full context (handler, param, types). Better than silent None injection or generic errors.

- **Optional dependencies** — `D.Maybe*` variants allow None gracefully, matching the pattern of optional extraction in FastAPI/Litestar.

- **No raw event by default** — handlers receive only injected parameters, enforcing the principle that handlers declare their interface. The full event is available only via explicit annotation.

**Gaps worth examining:**

1. **No hierarchical/layered scopes** (Pattern 4): All dependencies are resolved at the handler level. Litestar's pattern of declaring dependencies at app/router/controller level would allow framework-wide defaults (e.g., a common `Api` accessor) with per-handler overrides. Currently not needed at hassette's scale, but would reduce repetition if many handlers share the same extraction patterns.

2. **No per-invocation caching**: FastAPI caches resolved dependencies per-request — if the same `Depends()` appears multiple times in a dependency tree, it runs once. Hassette's extractors run independently per parameter. If two parameters extract from the same event path (unlikely but possible), the extraction runs twice. Negligible cost for hassette's use case.

3. **No recursive dependency resolution**: FastAPI's `Depends()` can itself have dependencies (resolved recursively). Hassette's `AnnotationDetails` are flat — an extractor is a callable that takes an event, not a dependency that can depend on other dependencies. This is simpler and sufficient for event payload extraction, where the dependency graph is one level deep.

## Recommendation

Hassette's D module is well-designed and aligned with the `Annotated[T, Marker]` pattern the ecosystem is converging on. The integration with the A (accessor) module creates a clean two-layer system (extractor + converter) that maps naturally to event payload extraction.

No structural changes needed. The flat dependency model (no recursion, no scopes) is the right choice for event handler DI where the "dependency graph" is really just "extract fields from an event payload." The complexity of hierarchical scopes, recursive resolution, and per-invocation caching that web frameworks need doesn't apply to hassette's event-extraction use case.

The most actionable insight from the research is the **PEP 746 direction** — if it's adopted, hassette could add `__supports_type__` to its `AnnotationDetails` class, enabling type checkers to verify that `D.StateNew[LightState]` is valid (the accessor returns something convertible to `LightState`). This is future-proofing, not a current need.

## Sources

### Reference implementations
- https://github.com/fastapi/fastapi/blob/master/fastapi/dependencies/utils.py — FastAPI dependency resolution source
- https://python-dependency-injector.ets-labs.org/wiring.html — python-dependency-injector wiring
- https://github.com/ivankorobkov/python-inject — python-inject library
- https://github.com/daireto/starlette-di — starlette-di library

### Blog posts & writeups
- https://ponderinglion.dev/posts/demystifying-fastapis-dependency-injection/ — FastAPI DI deep dive
- https://guissmo.com/blog/fastapi-annotated-depends-pattern/ — Annotated + Depends pattern
- https://www.francoisvoron.com/blog/typing-annotated-the-new-python-cool — Annotated metadata in Python
- https://www.cosmicpython.com/book/chapter_13_dependency_injection.html — Manual DI / composition root
- https://www.cosmicpython.com/blog/2019-08-03-ioc-techniques.html — Three IoC techniques in Python
- https://blog.eamonnmr.com/2023/07/how-make-opt-in-arguments-like-pytest-fixtures-with-a-python-decorator/ — Minimal fixture-style DI
- https://www.netguru.com/blog/dependency-injection-with-python-make-it-easy — Lightweight Python DI

### Documentation & standards
- https://fastapi.tiangolo.com/tutorial/dependencies/ — FastAPI dependencies tutorial
- https://fastapi.tiangolo.com/reference/dependencies/ — FastAPI dependencies reference
- https://docs.litestar.dev/2/usage/dependency-injection.html — Litestar DI
- https://docs.litestar.dev/2/migration/fastapi.html — Litestar migration from FastAPI
- https://docs.pytest.org/en/stable/how-to/fixtures.html — pytest fixtures
- https://sanic.dev/en/plugins/sanic-ext/injection.html — Sanic injection
- https://sanic.dev/en/guide/advanced/signals.html — Sanic signal handlers
- https://docs.nestjs.com/fundamentals/custom-providers — NestJS custom providers
- https://docs.nestjs.com/fundamentals/injection-scopes — NestJS injection scopes
- https://peps.python.org/pep-0746/ — PEP 746: Type checking Annotated metadata

### Issues & discussions
- https://github.com/pytest-dev/pytest/discussions/9946 — Should fixtures stop being DI?
- https://github.com/pytest-dev/pytest/issues/2267 — pytest inspect.signature migration
- https://github.com/encode/starlette/issues/713 — Starlette DI discussion
- https://github.com/mdapena/pyventus/discussions/28 — Pyventus event handler DI
- https://www.sciencedirect.com/science/article/pii/S0164121221002223 — DI anti-patterns catalog
