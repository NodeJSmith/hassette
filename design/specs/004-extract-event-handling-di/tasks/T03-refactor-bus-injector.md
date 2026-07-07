---
task_id: "T03"
title: "Refactor bus ParameterInjector to use shared layer, delete extraction.py"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#10", "FR#11", "FR#12", "FR#13", "FR#14", "AC#2", "AC#4", "AC#8"]
---

## Summary
Refactor the bus `ParameterInjector` to use `build_injection_plan` and `CallableInvoker` from the shared `di/` package. Delete all functions from `bus/extraction.py` (or delete the file entirely). The `inject_parameters` method signature is unchanged — the bus wraps the event in `{Event: event}` internally and iterates params individually for per-parameter error attribution.

## Target Files
- modify: `src/hassette/bus/injection.py`
- delete: `src/hassette/bus/extraction.py`
- read: `src/hassette/bus/__init__.py`
- read: `src/hassette/bus/listeners.py`
- read: `src/hassette/di/__init__.py`
- read: `src/hassette/di/invoker.py`
- read: `src/hassette/di/plan.py`
- read: `src/hassette/di/matchers.py`

## Prompt
Refactor `src/hassette/bus/injection.py` (`ParameterInjector`) to use the shared DI layer. Reference design doc Architecture > Dispatch section for the `ParameterInjector` pseudocode.

### Changes to `injection.py`

1. Remove the import: `from .extraction import extract_from_signature`
2. Add imports: `from hassette.di import AnnotatedMatcher, TypeMatcher, CallableInvoker, build_injection_plan`
3. Promote `Event` from `TYPE_CHECKING`-only to a runtime import (needed as a live value in `TypeMatcher(Event)` and `{Event: event}`). Move it from the `if typing.TYPE_CHECKING:` block to the top-level imports.
4. In `__init__`:
   - Replace `self.param_details = extract_from_signature(signature)` with:
     ```python
     plan = build_injection_plan(signature, [AnnotatedMatcher(source_type=Event), TypeMatcher(Event)])
     self.invoker = CallableInvoker(plan)
     ```
   - Build a `conversion_map` from the plan: `{param.name: (param.target_type, param.converter) for param in plan}`
5. In `inject_parameters(event, **kwargs)`:
   - Build `available = {Event: event}`
   - Iterate `self.invoker.params` individually (NOT `self.invoker.invoke()`), calling each `param.extractor(available[param.source_type])` inside a per-parameter `try/except` that preserves the parameter name in error messages
   - Keep the kwarg collision warning
   - Keep the `DependencyError` pass-through and `DependencyResolutionError` wrapping
   - Call `self.extract_and_convert_parameter` with the raw value, target_type, and converter from the conversion_map
6. The `extract_and_convert_parameter` method stays — it handles Optional, TYPE_MATCHER, and ANNOTATION_CONVERTER. Its signature may change to accept `raw_value` instead of `event` (since extraction now happens in the param loop above), but keep the same conversion logic.

### Delete `extraction.py`

Delete `src/hassette/bus/extraction.py` entirely — all its functions have moved to `di/` or are replaced by matchers. If `bus/__init__.py` imports anything from `extraction`, remove that import.

### Verify no other imports

Grep for `from hassette.bus.extraction` in `src/` — the only source consumer is `injection.py` (the one we're changing). Test imports are handled in T04.

## Focus
- Current `injection.py` has `ParameterInjector.__init__` at line 29 calling `extract_from_signature(signature)` at line 43.
- Current `inject_parameters` at line 49 iterates `self.param_details` (a dict of `{name: (type, AnnotationDetails)}`).
- Current `extract_and_convert_parameter` at line 93 takes `event, param_name, param_type, extractor, converter` — the `event` parameter is used to call `extractor(event)`. After refactoring, the raw value is already extracted, so this method should take `raw_value` directly instead of `event + extractor`.
- `bus/__init__.py` does NOT re-export `extraction` or `injection` — they're internal. Check but expect no change needed.
- `listeners.py:9` imports `ParameterInjector` from `hassette.bus.injection` — this import path is unchanged.
- `listeners.py:235` constructs `ParameterInjector(handler_name, signature)` — this call site is unchanged (constructor signature stays the same).
- Current `injection.py:80-89` logs `LOGGER.error(...)` before raising `DependencyResolutionError`. The design pseudocode omits this log call — preserve it in the refactored version to avoid an observability regression.

## Verify
- [ ] FR#10: `ParameterInjector` uses `build_injection_plan` + `CallableInvoker` at construction, iterates params individually at dispatch
- [ ] FR#11: `extract_from_event_type` no longer exists in the codebase
- [ ] FR#12: `has_dependency_injection` no longer exists in the codebase
- [ ] FR#13: `extract_from_annotated` no longer exists in the codebase
- [ ] FR#14: `extract_from_signature` no longer exists in the codebase
- [ ] AC#2: All existing handler and bus integration tests pass without modification
- [ ] AC#4: `bus/extraction.py` contains no extraction functions or is deleted
- [ ] AC#8: Pyright reports no new errors on changed files
