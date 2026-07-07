# Context: Extract Shared DI Layer

## Problem & Motivation
The bus DI pipeline inspects handler signatures, builds extraction plans, and dispatches kwargs — a generic pattern locked behind Event-specific method signatures. The scheduler needs the same pattern for predicate injection with ScheduledJob, and future StateValueIs predicates need multiple sources injected simultaneously. Without a shared layer, each new consumer builds a parallel bespoke mechanism. The scheduler predicate branch already demonstrated this failure mode with arity-counting logic.

## Visual Artifacts
None.

## Key Decisions
1. The shared layer lives in `src/hassette/di/` as a new top-level package.
2. Dispatch API uses `dict[type, Any]` for multi-source resolution (research-backed — every surveyed DI framework uses type-keyed lookup internally).
3. `ParameterMatcher` is a `typing.Protocol` with a single `match()` method. Two built-in implementations: `TypeMatcher` and `AnnotatedMatcher`.
4. `InjectionParam` is the plan data structure — carries `name`, `source_type`, `target_type`, `extractor`, and optional `converter`.
5. `AnnotationDetails` moves to `di/` with the `T` TypeVar bound widened from `Event[Any]` to unbounded. A `source_type` field is added (default `None`).
6. `hassette.di` is the canonical import path for `AnnotationDetails` and `identity` — no backward-compat re-export.
7. The bus `ParameterInjector` iterates `CallableInvoker.params` individually (not batched `invoke()`) to preserve per-parameter error attribution.
8. `CallableInvoker.invoke()` is a thin kwargs builder — no error wrapping. The bus adds error normalization on top.
9. `TypeMatcher` replaces `extract_from_event_type`. `AnnotatedMatcher` replaces `extract_from_annotated`.
10. `AnnotatedMatcher` handles bare callable metadata (auto-wraps into `AnnotationDetails`).

## Constraints & Anti-Patterns
- Do NOT change the public `D.*` type alias API — app authors import `D.StateNew`, `D.EntityId`, etc.
- Do NOT modify the bus dispatch call chain beyond `ParameterInjector` internals.
- Do NOT add scheduler code — scheduler adoption happens in a separate branch.
- Do NOT add predicate normalization (`AllOf`, `AnyOf`).
- `AnnotationDetails.converter` remains bus-specific — `CallableInvoker` does not handle conversion.
- Exact-match semantics for `available` dict keys — no `isinstance` fallback during lookup.

## Design Doc References
- `## Architecture` — data structures, plan building, dispatch, bus ParameterInjector refactor
- `## Replacement Targets` — table mapping old code to new code with actions
- `## Edge Cases` — zero-arg, unannotated params, matcher ordering, missing source type, unmatched annotated params
- `## Implementation Preferences` — Protocol, exact-match, TypeMatcher issubclass behavior
- `## Test Strategy` — existing tests to adapt, new coverage, tests to remove

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
