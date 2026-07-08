---
proposal: "Extract a shared lightweight DI dispatch layer from the bus-specific pipeline, with a multi-source dispatch API that supports resolving handler parameters from multiple disparate objects (Event + StateManager, ScheduledJob + StateManager, etc.)"
date: 2026-07-07
status: Draft
flexibility: Decided (extraction); Exploring (dispatch API shape)
motivation: "Scheduler predicates need the same inspect-plan-dispatch pattern the bus uses, but with ScheduledJob instead of Event. Future StateValueIs predicates need BOTH a primary source AND a StateManager. The dispatch API must handle multiple source types."
constraints: "Python 3.11+, async-first, Annotated[T, metadata] type hints, Protocol-based matcher, zero-arg callable support, no full DI container"
non-goals: "No auto-wiring, no scopes, no lifecycle management. Just 'given a callable's signature and a set of available objects, build kwargs.'"
depth: normal
---

# Research Brief: Multi-Source Dispatch API for Shared DI Layer

**Initiated by**: Design investigation for extracting bus-specific DI into a shared layer that the scheduler (and future consumers) can use, with a dispatch API that handles multiple source types simultaneously.

## Context

### What prompted this

The bus has a mature DI pipeline that inspects handler signatures at registration time, builds an extraction plan, and at dispatch time passes a single `Event` object through extractors to build kwargs. A new consumer (scheduler predicates) needs the same pattern but with `ScheduledJob` instead of `Event`. Future work (StateValueIs predicates) needs both the primary source AND a `StateManager` injected simultaneously. The current pipeline is hardwired to a single `Event[Any]` source. The question is what dispatch API the shared invoker should expose.

### Current state

The bus DI pipeline spans three files in a clean registration-time / call-time split:

**Registration time** (run once per handler):
- `bus/extraction.py`: `extract_from_signature(signature)` walks every parameter, recognizes `Annotated[T, AnnotationDetails]` or bare `Event` subclass annotations, returns `dict[str, tuple[type, AnnotationDetails]]`.
- `bus/injection.py`: `ParameterInjector.__init__` calls `extract_from_signature` and caches the result as `self.param_details`.

**Call time** (run per event dispatch):
- `bus/injection.py`: `ParameterInjector.inject_parameters(event, **kwargs)` iterates `param_details`, calls `extractor(event)` on each, type-matches or converts, returns populated kwargs.
- `bus/listeners.py`: `HandlerInvoker.invoke(event)` calls `injector.inject_parameters(event)` then `await async_handler(**kwargs)`.

The metadata type is `AnnotationDetails` in `event_handling/dependencies.py`:

```python
@dataclass(slots=True, frozen=True)
class AnnotationDetails(Generic[T]):
    extractor: Callable[[T], Any]       # T is bound to Event[Any]
    converter: Callable[[Any, Any], Any] | None = None
```

The generic `T` is declared as `TypeVar("T", bound=Event[Any])`. Every extractor is `Callable[[Event], Any]`. The `inject_parameters` method takes exactly one `event` parameter and passes it to every extractor. This is where the single-source limitation lives.

The scheduler has zero DI. `SchedulerService.run_job()` wraps the user callable in an async adapter and calls it with `*job.args, **job.kwargs` -- fixed arguments set at scheduling time, no signature inspection, no extraction.

`AnnotationDetails` already lives outside `bus/` (in `event_handling/dependencies.py`), but the plan-building (`extraction.py`) and plan-execution (`injection.py`) code are inside `bus/`. The extraction logic itself is generic -- it operates on `inspect.Signature` and `AnnotationDetails`, not on bus-specific types. Moving it is straightforward.

### Key constraints

