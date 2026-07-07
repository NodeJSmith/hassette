# Design: Extract Shared DI Layer

**Date:** 2026-07-07
**Status:** approved
**Scope-mode:** hold
**Research:** design/specs/004-extract-event-handling-di/research.md

## Problem

The bus DI pipeline inspects handler signatures, builds extraction plans, and dispatches kwargs — a pattern that is generic in concept but locked behind `Event`-specific method signatures. The scheduler needs the same "inspect → plan → dispatch" pattern for predicate injection (with `ScheduledJob` instead of `Event`), and future `StateValueIs` predicates need multiple sources injected simultaneously (`Event` + `StateManager`). Without a shared layer, each new consumer builds a parallel bespoke mechanism — the scheduler predicate branch already demonstrated this failure mode with arity-counting logic that had to be reworked.

## Goals

- Extract the reusable parts of the bus DI pipeline into `src/hassette/di/`.
- Refactor the bus to consume the shared layer, proving it works.
- All existing extraction, injection, and handler tests pass unchanged — the refactor is invisible to current consumers.
- The shared layer's dispatch API supports multiple source types via `dict[type, Any]` (research-backed — see research brief).

## Non-Goals

- No scheduler code changes. The scheduler adoption happens in a separate branch after this merges.
- No predicate normalization work (`AllOf`, `AnyOf` combinators).
- No new DI features — this is a pure extraction refactor.

## User Scenarios

### Framework developer: Adding DI to a new consumer

- **Goal:** wire DI into the scheduler predicate system
- **Context:** after this PR merges, the scheduler branch rebases and adopts the shared layer

#### Adopt shared DI for scheduler predicates

1. **Import shared primitives** — `build_injection_plan`, `CallableInvoker`, `TypeMatcher` from `hassette.di`
2. **Build a plan at registration time** — `plan = build_injection_plan(sig, [TypeMatcher(ScheduledJob)])`
3. **Dispatch at call time** — `invoker.invoke({ScheduledJob: job})`
4. **Zero-arg predicates work automatically** — empty plan, empty kwargs, `predicate()` called with no args

### App author: Writing event handlers (unchanged)

- **Goal:** write handlers with `D.StateNew`, `D.EntityId`, etc.
- **Context:** existing app code, no changes needed

#### Existing DI annotations continue working

1. **Write a handler with DI annotations** — `async def handler(state: D.StateNew[LightState]):`
2. **Register via bus** — `await self.bus.on_state_change("light.*", handler=self.handler, name="light")`
3. **Handler receives injected params** — Hassette extracts the new state from the event and passes it as a typed `LightState` object

## Functional Requirements

