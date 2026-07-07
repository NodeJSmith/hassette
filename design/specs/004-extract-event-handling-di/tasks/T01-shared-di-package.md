---
task_id: "T01"
title: "Create shared di/ package with types, matchers, plan, and invoker"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "FR#7", "FR#15", "AC#3", "AC#6", "AC#7"]
---

## Summary
Create the new `src/hassette/di/` package containing all shared DI primitives: `AnnotationDetails` (moved + modified), `InjectionParam`, `ParameterMatcher` Protocol, `TypeMatcher`, `AnnotatedMatcher`, `CallableInvoker`, `build_injection_plan`, `validate_di_signature`, and `identity`. This is the foundational task — everything else builds on it.

## Target Files
- create: `src/hassette/di/__init__.py`
- create: `src/hassette/di/types.py`
- create: `src/hassette/di/matchers.py`
- create: `src/hassette/di/plan.py`
- create: `src/hassette/di/invoker.py`
- create: `tests/unit/di/__init__.py`
- create: `tests/unit/di/test_matchers.py`
- create: `tests/unit/di/test_plan.py`
- create: `tests/unit/di/test_invoker.py`
- create: `tests/integration/test_di_standalone.py`
- read: `src/hassette/event_handling/dependencies.py`
- read: `src/hassette/bus/extraction.py`
- read: `src/hassette/events/type_checks.py`
- read: `src/hassette/utils/type_utils.py`
- read: `src/hassette/types/types.py`

## Prompt
Create the `src/hassette/di/` package with five modules. Reference the design doc at `design/specs/004-extract-event-handling-di/design.md` — Architecture section for code structure, FRs #1-7 and #15 for requirements.

### `di/types.py`
Move `AnnotationDetails` from `src/hassette/event_handling/dependencies.py` and `identity` function. Changes to `AnnotationDetails`:
- Widen the `T` TypeVar from `bound=Event[Any]` to unbounded: `T = TypeVar("T")`
- Add field: `source_type: type[T] | None = None` (must come after `converter` to keep backward compat with positional construction)

Create `InjectionParam` frozen dataclass with fields: `name: str`, `source_type: type`, `target_type: Any`, `extractor: Callable[[Any], Any]`, `converter: Callable[[Any, Any], Any] | None = None`.

Create `ParameterMatcher` Protocol with single method: `def match(self, param: inspect.Parameter) -> InjectionParam | None: ...`

### `di/matchers.py`
`TypeMatcher` — constructed with `match_type: type`. Its `match()` method:
1. Gets the annotation from the parameter (skip if `Parameter.empty`)
2. Unwraps parameterized generics via `get_origin(annotation) or annotation` before the `issubclass` check (matching `is_event_type` behavior in `src/hassette/events/type_checks.py`)
3. If annotation is a subclass of `match_type`, returns `InjectionParam(name=param.name, source_type=self.match_type, target_type=annotation, extractor=identity)`
4. Otherwise returns `None`

`AnnotatedMatcher` — constructed with `source_type: type`. Its `match()` method:
1. Checks `is_annotated_type(annotation)` from `hassette.utils.type_utils`
2. Calls `get_type_and_details(annotation)` to get `(inner_type, metadata)`
3. If metadata is `AnnotationDetails` — use it directly
4. If metadata is a bare callable — wrap in `AnnotationDetails(extractor=metadata)`
5. If metadata is neither — emit a `warn()` and return `None`
6. Normalize inner_type via `normalize_annotation`
7. Return `InjectionParam(name=param.name, source_type=details.source_type or self.source_type, target_type=normalized_inner_type, extractor=details.extractor, converter=details.converter)`

### `di/plan.py`
`validate_di_signature(signature)` — move from `src/hassette/bus/extraction.py`. Raises `DependencyInjectionError` for `VAR_POSITIONAL` or `POSITIONAL_ONLY` params.

