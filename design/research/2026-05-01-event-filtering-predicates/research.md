---
topic: "Event Filtering and Predicate Composition"
date: 2026-05-01
status: Draft
---

# Prior Art: Event Filtering and Predicate Composition

## The Problem

Every event-driven system needs to answer "when X happens, if Y is true, do Z." The design space for expressing Y — the filter — ranges from declarative data (JSON patterns, YAML conditions) through composable objects (predicate builders, condition trees) to raw code (lambdas, Rx operators). The choice cascades through DX, debuggability, and performance: declarative filters are inspectable and optimizable but hit expressiveness ceilings; raw lambdas are maximally flexible but opaque to introspection; predicate objects sit between, trading ceremony for composability.

For home automation specifically, the challenge is sharper. Events are inherently CRUD-like (`state_changed`, `service_called`), but users think in domain terms ("when the kitchen light turns on", "when motion is detected and it's after sunset"). The filtering layer must bridge HA's generic events to domain-meaningful predicates while handling nested payloads (state → attributes → brightness), temporal modifiers (debounce, throttle), and composable logic (AND/OR/NOT). Additionally, event handlers need specific data extracted from events — the new state, the old brightness value, the service call target — and extracting this in every handler is boilerplate that a DI system can eliminate.

## How We Do It Today

Hassette uses a **three-layer predicate architecture (A→C→P) with a fourth DI layer (D)**. Accessors (A) extract values from events using `glom` paths or typed functions. Conditions (C) test extracted values — `Glob`, `Regex`, `IsIn`, `Comparison`, `Increased`/`Decreased`. Predicates (P) compose accessors + conditions into named dataclass trees — `ValueIs`, `StateTo`, `DomainMatches`, `ServiceDataWhere` — composable via `AllOf` (AND), `AnyOf` (OR), `Not`. All predicates have `.summarize()` for debug output. Users primarily interact through Bus convenience methods (`on_state_change("light.kitchen", changed_to="on")`) which auto-construct predicates from kwargs. For complex cases, raw `P` objects are passed via `where=`. Dependency injection (D) uses `Annotated` type hints on handler signatures (`new_state: D.StateNew[LightState]`) to auto-extract and type-convert event data. Built-in temporal control includes debounce, throttle, and once. Entity IDs support glob patterns.

## Patterns Found

### Pattern 1: Declarative Pattern Matching (Data as Query)

**Used by**: AWS EventBridge, Home Assistant YAML automations, Node-RED Switch nodes, Kafka Connect SMTs

**How it works**: Event filters are expressed as data structures (JSON, YAML, visual rules) that describe the shape of matching events. EventBridge uses JSON where keys specify fields and values specify match criteria — arrays mean "any of these" (OR), multiple keys mean "all must match" (AND), and special operators (`anything-but`, `prefix`, `numeric`) handle complex conditions. HA extends this with YAML trigger/condition/action blocks. Node-RED provides a visual UI with dropdown rules and JSONata expressions as the programmatic escape hatch.

**Strengths**: No code for common cases. Patterns are serializable, inspectable, and optimizable by infrastructure (EventBridge can short-circuit evaluation). Non-programmers can author filters. Schema validation catches errors before runtime.

**Weaknesses**: Every declarative system eventually needs a programmatic escape hatch — HA's Jinja2 templates, Node-RED's JSONata, EventBridge's `$or` nesting — and the escape hatch is typically the worst DX in the system (untyped strings, poor errors). Complex conditions become deeply nested. No IDE support within the pattern language.

**Example**: https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-event-patterns-content-based-filtering.html

### Pattern 2: Reactive Operator Pipeline (Stream Algebra)

**Used by**: RxJS, RxPY, Reactor (Project Reactor), Kafka Streams, Akka Streams

**How it works**: Events flow through a pipeline of operators. Filtering is one operator among many — `filter(predicate)` sits alongside `map`, `debounce`, `throttle`, `distinct_until_changed`, `buffer`, `window`. Composition happens by chaining operators via `.pipe()`, not by composing predicates into objects. In RxJS: `source$.pipe(filter(e => e.type === 'click'), debounceTime(300), map(e => e.target))`.

