# Design: Dumb State Models + Codec-Owned Conversion (clean global registries)

**Date:** 2026-06-23
**Status:** archived
**Scope-mode:** hold
**Research:** design/adrs/0003-dumb-state-models-codec-owned-conversion.md, design/specs/084-dumb-state-models-codec-conversion/challenge-results.md

## Problem

The `conversion ↔ models` runtime import cycle (#892) is the last open cycle under #1079. The other three fell to mechanical fixes in #1120; this one was deferred because mechanical fixes only relocate it. The cycle is one back-edge:

```
src/hassette/models/states/base.py:10
    from hassette.conversion import TYPE_REGISTRY, register_state_converter
```

`base.py` reaches up into the conversion layer for two reasons: `register_state_converter` in `__init_subclass__` (state subclasses self-register), and `TYPE_REGISTRY.convert(...)` in the `_validate_domain_and_state` validator (scalar value coercion). The three `conversion → models` lazy imports are the legitimate direction and are only lazy because this back-edge would otherwise close the loop at package-init time.

The root cause is that a Pydantic `@model_validator` is a classmethod with nothing to inject into, so a self-validating model *must* reach for an ambient global to convert its value. Secondary symptoms of the same arrangement: the implicit load-order contract (`conversion/validation.py:92` warns "STATE_REGISTRY is empty"), and convert-time self-mutation (`TypeRegistry.convert` auto-registers a constructor converter into the global map on a cache miss, `type_registry.py:200-215`), which is the sole driver of the type-registry test `snapshot`/`restore` dance.

This design moves conversion *behavior* out of the model and into a codec, which breaks the cycle, and tidies the registry globals — without introducing per-instance registries.

### Why not per-instance registries

ADR-0003 originally proposed per-instance registries. The challenge (`challenge-results.md`) and direct code verification killed that direction:

- **Production is single-instance.** `context.set_global_hassette` raises `RuntimeError` if a different `Hassette` is already set (`context.py:41-43`) — concurrent instances are forbidden. There is no production scenario two registries would isolate.
- **Per-instance doesn't isolate tests anyway.** The pollution source is `BaseState.__init_subclass__` writing a process-global target; a per-instance registry built from that global catalog still sees every prior test's class. Isolation still requires resetting the global, so per-instance adds machinery without removing the fixture.

So the registries stay clean process-global singletons. The state-side reset fixture stays (it is irreducible while `__init_subclass__` auto-registration is a documented feature); the type-side reset is *removed* by fixing the convert-on-miss self-write.

## Goals

- The `conversion ↔ models` runtime cycle is broken; the subpackage runtime import graph is acyclic. `models/states` imports nothing from `conversion`.
- State models are dumb data: shape plus a `value_type` declaration, no conversion behavior. `__init_subclass__` registration stays but targets a `models`-layer catalog, not `conversion`.
- A codec owns the dict → State path (domain resolution, value coercion, construction) and the known-model coercion path that `state_manager` uses.
- The convert-on-miss self-write is removed; `TypeRegistry` becomes a read-only catalog after init, eliminating the type-side `snapshot`/`restore`.
- The public extension API (`register_simple_type_converter`, `register_type_converter_fn`, module-level custom `BaseState` subclasses, `register_state_converter`, `TYPE_REGISTRY`/`STATE_REGISTRY`) keeps working unchanged.
- A `models-no-conversion` boundary rule self-proves the break. `check_module_boundaries.py` / `check_lazy_imports.py` pass; pyright clean; suite green.

## Non-Goals

- **No per-instance registries.** Registries remain clean global singletons (decision reversed from ADR-0003; rationale above and in the ADR's revised Decision).
- **No change to `__init_subclass__` auto-registration as a public behavior** — module-level custom state classes keep working with no explicit call.
- No change to per-domain model field shapes or their datetime `field_validator`s.
- No change to the DI/annotation-conversion behavior app authors observe (`D.StateNew[...]`).
- Not eliminating the state-side test reset fixture — irreducible while auto-registration stays (named as a known limit, not a goal).

## User Scenarios

The actors are framework maintainers and app authors; this is internal architecture with a public-API-compatibility surface.

### Maintainer: framework developer
- **Goal:** add or modify state models and conversion logic without fighting an import cycle.
- **Context:** `src/hassette/models/states/` and `src/hassette/conversion/`.

#### Add a new state domain
1. **Define a `BaseState` subclass at module level**
   - Sees: the model needs only fields + `value_type`; it imports the `models`-layer state-class catalog for `register_state_converter`, never `conversion`.
   - Decides: nothing about conversion wiring — `__init_subclass__` registers it automatically (at any subclass depth).
   - Then: the domain resolves through the codec.

### App author: Hassette user
- **Goal:** register a custom type converter or define a custom state class, exactly as documented today.
- **Context:** their app module, using the public API re-exported from `hassette`.

#### Register a custom converter
1. **Call `register_simple_type_converter(...)`**
   - Sees: identical public API and identical effect — one global registry, so the running app sees the converter.
   - Decides: nothing new.
   - Then: the converter is in `TYPE_REGISTRY`, used by every conversion.

## Functional Requirements

- **FR#1** `models/states/base.py` (and the rest of `models/states/`) import no symbol from `hassette.conversion` at runtime (including lazy/in-function imports).
- **FR#2** `BaseState` subclasses validate already-typed values — the model performs no registry lookup or scalar value coercion during validation.
- **FR#3** `__init_subclass__` registers every `BaseState` subclass (at any inheritance depth) into a `models`-layer state-class catalog, with no import of `conversion`.
- **FR#4** The codec converts a raw HA state dict to the correct typed state (domain resolution + value coercion + construction), with fallback to `BaseState` for unregistered domains — preserving today's `try_convert_state` behavior.
- **FR#5** The codec exposes a known-model coercion path: given a target state class and a raw state dict, coerce the value against `value_type` and construct — replacing the model's self-coercion at `DomainStates._validate_or_return_from_cache` (`state_manager.py:87`).
- **FR#6** Scalar value coercion produces the same typed results as today's `BaseState` validator path, for every domain `value_type`.
- **FR#7** A coercion failure on the `state_manager`/`api` state paths surfaces as `UnableToConvertStateError(entity_id, model)` — the same type and attached `entity_id` as today.
- **FR#8** `TypeRegistry.convert` no longer mutates the registry on a cache miss; the conversion result is unchanged.
- **FR#9** The public names `from hassette import TYPE_REGISTRY, STATE_REGISTRY, register_simple_type_converter, register_type_converter_fn` and `from hassette.conversion import register_state_converter` keep working and affect/read the one global registry the framework uses.
- **FR#10** `check_module_boundaries.py` enforces a `models-no-conversion` rule; `check_lazy_imports.py` passes with the cycle-related `# lazy-import:` annotations removed.

## Edge Cases

- **`unknown` / `unavailable` states:** the `is_unknown`/`is_unavailable` normalization and `state → None` handling stay in the model validator (shape logic), not the codec.
- **Unregistered domain:** codec falls back to `BaseState` (unchanged, FR#4).
- **`annotation_converter` self-package import:** `annotation_converter.py:39` (`from hassette.conversion import TYPE_MATCHER, TYPE_REGISTRY`) cannot hoist to a top-level self-package import (the symbols are created in `conversion/__init__.py:7-8` *after* `__init__` imports `annotation_converter`). Relocate the `TYPE_REGISTRY`/`TYPE_MATCHER`/`STATE_REGISTRY`/`ANNOTATION_CONVERTER` singleton *definitions* into their defining submodules; `__init__` re-exports them (public API unchanged). Then `annotation_converter` imports them from submodules at top-level.
- **Convert-on-miss memoization removed:** `test_type_registry.py::TestConstructorFallbackCache` asserts the cache *grows*; those assertions become "conversion succeeds" assertions. Performance is unaffected — both the old miss-branch and the old cache-hit branch call the same `to_type(value)` constructor (`type_registry.py:201` vs `:220`); the memo only avoided a dict insert.
- **State-class test pollution:** still reset between tests via the (simplified, state-only) catalog reset fixture. Type-registry pollution no longer occurs (FR#8), so the type-side fixture is deleted.

## Acceptance Criteria

- **AC#1** `grep` shows zero `hassette.conversion` imports anywhere in `models/states/` (FR#1, FR#3); `check_module_boundaries.py` reports `models-no-conversion` passing (FR#10).
- **AC#2** `check_lazy_imports.py` passes with the conversion-side cycle annotations removed. The three in-method imports become module-level, by distinct causes: (a) `annotation_converter.py:40` (`from hassette.models.states import BaseState`) and `state_registry.py:90` (the `BaseState` fallback import) are the legitimate `conversion → models` direction — hoistable once FR#1 holds (models stops importing conversion); (b) `annotation_converter.py:39` (`from hassette.conversion import TYPE_MATCHER, TYPE_REGISTRY`) is a self-package import that hoists only after the singleton relocation in Edge Cases. The standalone `# lazy-import:` comments at `:38` and the inline one at `:40` are deleted with their imports. `validation.py:77` is retained (load-order note, not a cycle).
- **AC#3** A characterization test asserts the codec produces identical typed values to the pre-change `model_validate` path across all domain `value_type`s (FR#4, FR#6) — captured before the refactor, green after.
- **AC#4** A test asserts the `self.states.<domain>[...]` / domain-iteration path (through `state_manager.py:87`) returns coerced typed values (e.g. `BoolBaseState` domains yield `bool`, not `"on"`) (FR#5, FR#6).
- **AC#5** A test asserts a coercion failure on the state path raises `UnableToConvertStateError` carrying the `entity_id` (FR#7).
- **AC#6** The public-API docs snippets (`type-registry/simple_registration.py`, `bus/.../custom_type_converter.py`, `custom-states.md`) type-check and behave identically (FR#9).
- **AC#7** No `TypeRegistry.snapshot`/`restore` references remain anywhere, and `StateRegistry.snapshot`/`restore` are gone (replaced by the state-catalog leaf's reset primitive); the `tests/conftest.py` isolation fixture resets only the state-class catalog (FR#8).
- **AC#8** Full unit + integration suite green; pyright clean; `check_module_boundaries.py` and `check_lazy_imports.py` pass.

## Key Constraints

- **No `from __future__ import annotations`** (project ban). The fix is structural.
- **The cycle is broken by moving behavior, not by relocating service classes** (unlike #1120's `SchedulerService`/`StateProxy` inversions).
- **Public names are load-bearing:** the imports in FR#9 must keep working; ~10 docs pages depend on them. Where a symbol's defining module moves, re-export from its old public location.
- **The model keeps its datetime/alias/domain/unknown-unavailable validators** — only the `TYPE_REGISTRY.convert` coercion and the `register_state_converter` *target* change.

## Dependencies and Assumptions

- Assumes `__init_subclass__` remains the registration mechanism (it fires for all subclass depths — `LightState(BoolBaseState)` triggers it — so it reaches the ~40 domain leaves that a bare `BaseState.__subclasses__()` scan would miss).
- Assumes the existing `hassette.state_registry`/`type_registry` properties (`core.py:438-443,445-450`) stay as accessors over the global singletons — no per-instance build.
- Internal-only; no HA-protocol or schema changes; no persisted data.

## Architecture

Target downward DAG:

```
types / const            StateValueT, enums
   ↑
models/states            Pydantic shapes + value_type + the state-class catalog
  ├─ registry leaf       STATE_CATALOG (domain→class dict) + register_state_converter + StateKey
  └─ base.py / domains   dumb data; __init_subclass__ → registry leaf (same subpackage)
   ↑
conversion (codec)       TYPE_REGISTRY (+ converters), TYPE_MATCHER, AnnotationConverter,
                         StateRegistry/try_convert_state, known-model coercion; reads the catalog + models
   ↑
consumers                bus DI, state_manager, api (via hassette.*_registry accessors over the globals)
```

### Dumb models (`base.py`)

- Delete the value-coercion `try/except` from `_validate_domain_and_state` (`base.py:174-180`). The codec coerces before constructing; the model validates an already-typed `value`. Keep domain extraction, `unknown`/`unavailable` normalization, datetime validators, and the `state`/`value` alias.
- Repoint `__init_subclass__`: `register_state_converter` now lives in the `models/states` registry leaf, not `conversion`. The call stays; only its import source changes.
- Drop the now-dead `UnableToConvertValueError` from `base.py:11` (used only in the removed block); keep `NoDomainAnnotationError`.
- Result: `base.py` imports only `types`, `exceptions` (`NoDomainAnnotationError`), `utils.date_utils`, `pydantic`, `whenever`, and the sibling registry leaf — none of which import `conversion`. `models/states` is a leaf relative to `conversion`.

### State-class catalog (new `models/states` leaf)

Extract the shared `domain → class` map (today `StateRegistry._registry`, a `ClassVar`) plus `register_state_converter`, `resolve`, and `StateKey` into a `models/states` registry module. `__init_subclass__` writes it; the codec's `StateRegistry` reads it. `register_state_converter` is re-exported from `conversion` so existing import paths hold (FR#9). (`register_state_converter`/`StateKey` are not part of the top-level `hassette` public surface today; FR#9 requires `register_state_converter` only from `hassette.conversion`, so they are not added to `hassette/__init__.py`.) This keeps `StateRegistry` (the rich conversion API used as `STATE_REGISTRY`) a single object in the codec while its backing dict lives below the codec, so `models` never imports `conversion`.

### Codec owns dict → State and known-model coercion

The conversion package is the codec. `try_convert_state` (FR#4) keeps its behavior; the three lazy `BaseState` imports become top-level (legit `conversion → models`). Add the known-model coercion entry point (FR#5): given a `state_class` and raw dict, look up `state_class.value_type`, coerce via `TYPE_REGISTRY` (the pattern `api.py:747` already uses), and construct. `DomainStates._validate_or_return_from_cache` (`state_manager.py:87`, `self._model.model_validate(state)`) calls this entry point instead.

Error handoff (FR#7): today `DomainStates._validate_or_return_from_cache` catches the validator's `ValidationError` at `:88` and re-raises `UnableToConvertStateError(entity_id, self._model)` at `:89`. After the move, coercion happens in the codec, which **raises `UnableToConvertStateError(entity_id, state_class)` itself** (reusing the existing `conversion_with_error_handling` wrapper that `try_convert_state` already uses at `state_registry.py:152-176`). The caller's `try/except ValidationError` at `:88-89` is therefore **removed** — the codec owns the wrapping, and a stray `ValidationError` from constructing an already-typed value would now be a genuine bug, not an expected coercion failure. The test at AC#5 pins this.

**Sequencing (implementer note):** build the FR#5 codec entry point and route `:87` through it *first*; only then remove the `except ValidationError` at `:88-89`. Removing the catch before the codec raises `UnableToConvertStateError` would open a regression window where coercion failures escape as bare `ValidationError`. This ordering belongs in the plan's task sequence.

### TypeRegistry stays a clean global; stop the self-write

`TYPE_REGISTRY`/`STATE_REGISTRY` stay process-global singletons. Fix `TypeRegistry.convert` (`type_registry.py:200-215`) to perform the constructor conversion **without** registering the result — the registry becomes read-only after its standard converters load at import. Remove `TypeRegistry.snapshot`/`restore`. The `hassette.state_registry`/`type_registry` accessors keep returning the globals. No active-context routing, no per-instance build.

### Singleton relocation (clears the `annotation_converter:39` lazy import)

Move the `TYPE_REGISTRY`/`TYPE_MATCHER`/`STATE_REGISTRY`/`ANNOTATION_CONVERTER` instances from `conversion/__init__.py:7-10` into their defining submodules; `__init__` re-exports them (public surface unchanged). `annotation_converter` then imports `TYPE_REGISTRY`/`TYPE_MATCHER` from submodules at top-level instead of the self-package lazy import.

## Replacement Targets

- **`BaseState._validate_domain_and_state` value coercion** (`base.py:174-180`) → codec coercion. Remove the `try/except` block.
- **`UnableToConvertValueError` import in `base.py`** (`base.py:11`) → now dead (used only in the removed block); drop it. Keep `NoDomainAnnotationError`.
- **`register_state_converter` import in `base.py`** (`base.py:10`) → import from the new `models/states` registry leaf. Repoint; drop the `TYPE_REGISTRY` import entirely (the dumb model never coerces).
- **`register_state_converter`, `StateKey`, the domain→class dict, and `resolve`** (currently in `conversion/state_registry.py`) → move to the new `models/states/registry.py` leaf. The `StateRegistry` *class* (the rich conversion API: `try_convert_state`, `conversion_with_error_handling`, `__contains__`, `items`/`values`/`keys`) **stays in `conversion`** and reads the leaf's dict. Re-export `register_state_converter`/`StateKey` from `conversion` so existing import paths hold (FR#9) — not from top-level `hassette` (they are not exported there today).
- **`StateRegistry._registry` `ClassVar`** (`state_registry.py:46`) → becomes the catalog dict owned by the `models/states` leaf; `StateRegistry` reads it.
- **`StateRegistry.snapshot`/`restore`** (`state_registry.py:196-203`) → removed; the state-catalog leaf exposes a reset/snapshot primitive instead, used by the test fixture (see Test Strategy).
- **`TypeRegistry.convert` self-registration on miss** (`type_registry.py:205`) → removed.
- **`TypeRegistry.snapshot`/`restore`** (`type_registry.py:266-274`) → removed (no longer needed once the self-write stops).
- **Singleton definitions in `conversion/__init__.py:7-10`** (`TYPE_MATCHER`, `TYPE_REGISTRY`, `STATE_REGISTRY`, `ANNOTATION_CONVERTER`) → moved to their defining submodules, re-exported from `__init__`.
- **Direct `XState.model_validate(raw_dict)` in tests** → a `test_utils` codec helper.

## Migration

No persisted data changes — registries are in-memory. Code-shape only: conversion behavior moves from the model into the codec, so raw-dict → State goes through the codec rather than `Model.model_validate(raw_ha_dict)`. Internal callers and tests migrate to the codec entry points. The public extension API is preserved, so no app-author migration. Pre-1.0; internal break acceptable.

## Convention Examples

### State-dict builder (test convention to extend)

**Source:** `src/hassette/test_utils/helpers.py`

```python
def make_state_dict(
    entity_id: str,
    state: str,
    attributes: dict[str, Any] | None = None,
    last_changed: str | None = None,
    last_updated: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Factory for creating state dictionary in Home Assistant format."""
    now = _date_utils.now().format_iso()
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes or {},
        "last_changed": last_changed or now,
        "last_updated": last_updated or now,
        "context": context or {"id": str(uuid4()), "parent_id": None, "user_id": None},
    }
```

The new codec helper (returning a typed state) sits alongside these dict builders — tests call `make_*_state_dict(...)` then the codec helper, replacing `XState.model_validate(dict)`.

### Known-model coercion already done right elsewhere

**Source:** `src/hassette/api/api.py:747`

```python
return self.hassette.type_registry.convert(state, model.value_type)
```

This is the exact value-coercion the codec's known-model path (FR#5) generalizes; the model validator currently duplicates it the wrong way.

## Alternatives Considered

- **Per-instance registries (ADR-0003 original B2).** Rejected after verification: production is single-instance (`context.py:43`), and per-instance does not isolate tests because the pollution is at the process-global `__init_subclass__`/catalog level. Adds active-context routing, ClassVar→instance migration, and DI-path threading to solve nothing. Full analysis in `challenge-results.md` Findings 1–7 and the ADR's revised Decision.
- **Smart models, registries as a leaf (ADR-0003 A).** Keeps the model validator coercing via a leaf registry. Smaller, but keeps the model owning conversion and keeps the convert-on-miss self-write. The chosen design is barely larger and removes both.
- **Drop `__init_subclass__` for explicit registration.** Would fully eliminate the state reset fixture, but breaks the documented "module-level custom state just works" DX (`custom-states.md`). Rejected — the fixture is a smaller cost than the DX regression.
- **Do nothing.** Leaves a static cycle blocking #633. Rejected.

## Test Strategy

### Existing Tests to Adapt
- `tests/unit/conftest.py:97`, `tests/unit/test_sync_entity_facade.py:41,52`, `tests/unit/test_entity_coroutine_conversion.py:51`, `tests/integration/test_sync_facades.py:125`, `tests/unit/test_api_helper_models.py:328`, `tests/integration/test_models.py:154` — replace `XState.model_validate(raw_dict)` with the codec helper.
- `tests/unit/test_state_manager.py:118,146,158` — spies on `LightState.model_validate`; re-point at the codec coercion path.
- `tests/unit/test_type_registry.py::TestConstructorFallbackCache` (lines ~32-100) — drop the `conversion_map`-growth assertions and the class-scoped `_isolate_registry` fixture; assert conversion succeeds instead (FR#8).
- `tests/unit/conversion/test_registry_validation.py:28,38,122,149` — uses `restore({})`; for the state side, build/clear via the catalog reset; the `TypeRegistry.restore` calls are removed with the method.
- `tests/conftest.py:232-238` `_isolate_registries` — reduce to resetting only the state-class catalog (type-registry no longer pollutes). Keep it autouse for the state side.
- `tests/unit/test_state_registry.py`, `tests/unit/test_type_utils.py` — already use `try_convert_state`; verify green.

### New Test Coverage
- Characterization: codec output equals pre-change `model_validate` output across all domain `value_type`s (AC#3) — write and green *before* the refactor (the pin).
- `self.states.<domain>[...]` returns coerced values through `state_manager.py:87` (AC#4).
- Coercion failure on the state path raises `UnableToConvertStateError` with `entity_id` (AC#5).
- `models-no-conversion` boundary rule present and passing (AC#1).
- `__init_subclass__` registers a grandchild domain class into the catalog (guards the depth behavior FR#3 relies on).

### Tests to Remove
- None outright — `TestConstructorFallbackCache` is rewritten, not deleted (keeps coverage of constructor fallback as behavior).

## Documentation Updates

- `docs/pages/core-concepts/states/conversion.md` — conversion is owned by the codec, not the model validator; note convert-on-miss no longer memoizes.
- `docs/pages/core-concepts/states/custom-states.md` — confirm module-level definition still auto-registers; adjust prose implying the model self-coerces.
- `docs/pages/core-concepts/states/index.md` + `type-registry`/`state-registry` snippet pages — verify prose matches the codec model.
- ADR-0003 — already revised to record B1 as the accepted decision; flip Status to Accepted on sign-off.
- No CHANGELOG edit (release-please). Squash title: `refactor:` (or `fix:` if framed as the cycle fix).

## Impact

<!-- Gap check 2026-06-24: 1 gap included — conversion/validation.py (:15,:83,:118 — imports StateKey/StateRegistry from conversion.state_registry, reads state_registry._registry, uses StateKey) → T03 Target Files + Focus item + step 5. Verified clean otherwise: core.py/test_utils/helpers.py/conftest already in scope; test_utils/harness.py reads public globals only (no change); state_manager.pyi has no affected signatures. -->

### Changed Files
- `src/hassette/models/states/base.py` (modify) — dumb model; repoint `__init_subclass__`; drop dead import. **Cross-cutting / highest risk.**
- `src/hassette/conversion/validation.py` (modify) — `StateKey` import source + `_registry` read survive the catalog-leaf move (gap-check addition; see T03).
- `src/hassette/models/states/registry.py` (create) — the state-class catalog leaf (`STATE_CATALOG`, `register_state_converter`, `resolve`, `StateKey`).
- `src/hassette/conversion/state_registry.py` (modify) — `StateRegistry` reads the catalog leaf; add known-model coercion + error wrapping; lazy `BaseState` imports → top-level.
- `src/hassette/conversion/type_registry.py` (modify) — stop convert-on-miss self-write; remove `snapshot`/`restore`; singleton def moves to module level.
- `src/hassette/conversion/type_matcher.py`, `annotation_converter.py` (modify) — module-level singleton defs; `annotation_converter` top-level imports; lazy annotations removed.
- `src/hassette/conversion/__init__.py` (modify) — re-export relocated singletons + `register_state_converter`; preserve public surface.
- `src/hassette/state_manager/state_manager.py` (modify) — route `DomainStates._validate_or_return_from_cache` (`:87`) through the codec known-model path and remove its `except ValidationError` re-wrap (`:88-89`). Optional tidy (not required): align the `:368,372,385,394` enumeration methods (which read module-level `STATE_REGISTRY`) to `self.hassette.state_registry` — functionally equivalent under a global, so it may be left untouched.
- `src/hassette/core/core.py` (modify) — `validate_registries` call still validates the globals; remove any `snapshot`/`restore` reliance.
- `src/hassette/test_utils/helpers.py` (modify) — add a codec-based state builder.
- `tools/check_module_boundaries.py` (modify) — add `models-no-conversion`.
- `tests/conftest.py`, `tests/unit/test_type_registry.py`, `tests/unit/conversion/test_registry_validation.py` (modify) — type-registry isolation + cache-test rewrite, per Test Strategy.
- `tests/unit/test_state_manager.py` (modify) — re-point the `LightState.model_validate` spies at the codec path once `:87` routes through it (per Test Strategy; breaks when `state_manager.py:87` reroutes).
- `tests/unit/conftest.py`, `tests/unit/test_sync_entity_facade.py`, `tests/unit/test_entity_coroutine_conversion.py`, `tests/integration/test_sync_facades.py`, `tests/unit/test_api_helper_models.py`, `tests/integration/test_models.py` (modify) — migrate `XState.model_validate(raw_dict)` to the codec helper (per Test Strategy; breaks when the model goes dumb).
- `docs/pages/core-concepts/states/*` (modify) — per Documentation Updates.

### Behavioral Invariants
- `try_convert_state` domain resolution + `BaseState` fallback unchanged (FR#4).
- Scalar coercion results unchanged for every `value_type` (FR#6).
- DI/annotation conversion observable behavior unchanged.
- Public imports in FR#9 unchanged; one global registry, no divergence.

### Blast Radius
- Conversion is core infrastructure used by `state_manager`, `api`, `bus` DI, and the recording/sync facades. Per CLAUDE.md, core changes lean on CI's `nox -s system_with_coverage` and `nox -s e2e` as the real safety net (unit/integration mock the boundaries where these regressions hide), in addition to the local unit/integration + lint gate.

## Open Questions

(none — per-instance question resolved by verification; correctness fixes folded in)