`build_injection_plan(sig, matchers)` — walks parameters, tries each matcher in order, returns `tuple[InjectionParam, ...]`. See design doc Architecture > Plan building for pseudocode.

### `di/invoker.py`
`CallableInvoker` — frozen dataclass with `params: tuple[InjectionParam, ...]`. Method `invoke(available: dict[type, Any]) -> dict[str, Any]` builds kwargs by looking up `available[param.source_type]` and calling `param.extractor(source)`. Does NOT store or call the target callable.

### `di/__init__.py`
Re-export all public symbols: `AnnotationDetails`, `InjectionParam`, `ParameterMatcher`, `TypeMatcher`, `AnnotatedMatcher`, `CallableInvoker`, `build_injection_plan`, `validate_di_signature`, `identity`.

### Tests
Unit tests for each module. Integration test (`test_di_standalone.py`) using `build_injection_plan` + `CallableInvoker` + `TypeMatcher` with a plain dataclass (not Event) to prove the shared layer works independently of the bus.

## Focus
- `identity` function is currently at `src/hassette/event_handling/dependencies.py:118` — a simple `return x` function.
- `AnnotationDetails` is at `dependencies.py:85` — `@dataclass(slots=True, frozen=True)` with `Generic[T]`. The `T` TypeVar is defined at line 81: `T = TypeVar("T", bound=Event[Any])`. Remove that bound.
- `validate_di_signature` is at `src/hassette/bus/extraction.py:59` — copy the logic exactly.
- `extract_from_annotated` logic (extraction.py:11-31) is what `AnnotatedMatcher.match()` absorbs — note the bare callable wrapping at line 28 and the warning at line 30.
- `is_event_type` at `src/hassette/events/type_checks.py:7` does `base_type = get_origin(annotation) or annotation` before `issubclass`. `TypeMatcher` must replicate this unwrapping.
- Follow the Protocol pattern from `TriggerProtocol` at `src/hassette/types/types.py:160`.
- Import `DependencyInjectionError` from `hassette.exceptions`.
- Import `get_type_and_details`, `is_annotated_type`, `normalize_annotation` from `hassette.utils.type_utils`.
- The `ensure_present` helper stays in `event_handling/dependencies.py` — do not move it.
- Event fixtures for the integration test are session-scoped from `hassette.test_utils.fixtures` (registered globally via `tests/conftest.py`).

## Verify
- [ ] FR#1: `from hassette.di import AnnotationDetails, CallableInvoker, build_injection_plan, TypeMatcher, AnnotatedMatcher, ParameterMatcher, InjectionParam, validate_di_signature, identity` resolves correctly
- [ ] FR#2: `ParameterMatcher` is a `typing.Protocol` with `match(param) -> InjectionParam | None`
- [ ] FR#3: `TypeMatcher(Event)` matches `RawStateChangeEvent` annotation (subclass), unwraps parameterized generics, produces correct `InjectionParam` with `source_type=Event, target_type=RawStateChangeEvent`
- [ ] FR#4: `AnnotatedMatcher` matches `Annotated[T, AnnotationDetails(...)]`, auto-wraps bare callables, warns on invalid metadata, propagates `source_type` and `converter`
- [ ] FR#5: `build_injection_plan` walks params, tries matchers in order, skips unannotated, returns tuple of `InjectionParam`
- [ ] FR#6: `CallableInvoker.invoke({SomeType: obj})` returns kwargs dict; empty plan returns empty dict; `KeyError` on missing source
- [ ] FR#7: `validate_di_signature` raises `DependencyInjectionError` for `*args` and positional-only params
- [ ] FR#15: `AnnotatedMatcher` uses `AnnotationDetails.source_type` when set, falls back to constructor `source_type` when `None`
- [ ] AC#3: The import statement from FR#1 resolves correctly
- [ ] AC#6: Standalone integration test proves non-Event type resolution through `TypeMatcher`
- [ ] AC#7: Unit test proves `AnnotatedMatcher` matching and `InjectionParam` production