- Extractors are plain callables (`Callable[[T], Any]`), not framework objects. The simplicity is deliberate and documented as a strength in the prior DI research (`design/research/2026-05-01-dependency-injection-handlers/research.md`).
- The `Annotated[T, AnnotationDetails]` pattern is well-aligned with ecosystem convergence on `Annotated[T, Marker]` (FastAPI, Litestar, Pydantic). The prior research explicitly recommends keeping it.
- Zero-arg callables must work (scheduler jobs with no DI annotations). The plan is empty, kwargs are empty, the callable is called with no arguments.
- No recursive dependency resolution. The current model is flat (one level of extraction) and should stay flat.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| `AnnotationDetails` | 1 file (`event_handling/dependencies.py`) | Low | Must remain backward-compatible with all existing `D.*` aliases |
| `extract_from_signature` | 1 file (move from `bus/extraction.py` to shared location) | Low | Logic is already generic; only imports change |
| `ParameterInjector` | 1 file (move from `bus/injection.py` to shared location) | Med | `inject_parameters` signature changes from `(event)` to multi-source |
| `HandlerInvoker.invoke` | 1 file (`bus/listeners.py`) | Low | Call site adapts to new `inject_parameters` signature |
| `SchedulerService.run_job` | 1 file (`core/scheduler_service.py`) | Med | Gains DI; needs to build a `ParameterInjector` and pass sources |
| Existing `D.*` aliases | 0 changes | None | Must continue working unchanged |
| Tests | ~4 test files | Med | Test `inject_parameters` with multi-source scenarios |

### What already supports this

- **`AnnotationDetails` is already outside `bus/`.** It lives in `event_handling/dependencies.py`, which is the right shared location. No move needed for the metadata type itself.
- **`extract_from_signature` is already source-agnostic.** It inspects `inspect.Signature` and recognizes `Annotated` metadata. It does not reference `Event` at all -- the `Event`-specific logic is only in `extract_from_event_type`, which is a fallback for bare `Event` type annotations.
- **The `T` generic on `AnnotationDetails` already parameterizes the extractor's source type.** `AnnotationDetails["RawStateChangeEvent"]` documents that the extractor operates on state change events. The generic is currently bounded to `Event[Any]`, but removing/widening that bound is the only change needed to support non-event sources.
- **`execution_mode.py` establishes a precedent.** The `ExecutionModeGuard` was already extracted as a shared leaf dependency between bus and scheduler, proving the codebase already does this kind of sharing.

### What works against this

- **The `T` bound on `AnnotationDetails`.** `T = TypeVar("T", bound=Event[Any])` prevents non-event extractors. This bound must be widened or removed, which changes the type signature of every existing `D.*` alias (even though their runtime behavior is unchanged).
- **`extract_from_event_type` is bus-specific.** This function checks `is_event_type(annotation)` and wraps bare `Event` subclass annotations with the `identity` extractor. It makes sense for the bus but not for the scheduler. The shared layer needs to either exclude this function or make it pluggable.
- **`inject_parameters` takes `event: Event[Any]`.** The signature is the single-source bottleneck. Every extractor is called as `extractor(event)`. Changing this is the core of the extraction work.

## How Frameworks Handle Multi-Source Resolution

### FastAPI: Build-time classification, structured source lists

FastAPI classifies parameters at route registration via `analyze_param()` with this priority:
1. `Annotated` metadata or default is `Depends()` -- sub-dependency (recursive)
2. Type is `Request`/`WebSocket`/`Response`/`BackgroundTasks` -- injected directly by type
3. Param name matches a path parameter -- `params.Path`
4. Type is a Pydantic model (non-scalar) -- `params.Body`
5. Fallback -- `params.Query`

The result is a `Dependant` dataclass with **separate typed lists** for each source category (`path_params`, `query_params`, `header_params`, `cookie_params`, `body_params`, `dependencies`). At dispatch time, `solve_dependencies()` walks each list and calls a source-specific extraction function (e.g., `request_params_to_args()` for path/query/header/cookie; recursive `solve_dependencies()` for sub-dependencies). The dispatch API is:

```python
async def solve_dependencies(
    *, request: Request | WebSocket,
    dependant: Dependant,        # the pre-built plan
    ...
) -> SolvedDependency:           # returns values: dict[str, Any]
```

Key insight: **source classification happens at build time, not dispatch time.** The plan already knows "param X comes from the path, param Y comes from the body." At dispatch time, each category uses its own extraction path on the single `Request` object.

### Container-based frameworks: type-keyed registry

python-dependency-injector, lagom, punq, kink, and python-inject all use a type-keyed internal registry:

- **inject**: `dict[Binding, Constructor]` where `Binding = type | Hashable`. Lookup: `injector.get_instance(Cache)`.
- **punq**: `container.resolve(service_key)` backed by a registration dict.
- **lagom**: `container[Type]` with auto-wiring fallback via `__init__` inspection.
- **kink**: `di[key]` checking `_factories` then `_services` then `_aliases`.