The key insight: stream composition (piping operators) replaces predicate composition (AND/OR/NOT). `AllOf(pred1, pred2)` becomes `filter(pred1).filter(pred2)` — mathematically equivalent but expressed at the stream level.

**Strengths**: Extremely flexible. Temporal operators integrate naturally. Backpressure built in. Strong TypeScript type narrowing through pipelines. Large operator ecosystem. Lazy evaluation.

**Weaknesses**: Predicates are opaque functions — no introspection, serialization, or optimization. Debugging requires marble diagrams. Steep learning curve. Error handling in pipelines is tricky. No declarative representation for UIs.

**Example**: https://reactivex.io/documentation/operators/filter.html

### Pattern 3: Composable Predicate Objects (Data + Behavior)

**Used by**: Kubernetes Operator SDK, hassette (P/C/A), type-safe filter DSLs (TypeScript)

**How it works**: Predicates are first-class objects (dataclasses, structs) that carry both configuration data and evaluation logic. Compound predicates (`AllOf`, `AnyOf`, `Not`) compose atomic predicates into trees. The tree is data — inspectable, serializable, displayable — but also evaluates itself against events.

The critical design decision is layer separation. Hassette's `ValueIs(source=A.get_entity_id, condition=C.IsIn(["a", "b"]))` cleanly separates "where to look" (accessor) from "what to compare" (condition) from "how to combine" (predicate). This three-layer separation enables mixing accessor strategies with condition strategies without combinatorial explosion. The K8s Operator SDK provides similar composition: `builder.WithPredicates(predicate.And(pred1, pred2))`.

Because predicates are data, they support multiple interpretations — evaluate at runtime, display in debug output, serialize for a monitoring UI, or potentially optimize evaluation order.

**Strengths**: Inspectable and debuggable — print the predicate tree to see what matches. Composable without stream machinery. Type-safe through generics. Domain-specific predicates encode business knowledge. IDE autocomplete on named classes. Multiple interpretations (evaluate, display, serialize).

**Weaknesses**: More ceremony than lambdas for simple cases. Predicate vocabulary is another thing to learn. Composition operators (`AllOf`/`AnyOf`) feel verbose vs `and`/`or` in code. Risk of the predicate model becoming its own complexity.

**Example**: https://sdk.operatorframework.io/docs/building-operators/golang/references/event-filtering/

### Pattern 4: Kwargs-as-Filters (Implicit Declarative)

**Used by**: AppDaemon, Django signals (`sender=`), Blinker (`sender=`), various Python event libraries

**How it works**: Keyword arguments to listener registration double as filters. If a kwarg key matches a key in event data and values are equal, the callback fires. AppDaemon's `listen_event("MODE_CHANGE", callback, mode="away")` fires only when `mode == "away"`. Zero new concepts — filtering keys are event data keys.

**Strengths**: Zero learning curve for equality filters. Natural Python syntax. Compact — one line registers handler + filter. No imports needed.

