# Challenge Findings — Dumb State Models design

**Format-version:** 3
**Target:** design/specs/084-dumb-state-models-codec-conversion/design.md
**Critics:** senior-engineer, contract-caller, structural-minimalist
**Likely-invalid:** 0
**Date:** 2026-06-23

Three critics ran independently; findings converged sharply (same `file:line` gaps hit by 2-3 critics). All crux claims verified against code.

## Finding 1: TypeRegistry per-instance tier is unjustified ceremony — asymmetric split (HIGHEST-VALUE / STRUCTURAL / design-level: Yes / User-directed)

**Why it matters:** The user chose "B2 for both registries." The adversarial pass says that's half right. The `StateRegistry` per-instance tier is load-bearing (domain→class is what tests pollute and what two Hassette instances would share). The `TypeRegistry` per-instance tier exists *only* to clean up the convert-on-miss self-write. Stop that write and `TypeRegistry` becomes a stateless read-only catalog — deleting the ClassVar→instance migration, the active-context routing for type converters, the `test_type_registry.py` migration, and closing the AnnotationConverter/bus-DI gap (Finding 5) for free.

**Evidence:** `type_registry.py:205` (`TypeRegistry.register(...)` writes the `ClassVar` on cache miss); ADR-0003 itself: "the type-converter set is genuinely process-global and stateless"; `annotation_converter.py:39` + `bus/injection.py:115` use the module-level `TYPE_REGISTRY`/`ANNOTATION_CONVERTER` singletons.

**Design challenge:** If the type-converter catalog is process-global and stateless once the self-write stops, what does a per-instance `TypeRegistry` buy that a clean read-only global doesn't?

**Recommendation:** Adopt the asymmetric split — per-instance `StateRegistry`, clean-global read-only `TypeRegistry` (fix the convert-on-miss self-write). Roughly halves the design and resolves Findings 3, 5, and the type-side of 6.

## Finding 2: `StateManager` enumeration reads the global, not the instance (CRITICAL / Fragility / design-level: Yes / User-directed)

**Why it matters:** After per-instance migration, `self.states` iteration/containment silently reads the catalog-backed default while `.resolve()`/`.try_convert_state()` read the live instance. AC#4's isolation test (which exercises `.resolve()`) won't catch it.

**Evidence:** `state_manager.py:368,372,385,394` bind module-level `STATE_REGISTRY`; `:288,:356` use `self.hassette.state_registry`. Confirmed.

**Recommendation:** Move these four methods to `self.hassette.state_registry`; add a boundary rule banning module-level `STATE_REGISTRY`/`TYPE_REGISTRY` import outside `conversion/`. List them in Impact + Replacement Targets.

## Finding 3: `BaseState.__subclasses__()` scan registers zero domains (CRITICAL / Approach-now / design-level: Yes / User-directed)

**Why it matters:** The proposed discovery mechanism returns only the 5 intermediate bases; the ~40 domain leaves are grandchildren. Strict-mode startup would fail with an empty registry; non-strict would silently fall back to `BaseState` (uncoerced values everywhere).

**Evidence:** `light.py:56` `class LightState(BoolBaseState)`, `sensor.py:102` `class SensorState(StringBaseState)`; `base.py:209-244` defines the 5 intermediate bases as the only direct `BaseState` subclasses. Confirmed.

**Recommendation:** Either a recursive subclass walk, OR — simpler and order-independent — keep `__init_subclass__` but have it register into a **leaf catalog** (downward import, no cycle) instead of `conversion`. The leaf-catalog push avoids both the grandchildren bug and the late-import ordering edge cases (Finding 4).

## Finding 4: Scan-ordering / late-import classes silently unregistered (HIGH / Fragility / design-level: Yes / User-directed)

**Why it matters:** Today `__init_subclass__` fires on import regardless of timing. A startup scan misses any state class whose module imports after the scan — silent `BaseState` fallback. The "scan after app loading" point is also undefined: `validate_registries` runs in `wire_services()` before any app initializes.

**Evidence:** ADR/design Edge Cases acknowledge ordering but don't resolve the lifecycle point; `core.py:248` calls `validate_registries` in `wire_services`.

**Recommendation:** The leaf-catalog `__init_subclass__` push (Finding 3) dissolves this — registration stays eager and order-independent. If a scan is kept, define the exact lifecycle hook and rescan-on-miss behavior.

## Finding 5: Raw-dict hot path `state_manager.py:87` loses coercion silently (CRITICAL / Approach-now / design-level: Yes / User-directed)

**Why it matters:** `DomainStates._validate_or_return_from_cache` calls `self._model.model_validate(raw_dict)` — the primary path for `self.states.light["bedroom"]` and all domain iteration. After dumb models, the model no longer coerces; boolean/numeric domains return `"on"`/`"23.5"` strings. The design mentions `:87` once but specifies no replacement, and today's codec (`try_convert_state`) resolves domain from the dict — there's no "coerce against this known model class" entry point.

**Evidence:** `state_manager.py:87`; `state_registry.py:63` `try_convert_state(data, entity_id)` resolves domain internally.

**Recommendation:** Add a codec entry point that takes a known `state_class` + raw dict, coerces the value via the type registry, and constructs. Route `:87` through it.

## Finding 6: Error type/timing change breaks the `UnableToConvertStateError` catch (HIGH / Fragility / design-level: Yes / User-directed)

**Why it matters:** Coercion failure today surfaces as Pydantic `ValidationError`, caught at `state_manager.py:88` and re-raised as `UnableToConvertStateError` with `entity_id`. Moving coercion to the codec raises `UnableToConvertValueError` directly — not a `ValidationError` — so the catch misses it and the entity silently drops at the `except Exception: continue` path.

**Evidence:** `state_manager.py:88` catches `ValidationError`; `base.py:176` `except UnableToConvertValueError`; codec coercion would raise `UnableToConvertValueError`.

**Recommendation:** Codec wraps coercion failures so the existing `UnableToConvertStateError(entity_id, model)` contract holds; add a test pinning the error type + entity_id.

## Finding 7: Active-context `register_*` routing is promised but doesn't exist (HIGH / Gap / design-level: Yes / User-directed)

**Why it matters:** The design says module-level `register_*` also updates the active live instance. No context-var lookup exists in `conversion/` today; behavior with no/two contexts is unspecified. `register_state_converter` is documented public API (`conversion.md:87`) for runtime domain registration — under per-instance it would only hit the catalog, not the running registry, defeating its purpose.

**Evidence:** `type_registry.py:147-155` `register` is a classmethod with no context lookup; `core.py` context management exists but isn't wired to registration.

**Recommendation:** If Finding 1 is adopted, this collapses to the state-registry side only. Specify the context-var mechanism and the no-context behavior explicitly, or scope dynamic post-startup registration as unsupported and document it.

## Likely Invalid

(none)