- **FR#1** A new `src/hassette/di/` package provides `AnnotationDetails`, `InjectionParam`, `CallableInvoker`, `ParameterMatcher` (Protocol), `TypeMatcher`, `AnnotatedMatcher`, `build_injection_plan`, `validate_di_signature`, and `identity`.
- **FR#2** `ParameterMatcher` is a `typing.Protocol` with a single `match(param: inspect.Parameter) -> InjectionParam | None` method.
- **FR#3** `TypeMatcher` is constructed with a target type and matches parameters whose annotation is that type or a subclass of it. For parameterized generic annotations (e.g., `Event[Any]`), it unwraps the origin type before the subclass check (matching the behavior of the existing `is_event_type` helper). It produces an `InjectionParam` with `extractor=identity`, `source_type` set to the matcher's target type, and `target_type` set to the annotation type.
- **FR#4** `AnnotatedMatcher` matches parameters with `Annotated[T, metadata]` annotations where `metadata` is either an `AnnotationDetails` instance or a bare callable. When the metadata is a bare callable, it is auto-wrapped into `AnnotationDetails(extractor=callable)`. When the metadata is neither `AnnotationDetails` nor callable, the matcher emits a warning and returns `None` (no match). `AnnotatedMatcher` is constructed with a `source_type` parameter that specifies which source type all matched extractors operate on. It produces an `InjectionParam` with the extractor and converter from the resolved `AnnotationDetails`, `source_type` from the constructor argument (or from `AnnotationDetails.source_type` when set), and `target_type` from the inner type `T`.
- **FR#5** `build_injection_plan` accepts a `Signature` and a sequence of `ParameterMatcher` instances. It walks all parameters, tries each matcher in order, and returns a tuple of `InjectionParam` for all matched parameters. Parameters without annotations or without a matcher match are silently skipped.
- **FR#6** `CallableInvoker` stores a tuple of `InjectionParam`. Its `invoke(available: dict[type, Any])` method builds kwargs by looking up `available[param.source_type]` for each param and calling `param.extractor(source)`, then returns the kwargs dict. It does not store or call the target callable — the caller is responsible for calling the target with the resolved kwargs. The bus's `ParameterInjector` iterates `CallableInvoker.params` individually (not via a single batched `invoke()` call) to preserve per-parameter error attribution in exception messages.
- **FR#7** `validate_di_signature` raises `DependencyInjectionError` for signatures with `VAR_POSITIONAL` (`*args`) or `POSITIONAL_ONLY` parameters.
- **FR#8** `AnnotationDetails` moves from `event_handling/dependencies.py` to `di/`. The `T` TypeVar bound is widened from `Event[Any]` to unbounded, allowing non-Event source types. A `source_type: type[T] | None` field is added with a default of `None` (backward compatible — existing `D.*` aliases construct without it).
- **FR#9** `identity` moves from `event_handling/dependencies.py` to `di/`.
- **FR#10** The bus `ParameterInjector` is refactored to use `build_injection_plan` with `[AnnotatedMatcher(source_type=Event), TypeMatcher(Event)]` at construction time, and `CallableInvoker` for the base kwargs resolution at dispatch time. The bus-specific conversion layer (`extract_and_convert_parameter`, `TYPE_MATCHER`, `ANNOTATION_CONVERTER`) remains in `bus/injection.py`.
- **FR#11** `extract_from_event_type` in `bus/extraction.py` is deleted. Its behavior is replaced by `TypeMatcher(Event)` in the bus's matcher list.
- **FR#12** `has_dependency_injection` in `bus/extraction.py` is deleted — it is unused.
- **FR#13** `extract_from_annotated` in `bus/extraction.py` is deleted. Its logic moves into `AnnotatedMatcher.match()`.
- **FR#14** `extract_from_signature` in `bus/extraction.py` is deleted. Its logic is replaced by `build_injection_plan` in `di/`.
- **FR#15** When `AnnotationDetails.source_type` is set (not `None`), `AnnotatedMatcher` uses it instead of its constructor `source_type` for that param's `InjectionParam`. This enables future per-annotation source types (e.g., a `StateManager`-sourced extractor alongside `Event`-sourced extractors).

## Edge Cases

- **Zero-arg callable:** A callable with no annotations produces an empty plan. `CallableInvoker.invoke({})` returns an empty dict. The callable is called with no args. This is the scheduler's default case for simple predicates.
- **Unannotated parameters:** Parameters without type annotations are silently skipped by `build_injection_plan`. They are not injected — the caller must provide them via the kwargs passthrough if needed.
- **Multiple matchers match the same parameter:** The first matcher to return a non-None `InjectionParam` wins. Order matters — `AnnotatedMatcher` should come before `TypeMatcher` so that `Annotated[Event, AnnotationDetails(...)]` is handled by the annotated path, not the bare-type path.
- **Missing source type in available dict:** `CallableInvoker.invoke()` raises `KeyError` if `available` does not contain a key matching `param.source_type`. The bus's `ParameterInjector` wraps this (and all non-`DependencyError` exceptions from extractors/converters) into `DependencyResolutionError` with a descriptive message — this error-normalization behavior is preserved from the current implementation.
- **`source_type` on AnnotationDetails is None and no constructor default:** `AnnotatedMatcher` always has a constructor `source_type`, so this is the fallback. If a future matcher doesn't provide one, `InjectionParam` construction fails explicitly.
- **Annotated parameter unmatched by any configured matcher:** An annotated parameter matched by none of the consumer's configured matchers is silently dropped from the plan. Downstream consumers (e.g., the scheduler) should decide whether `build_injection_plan` should warn — the way `AnnotatedMatcher` already warns for invalid metadata — when it skips an annotated (vs. unannotated) parameter.