**Weaknesses**: Only supports equality — no regex, ranges, negation, or composition. Complex logic must go in handler bodies, losing declarative intent. No type checking on keys or values (typos silently match nothing). No autocomplete for valid filter keys. HA community discussions document persistent user confusion about which keys are valid. ([source](https://community.home-assistant.io/t/callback-kwargs-usage/371603))

**Example**: https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html

### Pattern 5: SQL-like Event Processing Language (CEP DSL)

**Used by**: Esper (EPL), Siddhi (SiddhiQL), Apache Flink SQL, ksqlDB

**How it works**: A dedicated query language extends SQL with temporal constructs, windows, and pattern matching. Filters are WHERE clauses, joins operate across streams, and pattern detection uses sequence/temporal operators. Esper: `SELECT * FROM TemperatureEvent WHERE temperature > 100 AND sensor_id = 'A1'`. SiddhiQL adds windows: `FROM TempStream#window.time(5 min) SELECT avg(temp) HAVING avg(temp) > 100`.

These compile into execution plans with predicate pushdown and join reordering.

**Strengths**: Extremely expressive — temporal patterns, joins, windows, aggregations. Query optimization by runtime. Familiar SQL syntax. Native temporal pattern matching.

**Weaknesses**: String-based queries with no type safety, no IDE autocomplete, runtime-only errors. Impedance mismatch with host language. Not appropriate for in-process single-application event handling — designed for stream processing infrastructure.

**Example**: https://objectcomputing.com/resources/publications/sett/october-2008-complex-event-processing-with-esper

### Pattern 6: Signature-Based Dependency Injection for Handlers

**Used by**: FastAPI (`Depends`), pytest (fixtures), hassette (D module), Angular

**How it works**: Handlers declare what data they need through function signatures; the framework resolves and injects values automatically. FastAPI's `Depends()` uses `Annotated[Type, Depends(provider)]` to declare dependencies resolved from request context. Hassette adapts this for event handlers — `D.StateNew[ButtonState]` extracts and type-converts the new state from event payloads, eliminating `event.payload.data.new_state` boilerplate.

The DI system inspects signatures at registration time, resolves the dependency graph, and creates an injection plan. Pytest's name-based DI (fixture names match parameter names) is the simpler cousin of FastAPI's type-based approach.

**Strengths**: Handlers declare their interface, not extraction logic. Type safety through annotations. Testable — inject mock data without full event objects. Extraction logic in accessors, not handler bodies. IDE autocomplete on injected values. Hierarchical resolution.

**Weaknesses**: Magic — annotation-to-value connection not obvious to newcomers. Inspection-based DI has edge cases with decorated functions. Runtime errors on resolution failure harder to trace. Performance overhead from inspection (mitigated by caching). `Annotated` syntax still relatively unfamiliar.

**Example**: https://fastapi.tiangolo.com/tutorial/dependencies/

### Pattern 7: Content-Based Router (Enterprise Integration Pattern)

**Used by**: Apache Camel, Spring Integration, MuleSoft, Azure Logic Apps

**How it works**: A dedicated routing component sits between source and handlers, evaluating events against (predicate, destination) pairs. The router is configured centrally. Apache Camel: `.choice().when(xpath("/order/type = 'widget'")).to("direct:widgets").otherwise().to("direct:other")`.

This differs from predicate-on-handler (hassette's model) in that routing logic is centralized rather than distributed across registrations.

**Strengths**: Routing visible in one place — easier to understand overall flow. Router can optimize evaluation order. Supports fallback/default routing. Decades of production use. Easy to add logging/metrics at the routing point.

**Weaknesses**: Centralized routing becomes a complexity bottleneck as handlers grow. Registration split between router and handler. Must know all destinations at config time. Less suitable for dynamic handler registration.

**Example**: https://www.enterpriseintegrationpatterns.com/patterns/messaging/ContentBasedRouter.html

## Anti-Patterns

- **Opaque lambda predicates**: Anonymous lambdas show up as `<lambda at 0x7f...>` in logs. Teams that start with lambdas for simplicity end up wrapping them in named functions anyway, recreating a predicate vocabulary without composability benefits. Named, inspectable predicate objects are worth the ceremony from day one. ([source](https://event-driven.io/en/anti-patterns/))

- **Kwargs filtering without validation**: When kwargs double as filters with no schema validation, typos silently match nothing. `listen_event("state_changed", callback, enity_id="light.kitchen")` never fires and users can't figure out why. ([source](https://community.home-assistant.io/t/callback-kwargs-usage/371603))

- **Fat events creating coupling**: Full state objects in events enable rich accessor patterns but couple consumers to the producer's schema. Deep path dependencies (`A.get_path("payload.data.new_state.attributes.geolocation.locality")`) break on schema changes. The mitigation: accessor functions as a stable interface over evolving schemas, absorbing changes in one place. ([source](https://codeopinion.com/beware-anti-patterns-in-event-driven-architecture/))

- **Event flooding from noisy fields**: Generating events for every minor change (timestamp updates) floods the bus with events most handlers don't care about. Filter at the source and design predicates to short-circuit on cheap checks before expensive ones. ([source](https://www.ben-morris.com/event-driven-architecture-and-message-design-anti-patterns-and-pitfalls/))

## Emerging Trends

**Filters as data for multi-target compilation**: Modeling filters as recursive data structures (not functions) enables compilation to multiple backends — runtime evaluation, SQL queries, Elasticsearch filters, UI filter builders — from one definition. Hassette's dataclass-based predicates are positioned for this: predicates could serialize to the monitoring UI or compile to optimized evaluation strategies. ([source](https://medium.com/@reidev275/creating-a-type-safe-dsl-for-filtering-in-typescript-53fe68a7942e))

**DI in event handlers (beyond HTTP)**: FastAPI popularized `Depends()` for HTTP; the pattern is spreading to WebSocket handlers, background tasks, CLI commands, and event handlers. Hassette's `D` module is an early example in the home automation space. DI-based handler signatures are becoming the expected ergonomic standard for framework-dispatched functions. ([source](https://fastapi.tiangolo.com/tutorial/dependencies/))

**Declarative + programmatic hybrid**: Pure declarative (YAML patterns) and pure programmatic (lambdas/Rx) each have documented failure modes. The emerging best practice is layered: declarative for common cases (kwargs), structured programmatic for complex cases (predicate objects), raw programmatic as escape hatch (custom callables). This is the model hassette follows.

## Relevance to Us

Hassette's P/C/A/D architecture is **well-validated by the prior art** — it combines the best properties from multiple patterns while avoiding their weaknesses:

**What we're doing well:**

- **Three-layer separation (A→C→P)** is a refinement not commonly seen. Most frameworks collapse at least two layers — K8s Operator SDK combines accessor+condition into the predicate, Rx puts everything in lambdas, EventBridge puts everything in JSON structure. Hassette's separation of "where to look" / "what to compare" / "how to combine" avoids combinatorial explosion and enables mixing strategies independently.

- **Convenience kwargs + composable predicates** — the layered approach. `on_state_change("light.kitchen", changed_to="on")` is as easy as AppDaemon's kwargs for simple cases, but `where=[P.AllOf(...)]` provides structured composition for complex cases without falling back to opaque lambdas. This is the "declarative + programmatic hybrid" pattern that the research identifies as the emerging best practice.

- **Predicates as dataclasses with UI serialization** — inspectable, debuggable (`.summarize()`), and already serialized to the monitoring UI. Both `predicate_description` (repr) and `human_description` (`.summarize()`) are persisted to the DB at registration time, exposed via the API as `ListenerWithSummary` fields, and rendered in the frontend's handler rows (e.g., "Fires when binary_sensor.garage_door → open"). This avoids the "lambda soup" anti-pattern and realizes the "filters as data for multi-target compilation" trend the research identifies — a debugging aid no other HA framework offers.

- **Signature-based DI (D module)** — adapting FastAPI's `Depends` to event handlers is novel in the home automation space. AppDaemon passes raw dicts; HA YAML has no handler concept; hassette gives handlers typed, extracted data via annotations. This is the direction the ecosystem is heading.

- **Built-in temporal control** — debounce, throttle, once alongside predicate filtering mirrors the Rx model of combining filtering with temporal operators, but integrated into the registration API rather than requiring stream piping.

- **Glob patterns for entity IDs** — a pragmatic domain-specific feature that neither Rx nor generic predicate systems offer. Matches the "light.*kitchen*" patterns that home automation users think in.

**Gaps worth examining:**

1. **No operator overloading for composition**: Writing `P.AllOf([P.DomainMatches("light"), P.StateTo("on")])` is more verbose than hypothetical `P.DomainMatches("light") & P.StateTo("on")`. Python's `__and__`/`__or__`/`__invert__` could make composition more natural. The tradeoff: operator overloading is less explicit and harder to search for. Given the codebase's philosophy of explicitness, this may be intentionally avoided.

2. **No short-circuit optimization**: The predicate tree is evaluated fully — `AllOf` doesn't stop on first false, `AnyOf` doesn't stop on first true (worth verifying). EventBridge and CEP systems optimize evaluation order. For home automation volumes this likely doesn't matter, but if predicate evaluation ever shows up in profiling, the dataclass-based tree structure is already in the right shape for optimization.

3. **Richer predicate serialization**: Predicates are already serialized to the UI via `human_description` (`.summarize()`) and `predicate_description` (repr), displayed in handler rows. The current output is string-based. A structured `.to_dict()` serialization could enable richer UI features — interactive predicate trees, filter-by-predicate search in the dashboard, or visual predicate builders. This is polish on an existing capability, not a missing feature.

## Recommendation

Hassette's event handling architecture is the strongest in the HA ecosystem and well-validated against broader patterns. The three-layer A→C→P separation, convenience kwargs bridge, and signature-based DI represent a design that the research confirms is the direction the industry is heading — not a novel experiment.

Predicate serialization to the UI is already in place — `human_description` and `predicate_description` are persisted, API-exposed, and rendered in handler rows. The remaining opportunity is richer structured serialization (`.to_dict()`) for interactive predicate trees or visual builders, but that's polish rather than a gap.

The architecture doesn't need restructuring. The research confirms that hassette has already navigated the key design tradeoffs correctly: declarative for simple cases, structured objects for complex cases, DI for handler ergonomics, named predicates for debuggability, and predicate visibility in the monitoring UI.

## Sources

### Reference implementations
- https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-event-patterns-content-based-filtering.html — EventBridge content-based filtering
- https://reactivex.io/documentation/operators/filter.html — ReactiveX filter operator
- https://rxpy.readthedocs.io/en/latest/operators.html — RxPY operators
- https://sdk.operatorframework.io/docs/building-operators/golang/references/event-filtering/ — K8s Operator SDK predicates
- https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html — AppDaemon event API
- https://docs.sqlalchemy.org/en/21/core/event.html — SQLAlchemy event system
- https://blinker.readthedocs.io/en/stable/ — Blinker signal library
- https://fastapi.tiangolo.com/tutorial/dependencies/ — FastAPI dependency injection
- https://docs.pytest.org/en/4.6.x/fixture.html — pytest fixture DI
- https://developer.confluent.io/patterns/event-processing/event-filter/ — Confluent event filter pattern

### Blog posts & writeups
- https://www.tbray.org/ongoing/When/201x/2019/12/18/Content-based-filtering — Tim Bray on EventBridge design
- https://community.home-assistant.io/t/callback-kwargs-usage/371603 — AppDaemon kwargs confusion
- https://medium.com/@reidev275/creating-a-type-safe-dsl-for-filtering-in-typescript-53fe68a7942e — Type-safe filter DSL
- https://dev.to/deanius/how-to-use-type-guards-for-type-safe-events-in-typescript-3bap — Type-safe events in TypeScript
- https://codeopinion.com/beware-anti-patterns-in-event-driven-architecture/ — EDA anti-patterns
- https://www.ben-morris.com/event-driven-architecture-and-message-design-anti-patterns-and-pitfalls/ — Event design pitfalls
- https://event-driven.io/en/anti-patterns/ — Event modeling anti-patterns
- https://medium.com/@sizanmahmud08/django-signals-the-complete-guide-to-building-responsive-event-driven-applications-775cc7cb1618 — Django signals guide

### Documentation & standards
- https://www.home-assistant.io/docs/automation/trigger/ — HA automation triggers
- https://www.home-assistant.io/docs/scripts/conditions/ — HA conditions
- https://flowfuse.com/node-red/core-nodes/switch/ — Node-RED Switch node
- https://objectcomputing.com/resources/publications/sett/october-2008-complex-event-processing-with-esper — Esper CEP
- https://www.enterpriseintegrationpatterns.com/patterns/messaging/ContentBasedRouter.html — Content-Based Router (EIP)
- https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-patterns-best-practices.html — EventBridge best practices
- https://docs.aws.amazon.com/prescriptive-guidance/latest/lambda-event-filtering-partial-batch-responses-for-sqs/best-practices-event-filtering.html — Lambda event filtering
- https://introtorx.com/chapters/filtering — Intro to Rx.NET filtering
