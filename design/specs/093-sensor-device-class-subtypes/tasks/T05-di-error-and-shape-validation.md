---
task_id: "T05"
title: "Add legible DI conversion errors and shape validation"
status: "planned"
depends_on: ["T04"]
implements: ["FR#14", "FR#15", "AC#10", "AC#11"]
---

## Summary

Dependency injection currently fails two ways when an annotation and an entity disagree. A
too-strict annotation raises a raw Pydantic `ValidationError` about `state.int` / `state.float` —
technically safe, but unreadable. A too-loose annotation does not fail at all: annotating
`D.StateNew[EnumSensorState]` against a temperature sensor returns `'23.5'` with no signal, because
a float coerces to a string happily. Fix the first with a wrapping error that names the entity, and
the second by comparing the annotated class's declared shape against the shape the classifier
computes.

## Target Files

- modify: `src/hassette/conversion/state_registry.py`
- modify: `src/hassette/exceptions.py`
- create: `tests/unit/conversion/test_di_shape_validation.py`
- read: `src/hassette/models/states/sensor_shapes.py`
- read: `src/hassette/event_handling/dependencies.py`
- read: `src/hassette/event_handling/annotation_converter.py`
- read: `tests/unit/conversion/test_custom_conversion.py`

## Prompt

Read `context.md` first, then the design doc's `## Architecture → The DI error wrapper and shape
validation` section.

Both changes land in `convert_state_dict_to_model`
(`src/hassette/conversion/state_registry.py:218-260`). That function already holds the full raw
dict, so `prepared["attributes"]["device_class"]` is in scope with no registry involvement.

**Part 1 — legible failures (FR#14).**

When `model.model_validate(prepared)` raises, wrap the Pydantic `ValidationError` in a new exception
that names the entity id, the entity's actual device class, and the annotated class. Follow the
pattern of `UnableToConvertStateError` (`exceptions.py:363-369`): a message plus structured
attributes, not a bare string. Chain the original with `raise ... from exc` so the Pydantic detail
is not lost.

This matters because DI calls `convert_state_dict_to_model` directly rather than through
`conversion_with_error_handling` (`state_registry.py:159-195`), so today the failure never gets
wrapped into the framework's own error type at all.

**Part 2 — shape validation (FR#15).**

When the annotated class is one of the four narrowed sensor shapes from T04, compute the entity's
shape with the classifier and raise when it disagrees with the shape the class declares — even
though coercion would have succeeded. Add a distinct exception for the mismatch; its message must
name the entity, its actual device class, and the annotated class.

Three scoping rules, all load-bearing:

1. **Only the four narrowed classes trigger validation.** A plain `SensorState` annotation makes no
   shape claim, so there is nothing to contradict — it stays unvalidated and behaves exactly as it
   does today. Same for every other domain's state class.
2. **An entity that classifies as "unknown" does not raise.** No shape claim can be contradicted by
   an entity whose shape cannot be determined.
3. **This runs on the DI path for every domain**, so the check must be cheap and must short-circuit
   before doing any work when the annotated class is not one of the four.

**Part 3 — tests.**

Create `tests/unit/conversion/test_di_shape_validation.py` covering all four FR#15 cases plus the
FR#14 message contents:

- Mismatched narrowed annotation (`EnumSensorState` against a temperature state dict) raises rather
  than returning `'23.5'`.
- Matching narrowed annotation still converts successfully.
- Plain `SensorState` annotation is unaffected.
- An entity classifying as "unknown" does not raise.
- The FR#14 error message contains the entity id, the actual device class, and the annotated class
  name.

## Focus

**Depends on T04** for both the four classes and the classifier function.

**This is additive, not breaking — and the scoping is what makes it so.** No code written before
this ships can annotate a class that does not yet exist, so no existing user automation changes
behavior. "DI now raises where it used to return a value" reads like a breaking change and is not
one. Do not widen the scope beyond the four new classes; doing so later would need to be treated as
a breaking change at that point.

**Do not touch the `suppress(UnableToConvertValueError)` at `state_registry.py:257`.** It skips only
the `TYPE_REGISTRY` step; `model.model_validate` runs immediately after and rejects genuinely bad
values. Its permissive fallback-to-string behavior is a known, separately-tracked concern
(issue #1539) and is explicitly out of scope here.

**Preprocessing already normalizes unavailable states.** `state == "unknown"` and
`state == "unavailable"` are set to `None` before coercion (`state_registry.py:248-255`), so such
entities have `value is None` and must not trip shape validation.

**The device-class-flip case resolves here.** `D.TypedStateChangeEvent[X]` applies the same class to
both `old_state` and `new_state` (`annotation_converter.py:180-181`). When an event straddles a
runtime device-class change, the mismatched half fails this validation and the handler raises.
That is the intended behavior — there is no fallback to `SensorState` for one half, because a
half-narrowed event would be a type lie. No special-casing is needed; just do not add an escape
hatch for it.

**Follow the repo's exception conventions.** New exceptions belong in `src/hassette/exceptions.py`
under the existing `StateRegistryError` hierarchy. `tools/check_exception_names.py` enforces that
caught exceptions are bound to `exc` or a `*_exc` name — never `e`, `err`, or `error`.

## Verify

- [ ] FR#14: A failed conversion during DI raises a framework exception (not a raw Pydantic
      `ValidationError`) whose message names the entity, its actual device class, and the annotated
      class, with the original chained via `from exc`.
- [ ] FR#15: DI raises when the annotated class is one of the four narrowed shapes and the entity's
      computed shape disagrees — including the coercion-would-succeed case — while an entity
      classifying as "unknown" does not raise.
- [ ] AC#10: A test asserts the DI conversion error message contains the entity id, the actual
      device class, and the annotated class name.
- [ ] AC#11: `uv run pytest tests/unit/conversion/test_di_shape_validation.py -n 4` passes,
      covering all four cases: mismatched narrowed annotation raises, matching narrowed annotation
      converts, plain `SensorState` annotation unaffected, "unknown" entity does not raise.