## Acceptance Criteria

- **AC#1** All existing tests in `tests/integration/test_extraction.py`, `tests/integration/test_injection.py`, and `tests/integration/test_annotation_conversion.py` pass after updating import paths to the new `hassette.di` locations. The behavioral assertions in these tests are unchanged — only import paths and function call targets change (e.g., `extract_from_annotated` → `AnnotatedMatcher(...).match(...)`, `extract_from_signature` → `build_injection_plan`) (FR#10, FR#11, FR#13, FR#14).
- **AC#2** All existing handler and bus integration tests pass without modification (FR#10).
- **AC#3** `from hassette.di import AnnotationDetails, CallableInvoker, build_injection_plan, TypeMatcher, AnnotatedMatcher` resolves correctly (FR#1).
- **AC#4** `bus/extraction.py` contains no extraction functions — only imports or is deleted entirely (FR#7, FR#11, FR#12, FR#13, FR#14).
- **AC#5** The `D.*` type aliases in `event_handling/dependencies.py` import `AnnotationDetails` from `hassette.di` (FR#8, FR#9).
- **AC#6** A standalone integration test demonstrates `build_injection_plan` + `CallableInvoker` resolving a non-Event type (e.g., a plain dataclass) through `TypeMatcher`, proving the shared layer works independently of the bus (FR#3, FR#5, FR#6).
- **AC#7** A standalone unit test demonstrates `AnnotatedMatcher` matching `Annotated[T, AnnotationDetails(...)]` parameters and producing correct `InjectionParam` values (FR#4).
- **AC#8** Pyright reports no new errors on the changed files (FR#8).

## Key Constraints

- Do not change the public `D.*` type alias API. App authors import `D.StateNew`, `D.EntityId`, etc. — these must continue working with identical semantics.
- Do not modify the bus dispatch call chain beyond what's needed for the `ParameterInjector` refactor. `BusService.dispatch` → `HandlerInvoker.invoke` → `injector.inject_parameters` flow stays intact; only the internals of `inject_parameters` change.
- `AnnotationDetails.converter` remains bus-specific behavior. The shared `CallableInvoker` does not handle conversion — the bus's `ParameterInjector` applies conversion on top of the shared layer's output.

## Dependencies and Assumptions

- No external dependencies. Pure internal refactor using stdlib types (`inspect`, `typing`, `dataclasses`).
- Assumes the `T` TypeVar bound removal on `AnnotationDetails` has no downstream effect. The bound is `Event[Any]` — removing it widens what's accepted but doesn't narrow it. Pyright should accept this without issues.

## Architecture

The shared layer separates into three concerns: **data structures** (what the plan contains), **plan building** (how to inspect a signature), and **dispatch** (how to resolve kwargs at call time).

### Data structures

`InjectionParam` is a frozen dataclass representing one parameter's injection plan:

```python
@dataclass(frozen=True, slots=True)
class InjectionParam:
    name: str                          # parameter name on the callable
    source_type: type                  # key to look up in available dict
    target_type: Any                   # annotation type for conversion (e.g., LightState)
    extractor: Callable[[Any], Any]    # source → value
    converter: Callable[[Any, Any], Any] | None = None  # optional type converter
```

`target_type` carries the annotation's inner type (e.g., `LightState` from `Annotated[LightState, AnnotationDetails(...)]`, or `RawStateChangeEvent` from a bare annotation). `converter` carries the optional custom converter from `AnnotationDetails.converter` (e.g., `convert_to_datetime`). The bus conversion layer uses both for `TYPE_MATCHER.matches(value, target_type)` and `converter(value, target_type)`. Consumers that don't need conversion can ignore both fields.

`AnnotationDetails` moves from `event_handling/dependencies.py` to `di/` with two changes: the `T` bound is removed (was `bound=Event[Any]`), and an optional `source_type: type[T] | None = None` field is added. The existing `extractor` and `converter` fields are unchanged.

### Plan building

`build_injection_plan(signature, matchers)` replaces `extract_from_signature`. It walks parameters, tries each matcher in order, and collects `InjectionParam` results:

```python
def build_injection_plan(
    sig: Signature,
    matchers: Sequence[ParameterMatcher],
) -> tuple[InjectionParam, ...]:
    validate_di_signature(sig)
    params = []
    for param in sig.parameters.values():
        if param.annotation is Parameter.empty:
            continue
        for matcher in matchers:
            result = matcher.match(param)
            if result is not None:
                params.append(result)
                break
    return tuple(params)
```

Two built-in matchers:

- `TypeMatcher(match_type)` — matches bare type annotations (including subclasses of `match_type`). Unwraps parameterized generics (e.g., `Event[Any]` → `Event`) before the subclass check. Returns `InjectionParam(name, source_type=match_type, target_type=<the annotation type>, extractor=identity)`. For example, `TypeMatcher(Event)` matching a `event: RawStateChangeEvent` param produces `source_type=Event, target_type=RawStateChangeEvent`. Replaces `extract_from_event_type` for the bus and serves the scheduler case.
- `AnnotatedMatcher(source_type)` — matches `Annotated[T, metadata]` where metadata is `AnnotationDetails` or a bare callable (auto-wrapped into `AnnotationDetails(extractor=callable)`). Emits a warning for invalid metadata. Returns `InjectionParam(name, source_type=details.source_type or constructor_source_type, target_type=T, extractor=details.extractor)`. Absorbs the logic from `extract_from_annotated`.

### Dispatch

`CallableInvoker` stores the plan and resolves kwargs at call time. It does not store or invoke the target callable — the caller does that with the returned kwargs:

```python
@dataclass(frozen=True, slots=True)
class CallableInvoker:
    params: tuple[InjectionParam, ...]

    def invoke(self, available: dict[type, Any]) -> dict[str, Any]:
        return {
            p.name: p.extractor(available[p.source_type])
            for p in self.params
        }
```

The bus's `ParameterInjector` wraps `CallableInvoker` and adds the conversion layer on top:

```python
class ParameterInjector:
    def __init__(self, handler_name: str, signature: Signature):
        plan = build_injection_plan(
            signature,
            [AnnotatedMatcher(source_type=Event), TypeMatcher(Event)],
        )
        self.invoker = CallableInvoker(plan)
        self.conversion_map = self._build_conversion_map(plan)

    def inject_parameters(self, event: Event[Any], **kwargs: Any) -> dict[str, Any]:
        available = {Event: event}
        for param in self.invoker.params:
            if param.name in kwargs:
                LOGGER.warning("Handler '%s' - parameter '%s' in kwargs will be overridden by DI",
                               self.handler_name, param.name)
            try:
                raw_value = param.extractor(available[param.source_type])
                target_type, converter = self.conversion_map[param.name]
                kwargs[param.name] = self.extract_and_convert_parameter(
                    param.name, raw_value, target_type, converter,
                )
            except DependencyError:
                raise
            except Exception as e:
                raise DependencyResolutionError(
                    f"Handler '{self.handler_name}' - failed to extract parameter "
                    f"'{param.name}': {e}"
                ) from e
        return kwargs
```

The `inject_parameters` method signature stays `(event: Event[Any])` — the bus wraps the event in `{Event: event}` internally. Callers of `ParameterInjector` see no change. The `conversion_map` is built from `InjectionParam.target_type` (for type matching/normalization) and `InjectionParam.converter` (for custom conversion — propagated from `AnnotationDetails.converter` by `AnnotatedMatcher`). The existing `extract_and_convert_parameter` logic (Optional handling, TYPE_MATCHER, ANNOTATION_CONVERTER) is unchanged — it just reads from the plan's data structures instead of `self.param_details`.

The bus's error-handling behavior is preserved in `ParameterInjector.inject_parameters`, not in `CallableInvoker`. Specifically: (a) a warning is logged when a DI-injected param name collides with a passed-in kwarg, and (b) non-`DependencyError` exceptions during extraction or conversion are wrapped into `DependencyResolutionError` with a descriptive message, while `DependencyError` subclasses re-raise as-is. `CallableInvoker.invoke()` itself is a thin kwargs builder with no error wrapping — the bus layer adds error normalization on top.