All of these are conceptually `dict[type, value_or_factory]`. The type is the lookup key. Multiple sources are just multiple entries in the dict.

### Zero-arg callables

Every framework handles this trivially: empty plan means empty kwargs means `func()`. No special-casing needed. FastAPI does not short-circuit -- it runs `solve_dependencies`, gets an empty `values` dict, calls `await call(**{})`. This is the right approach.

### Lightweight injection without a container

FastAPI's `solve_dependencies` IS this pattern. It is a pure async function that:
1. Receives a pre-built plan (`Dependant`) and the available sources (`Request`)
2. Walks the plan, extracting values from sources
3. Returns `SolvedDependency(values=dict[str, Any])`
4. The caller then does `await endpoint(**values)`

No container, no global state, no lifecycle management. This is exactly what Hassette's shared layer should be.

## Options Evaluated

### Option A: `dict[type, Any]` -- type-keyed available-sources bag

**How it works**: At dispatch time, the invoker receives a dictionary mapping types to instances. Each `AnnotationDetails` declares what source type its extractor operates on (via the existing `T` generic, made concrete as a `source_type` field). The invoker looks up `available[details.source_type]`, passes the result to the extractor, then converts as before.

```python
# AnnotationDetails gains source_type (with backward-compatible default)
@dataclass(slots=True, frozen=True)
class AnnotationDetails(Generic[T]):
    extractor: Callable[[T], Any]
    source_type: type[T]                                  # NEW
    converter: Callable[[Any, Any], Any] | None = None

# Dispatch API
def invoke(available: dict[type, Any]) -> dict[str, Any]:
    for param_name, (param_type, details) in plan.items():
        source = available[details.source_type]
        raw = details.extractor(source)
        kwargs[param_name] = convert(raw, param_type)
    return kwargs

# Bus call site
invoker.invoke({Event: event})

# Scheduler call site
invoker.invoke({ScheduledJob: job})

# Future StateValueIs predicate
invoker.invoke({Event: event, StateManager: state_mgr})
```

Existing `D.*` aliases would gain `source_type=Event` (or `RawStateChangeEvent` as appropriate), which is the current implicit behavior made explicit. Existing extractors (`Callable[[Event], Any]`) continue to work unchanged -- they still receive an Event, just looked up from the dict instead of passed directly.

**Pros**:
- Existing extractors unchanged. `A.get_state_object_new` still takes an Event and returns a dict. The only change is how the invoker finds the Event to pass.
- Extensible without API changes. Adding StateManager as a source means adding a key to the dict at the call site. No invoker changes.
- Zero-arg case is `invoke({})` -- trivial.
- Matches what DI containers do internally (type-keyed lookup).
- `source_type` field makes the extractor's dependency explicit and inspectable (useful for validation, error messages, and future tooling).

**Cons**:
- `dict[type, Any]` has no type safety at the boundary. The invoker trusts that `available[Event]` is actually an `Event`. Errors surface at extractor call time, not at dict construction.
- `source_type` is redundant with the `T` generic on `AnnotationDetails`. In theory `T` already carries this information, but at runtime generics are erased, so `source_type` is the runtime equivalent.
- Every existing `D.*` alias in `dependencies.py` needs a `source_type=` argument added to its `AnnotationDetails(...)` constructor call. This is mechanical but touches 10+ lines.

**Effort estimate**: Small to Medium. The structural extraction (moving files) is mechanical. The `source_type` addition is a one-line change per alias. The invoker's `inject_parameters` method needs a new signature and a dict lookup per parameter.

**Dependencies**: None. Pure internal refactor using stdlib types.

### Option B: Resolver callable -- `Callable[[type[T]], T]`

**How it works**: Instead of a dict, the invoker receives a resolver function. The invoker calls `resolver(details.source_type)` to get the source for each extractor.

```python
def invoke(resolve: Callable[[type], Any]) -> dict[str, Any]:
    for param_name, (param_type, details) in plan.items():
        source = resolve(details.source_type)
        raw = details.extractor(source)
        kwargs[param_name] = convert(raw, param_type)
    return kwargs

# Bus call site
def bus_resolver(t: type) -> Any:
    if t is Event or issubclass(t, Event):
        return event
    raise TypeError(f"Bus dispatch has no source for {t}")

invoker.invoke(bus_resolver)

# Or with a lambda for simple cases
invoker.invoke(lambda t: event)  # bus: everything comes from the event
```

