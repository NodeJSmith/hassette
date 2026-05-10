---
task_id: "T07"
title: "Implement state model generator with Jinja2 templates"
status: "planned"
depends_on: ["T04", "T05", "T06"]
implements: ["FR#4", "FR#6", "AC#3", "AC#12"]
---

## Summary
Builds the state model generator that takes extracted data (properties, features, base class) and renders Pydantic state model files via Jinja2 templates. Each generated file contains the IntFlag enum (colocated), an Attributes class, and a State class — matching the pattern of existing hand-written models.

## Prompt
Create:

**`codegen/src/hassette_codegen/generators/states.py`:**
- Input: `ExtractedDomain` (aggregated extraction results + overrides for one domain)
- Load Jinja2 template from `templates/state_model.py.j2`
- Render one `.py` file per domain containing:
  1. Imports (typing, pydantic Field, base classes, plus override extra_imports)
  2. IntFlag enum (if domain has one) — same name, same members, same values as HA core
  3. `{Domain}Attributes(AttributesBase)` class — fields from _attr_* extraction, all `| None = Field(default=None)` for those without defaults
  4. `supports_{feature_name}` properties on the Attributes class — one per IntFlag member, calling `self._has_feature(EnumClass.MEMBER)`
  5. `{Domain}State({Base}BaseState)` class — `domain: Literal["{domain}"]`, `attributes: {Domain}Attributes`
- Apply override base class if specified
- Return rendered content as string (caller handles formatting + writing)

**`codegen/src/hassette_codegen/templates/state_model.py.j2`:**
Template matching existing patterns. Reference `src/hassette/models/states/fan.py` and `light.py` as canonical examples of the target format.

Unit tests in `codegen/tests/test_state_generator.py`:
- Render fan domain → output contains `FanEntityFeature(IntFlag)`, `FanAttributes(AttributesBase)`, `FanState(BoolBaseState)`, all `supports_*` properties
- Render sensor domain → output contains `SensorAttributes`, `SensorState(NumericBaseState)` (via override), no IntFlag section
- Generated output passes py_compile
- Fields without defaults produce `field_type | None = Field(default=None)` in output

## Focus
- Existing state files follow a strict pattern: imports → IntFlag (if any) → Attributes class → State class. The template must reproduce this order.
- `AttributesBase._has_feature()` is defined in `base.py` — the Attributes class just calls it. The generated `supports_*` property is: `@property\ndef supports_X(self) -> bool:\n    return self._has_feature(Enum.MEMBER)`
- Field definitions use `Field(default=None)` — not bare `None` as default. This matches existing hand-written patterns.
- The `domain: Literal["fan"]` annotation on the State class is what triggers auto-registration via `__init_subclass__`
- Jinja2 templates should use `{% for %}` loops for fields and enum members — keep the template readable

## Verify
- [ ] FR#4: Generated state models have `{Domain}Attributes(AttributesBase)` + `{Domain}State({Base}BaseState)` with `domain: Literal["{domain}"]`
- [ ] FR#6: Generated attribute classes include `supports_{feature_name}` properties for each IntFlag member
- [ ] AC#3: Generated state model structure matches: correct base class, correct field types, correct attribute class pattern
- [ ] AC#12: Each IntFlag member produces a corresponding `supports_*` property on the Attributes class