### How a future scheduler consumer would use it

Not implemented in this PR, but the API supports it:

```python
# At registration time
sig = get_typed_signature(predicate)
plan = build_injection_plan(sig, [TypeMatcher(ScheduledJob)])
invoker = CallableInvoker(plan)

# At dispatch time
kwargs = invoker.invoke({ScheduledJob: job})
result = predicate(**kwargs)
```

### How future multi-source predicates would work

```python
class StateValueIs:
    def __init__(self, entity_id: str, value: str): ...

    def __call__(self, states: StateManager) -> bool:
        return states.get(self.entity_id).value == self.value

# Matcher sees `states: StateManager` → TypeMatcher(StateManager) matches
# Dispatch: invoker.invoke({ScheduledJob: job, StateManager: state_manager})
```

## Implementation Preferences

- Use `typing.Protocol` for the `ParameterMatcher` interface.
- Exact-match semantics for `available` dict keys — the caller must use the same type the matcher declared as `source_type`. No `isinstance` fallback during lookup.
- `TypeMatcher.match` uses `issubclass` to detect the annotation (a `RawStateChangeEvent` annotation matches `TypeMatcher(Event)`), but the `InjectionParam.source_type` is always the matcher's target type (not the annotation's specific subclass). This means `available[Event]` is the lookup key regardless of whether the annotation was `Event` or `RawStateChangeEvent`.

## Replacement Targets

| Old code | Replaced by | Action |
|---|---|---|
| `bus/extraction.py:extract_from_annotated` | `AnnotatedMatcher.match` in `di/` | Delete function |
| `bus/extraction.py:extract_from_event_type` | `TypeMatcher(Event)` in bus matcher list | Delete function |
| `bus/extraction.py:extract_from_signature` | `build_injection_plan` in `di/` | Delete function |
| `bus/extraction.py:has_dependency_injection` | (unused — no replacement) | Delete function |
| `bus/extraction.py:validate_di_signature` | `validate_di_signature` in `di/` | Move |
| `event_handling/dependencies.py:AnnotationDetails` | `di/:AnnotationDetails` | Move, widen `T` bound, add `source_type` |
| `event_handling/dependencies.py:identity` | `di/:identity` | Move |

After these moves, `bus/extraction.py` should be empty or deleted entirely. `event_handling/dependencies.py` retains all `D.*` aliases, `ensure_present`, and accessor imports — it imports `AnnotationDetails` and `identity` from `hassette.di`. No backward-compatibility re-export is maintained — `hassette.di` is the canonical import path for `AnnotationDetails` and `identity`.

## Convention Examples

### Protocol pattern

**Source:** `src/hassette/types/types.py:160`

```python
class TriggerProtocol(Protocol):
    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime: ...
    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime | None: ...
    def trigger_label(self) -> str: ...
    def trigger_detail(self) -> str | None: ...
    def trigger_db_type(self) -> str: ...
    def trigger_id(self) -> str: ...
```

### Frozen dataclass with Generic

**Source:** `src/hassette/event_handling/dependencies.py:85`

```python
@dataclass(slots=True, frozen=True)
class AnnotationDetails(Generic[T]):
    extractor: Callable[[T], Any]
    converter: Callable[[Any, Any], Any] | None = None
```

### Extraction test pattern (signature inspection)

**Source:** `tests/integration/test_extraction.py` — `TestSignatureExtraction` class

Tests define inline handler functions with DI annotations, call `get_typed_signature` + `extract_from_signature`, then assert on the returned dict's keys and `AnnotationDetails` values. The pattern: define a handler → extract → assert param names and types.

### Injection test pattern (end-to-end DI)

**Source:** `tests/integration/test_injection.py` — `TestRequiredAnnotations`, `TestMaybeAnnotations` classes

Tests call `extract_from_annotated(D.SomeAlias)` to get an `AnnotationDetails`, then call `details.extractor(event)` with a real event fixture and assert the extracted value matches the event's data. The pattern: extract annotation details → call extractor with event → assert value.

## Alternatives Considered

### Leave extraction in bus/, add scheduler-specific parallel