**Pros**:
- More abstract than a dict. Can be backed by a container, a closure, a chain of resolvers, or lazy computation.
- Could support subclass matching (e.g., `resolve(RawStateChangeEvent)` returns the event even if registered as `Event`).

**Cons**:
- Over-abstraction for the actual use case. The bus passes 1 source. The scheduler passes 1 source. The future multi-source case passes 2. A dict handles all of these with less ceremony.
- Harder to inspect and debug. A dict's contents are visible in a debugger; a resolver function is opaque.
- Error messages are worse. With a dict, a missing key gives `KeyError(StateManager)`. With a resolver, the error depends on the resolver's implementation.
- Every call site must construct a resolver function instead of a dict literal. More boilerplate for the common case.
- The `lambda t: event` shortcut is tempting but incorrect -- it ignores the requested type entirely, which hides bugs when a multi-source handler is dispatched with a single-source resolver.

**Effort estimate**: Same as Option A for the shared layer, plus more boilerplate at each call site.

**Dependencies**: None.

### Option C: Named parameters with `**kwargs` convention

**How it works**: Instead of type-keying, use string names for sources. The invoker receives named sources as keyword arguments.

```python
def invoke(*, event: Event | None = None,
           state_manager: StateManager | None = None,
           job: ScheduledJob | None = None) -> dict[str, Any]:
    ...

# Or the open-ended version
def invoke(**sources: Any) -> dict[str, Any]:
    ...
```

**Pros**:
- Named parameters are self-documenting and IDE-friendly.
- Type checkers can validate the call site (if using the explicit-params version).

**Cons**:
- Not extensible. Adding a new source type requires changing the invoker's signature (explicit version) or loses all type safety (open `**kwargs` version).
- `AnnotationDetails` would need a `source_name: str` field instead of `source_type: type`, coupling extractors to naming conventions rather than types.
- Breaks the abstraction boundary. The shared invoker should not know about `Event`, `ScheduledJob`, or `StateManager` -- those are consumer-specific types.
- Violates the "Protocol-based matcher" constraint -- string matching is not type matching.

**Effort estimate**: Small, but with ongoing maintenance cost every time a new source type is added.

**Dependencies**: None.

## Concerns

### Technical risks