Keep the bus DI code where it is and build a separate `scheduler/injection.py` with its own plan-building for `ScheduledJob`. This is what the scheduler predicate branch started doing — it led to `_predicate_wants_job` with arity counting, the boolean flag, the dispatch branch, and two rounds of rework. Rejected because it compounds the exact problem this extraction solves.

### Resolver callable instead of dict

Use `Callable[[type], Any]` instead of `dict[type, Any]` for the dispatch API. Research found this adds ceremony (each call site constructs a function instead of a dict literal) without practical benefit for 1-2 source cases. Harder to debug (opaque closures vs. visible dict contents). Rejected per research recommendation.

## Test Strategy

### Existing Tests to Adapt

- `tests/integration/test_extraction.py` — imports `extract_from_annotated`, `extract_from_signature`, `has_dependency_injection`, `validate_di_signature` from `hassette.bus.extraction`. These imports change to `hassette.di` for the functions that moved. Tests that call `extract_from_annotated` directly test via `AnnotatedMatcher.match` instead. Tests that call `extract_from_signature` test via `build_injection_plan` instead. Tests for `has_dependency_injection` are removed (function deleted).
- `tests/integration/test_injection.py` — imports `extract_from_annotated` from `hassette.bus.extraction` (used in ~12 of ~13 tests) and `ParameterInjector` from `hassette.bus.injection`. The `extract_from_annotated` import changes to `hassette.di` (via `AnnotatedMatcher` or a re-exported helper). `ParameterInjector` import path unchanged. Test assertions unchanged — only import paths and call targets for `extract_from_annotated` adapt.
- `tests/integration/test_annotation_conversion.py` — imports `extract_from_annotated` from `hassette.bus.extraction` and `ParameterInjector` from `hassette.bus.injection`. `extract_from_annotated` import changes.
- `tests/integration/test_type_detection.py` — imports `extract_from_annotated` and `extract_from_event_type` from `hassette.bus.extraction` (both deleted per FR#11/FR#13). Update imports to use `AnnotatedMatcher`/`TypeMatcher` from `hassette.di`, or fold assertions into `tests/unit/di/test_matchers.py` if coverage is subsumed.

### New Test Coverage

- **Unit tests for `build_injection_plan`** — verify matcher ordering, unannotated param skipping, empty plan for zero-arg callables, signature validation errors (FR#5, FR#7).
- **Unit tests for `TypeMatcher`** — verify exact type match, subclass match, non-match, `source_type` on returned `InjectionParam` (FR#3).
- **Unit tests for `AnnotatedMatcher`** — verify `Annotated[T, AnnotationDetails]` match, bare callable auto-wrapping into `AnnotationDetails`, warning on invalid metadata, constructor `source_type` propagation, `AnnotationDetails.source_type` override when set, `target_type` set to inner type `T`, non-match for non-Annotated annotations (FR#4, FR#15).
- **Unit tests for `CallableInvoker`** — verify kwargs building from `available` dict, empty plan returns empty dict, `KeyError` on missing source type (FR#6).
- **Integration test: non-bus consumer** — standalone test using `build_injection_plan` + `CallableInvoker` + `TypeMatcher` with a plain dataclass (not Event), proving the shared layer works independently (AC#6).

### Tests to Remove

- Tests for `has_dependency_injection` — function is deleted (unused).

## Documentation Updates

- `docs/pages/core-concepts/bus/dependency-injection.md` — update mkdocstrings cross-reference link from `hassette.event_handling.dependencies.AnnotationDetails` to `hassette.di.AnnotationDetails` (or verify the re-import in `dependencies.py` is visible to mkdocstrings via `__all__`).
- `docs/pages/core-concepts/bus/custom-extractors.md` — same cross-reference link update. Also update the tutorial code snippet (`snippets/dependency-injection/custom_extractor_converter.py`) to import `AnnotationDetails` from `hassette.di` instead of `hassette.event_handling.dependencies`.
- `tools/docs/gen_ref_pages.py` — add `hassette.di` to `PUBLIC_MODULES` so mkdocstrings generates API reference for the new package. Verify `hassette.event_handling.dependencies` still resolves (it retains the `D.*` aliases and re-imports `AnnotationDetails`).

- `tools/docs/check_xref_coverage.py` — update `XREF_MAP["AnnotationDetails"]` from `hassette.event_handling.dependencies.AnnotationDetails` to `hassette.di.AnnotationDetails`.

CI runs `mkdocs build --strict` which fails on unresolved cross-references — these link updates are required to avoid build failures.

## Impact

### Changed Files

- **create** `src/hassette/di/__init__.py` — package init, re-exports public API
- **create** `src/hassette/di/types.py` — `AnnotationDetails` (moved + modified), `InjectionParam`, `ParameterMatcher` Protocol, `identity` (moved)
- **create** `src/hassette/di/plan.py` — `build_injection_plan`, `validate_di_signature` (moved)
- **create** `src/hassette/di/invoker.py` — `CallableInvoker`
- **create** `src/hassette/di/matchers.py` — `TypeMatcher`, `AnnotatedMatcher`
- **modify** `src/hassette/event_handling/dependencies.py` — remove `AnnotationDetails`, `identity` definitions; add imports from `hassette.di`; all `D.*` aliases unchanged in behavior
- **modify** `src/hassette/bus/injection.py` — `ParameterInjector` refactored to use `build_injection_plan` + `CallableInvoker` internally; `inject_parameters` signature unchanged; `Event` import promoted from `TYPE_CHECKING` to runtime (needed as a live value in `TypeMatcher(Event)` and `{Event: event}`)
- **delete** or **empty** `src/hassette/bus/extraction.py` — all functions moved to `di/` or replaced by matchers
- **modify** `src/hassette/bus/listeners.py` — update import of `ParameterInjector` (path unchanged, but extraction imports removed if any)
- **modify** `tests/integration/test_extraction.py` — update imports, adapt to `AnnotatedMatcher`/`build_injection_plan` API
- **modify** `tests/integration/test_injection.py` — update imports if needed
- **modify** `tests/integration/test_annotation_conversion.py` — update `extract_from_annotated` import
- **modify** `tests/integration/test_type_detection.py` — update `extract_from_annotated` and `extract_from_event_type` imports (both functions deleted)
- **create** `tests/unit/di/test_plan.py` — unit tests for `build_injection_plan`, `validate_di_signature`
- **create** `tests/unit/di/test_matchers.py` — unit tests for `TypeMatcher`, `AnnotatedMatcher`
- **create** `tests/unit/di/test_invoker.py` — unit tests for `CallableInvoker`
- **create** `tests/integration/test_di_standalone.py` — integration test proving non-bus usage
- **modify** `tools/docs/gen_ref_pages.py` — remove `hassette.bus.extraction` from `PUBLIC_MODULES`, add `hassette.di`
- **modify** `docs/pages/core-concepts/bus/dependency-injection.md` — update `AnnotationDetails` cross-reference link to `hassette.di`
- **modify** `docs/pages/core-concepts/bus/custom-extractors.md` — update `AnnotationDetails` cross-reference link to `hassette.di`

<!-- Gap check 2026-07-07: 1 gap included — docs/pages/core-concepts/bus/handlers.md:58 cross-ref link → T04 -->

### Behavioral Invariants

- `ParameterInjector.inject_parameters(event, **kwargs)` returns identical results for all existing handler signatures.
- All `D.*` type aliases produce identical extracted values for all event types.
- `HandlerInvoker.invoke(event)` dispatches handlers identically.
- The bus dispatch pipeline (`BusService.dispatch` → `HandlerInvoker.invoke`) is unchanged.
- Extractor/converter exceptions in the bus are normalized to `DependencyResolutionError` (non-`DependencyError`) or re-raised as-is (`DependencyError` subclasses). The kwarg collision warning is preserved.

### Blast Radius

Limited to internal framework code. No user-facing API changes. The `D.*` aliases, bus registration methods (`on_state_change`, `on_attribute_change`, etc.), and handler authoring patterns are all unchanged. The only observable difference is import paths for internal test code that directly imports extraction functions.

## Open Questions

None — all design decisions resolved during discovery and research.