- **`source_type` field on `AnnotationDetails` must default correctly for backward compatibility.** All existing `D.*` aliases construct `AnnotationDetails(extractor=...)` without a `source_type`. If `source_type` is a required field, every alias breaks. Making it optional with a default (or inferring from the generic) is necessary but needs careful design -- a wrong default silently passes the wrong source.
- **`extract_from_event_type` (bare Event annotation fallback) does not fit the shared layer.** It recognizes `def handler(event: RawStateChangeEvent)` and injects the full event via `identity`. This is bus-specific behavior. The shared layer must either exclude it or make it a pluggable classifier (like FastAPI's `analyze_param` priority chain). The simplest path is to keep it in the bus layer as a pre-processing step that adds an `AnnotationDetails` before the shared extractor runs.
- **Type-matching for subclasses in the `available` dict.** If an extractor declares `source_type=RawStateChangeEvent` but the dict has `{Event: event}`, the lookup fails even though the event IS a `RawStateChangeEvent`. The invoker needs either exact-match semantics (caller must use the right key) or subclass-aware lookup (check `isinstance`). Exact-match is simpler and less surprising.

### Complexity risks

- **Two layers of indirection for extraction.** Currently: `extractor(event)`. After: `source = available[source_type]; extractor(source)`. One more step, one more place for errors. The additional step is load-bearing (it enables multi-source), but it does add reader load.
- **`source_type` as both a generic parameter and a runtime field.** `AnnotationDetails[T]` has `T` as a generic and `source_type: type[T]` as a field. These must agree. Static analysis cannot enforce this at present (pending PEP 746). Runtime validation at `ParameterInjector` construction time could catch mismatches.

### Maintenance risks

- **Every new source type needs call-site changes.** Adding a new source means updating the `available` dict at each dispatch site that uses it. With `dict[type, Any]` this is a one-line change per call site, but it IS a change.
- **Existing test infrastructure.** ~4 test files test the injection pipeline against `Event` objects directly. These need updating to pass `{Event: event}` instead. Mechanical but broad.

## Open Questions

- [ ] **Should `source_type` be inferred from the generic `T` or declared explicitly?** Inference (via `__orig_class__` or similar) would avoid the redundancy but is fragile at runtime due to generic erasure. Explicit declaration is redundant but reliable. The existing `D.*` aliases already parameterize `T` (e.g., `AnnotationDetails["RawStateChangeEvent"]`), but that string is erased at runtime.
- [ ] **Should the `available` dict use exact-match or subclass-aware lookup?** Exact-match is simpler but requires callers to use the precise key that extractors expect. Subclass-aware is more forgiving but adds `isinstance` checks on every parameter.
- [ ] **Where should the shared code live?** Options: (a) `event_handling/injection.py` alongside the existing `dependencies.py`; (b) a new top-level `injection/` package; (c) `core/injection.py`. The `event_handling/` location has the advantage of proximity to `AnnotationDetails` and `accessors`, but the name "event_handling" implies event-specificity, which is exactly what we are generalizing away from.
- [ ] **Should `extract_from_event_type` (bare Event annotation fallback) be kept as a bus-specific pre-processor, or should the shared layer have a pluggable classifier chain?** The former is simpler. The latter is more general but may be YAGNI.

## Recommendation

**Option A (`dict[type, Any]`) is the right dispatch API.** It matches what every DI framework uses internally (type-keyed lookup), avoids over-abstraction (Option B's resolver callable adds ceremony without benefit for 1-2 source cases), and stays extensible without API changes (Option C's named params require signature changes for each new source type).

The confidence level for this recommendation is **Supported** -- no single framework explicitly recommends `dict[type, Any]` for lightweight dispatch, but the convergence across FastAPI (structured typed lists, conceptually equivalent), dependency-injector (provider callables keyed by type), inject/punq/lagom/kink (all type-keyed registries) points strongly toward type-keyed lookup as the standard dispatch mechanism.

The prior session's proposed `invoke(available: dict[type, Any])` is well-calibrated. The one addition worth making is `source_type` on `AnnotationDetails` so the invoker knows which key to look up -- without it, the invoker has no way to connect an extractor to its source, and every extractor would need to accept the full dict (breaking existing extractors).

### Suggested next steps

1. **Write a design doc via /mine-define** covering the shared invoker's exact interface: `AnnotationDetails` changes, `ParameterInjector` generalization, call-site patterns for bus and scheduler.
2. **Decide on `source_type` inference vs explicit declaration** -- a quick prototype of both approaches would answer this in 30 minutes.
3. **Decide on module location** -- `event_handling/` vs a new name. This affects imports across the codebase and is worth settling before implementation.

## Sources

### Codebase references
- `src/hassette/event_handling/dependencies.py` -- `AnnotationDetails` definition, `D.*` type aliases
- `src/hassette/bus/extraction.py` -- `extract_from_signature`, signature inspection
- `src/hassette/bus/injection.py` -- `ParameterInjector`, dispatch-time extraction
- `src/hassette/bus/listeners.py` -- `HandlerInvoker.invoke`, `HandlerInvoker.create`
- `src/hassette/core/scheduler_service.py` (lines 422-467) -- scheduler's `*args/**kwargs` invocation (no DI)
- `design/research/2026-05-01-dependency-injection-handlers/research.md` -- prior DI pattern survey

### External references
- [FastAPI dependency resolution source](https://github.com/fastapi/fastapi/blob/master/fastapi/dependencies/utils.py) -- `solve_dependencies`, `get_dependant`, `analyze_param`
- [python-dependency-injector wiring](https://python-dependency-injector.ets-labs.org/wiring.html) -- Provider-based resolution
- [python-inject](https://github.com/ivankorobkov/python-inject) -- Global type-keyed injector
- [Lagom lightweight DI](https://lagom-di.readthedocs.io/) -- Auto-wiring container
- [Punq minimal DI](https://github.com/bobthemighty/punq) -- Minimal container with type resolution
- [Kink DI](https://github.com/kodemore/kink) -- Name-then-type resolution priority
- [PEP 746 -- Type checking Annotated metadata](https://peps.python.org/pep-0746/) -- Future static validation of extractor/source_type agreement
