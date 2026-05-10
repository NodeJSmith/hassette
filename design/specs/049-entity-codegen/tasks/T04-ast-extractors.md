---
task_id: "T04"
title: "Implement AST extractors for features, properties, and base class"
status: "planned"
depends_on: ["T03"]
implements: ["FR#1", "FR#2", "FR#5", "AC#5"]
---

## Summary
Builds the three AST-based extractors that read HA core Python source and produce structured data: IntFlag enum extraction, entity property extraction (_attr_* fields), and base class determination via inheritance heuristics. These are pure data extraction — no code generation yet.

## Prompt
Create three extractor modules:

**`codegen/src/hassette_codegen/extractors/features.py`:**
- Input: path to a domain component directory
- Scan BOTH `const.py` AND `__init__.py` for `IntFlag` subclasses (class name ending in `EntityFeature`)
- Extract: class name, each member name + integer value
- Return: `list[ExtractedEnum]` where `ExtractedEnum` has `name: str`, `members: list[tuple[str, int]]`
- Handle: domain with no IntFlag (return empty list)

**`codegen/src/hassette_codegen/extractors/properties.py`:**
- Input: path to a domain `__init__.py`
- Find the `CACHED_PROPERTIES_WITH_ATTR_` set literal — extract all string members
- Find all `_attr_*` annotated class variables in the Entity class body — extract name (strip `_attr_` prefix) and type annotation
- For fields WITHOUT a default value: widen type to `type | None` (FR#2)
- Return: `list[ExtractedProperty]` where each has `name: str`, `python_type: str`, `has_default: bool`

**`codegen/src/hassette_codegen/extractors/base_class.py`:**
- Input: path to a domain `__init__.py`
- Check class bases via AST: if `ToggleEntity` in bases → `"BoolBaseState"`
- Check `state` property return type annotation: if it's `float | None` or `int | None` → `"NumericBaseState"`
- Default → `"StringBaseState"`
- Return: `str` (the base class name)

Unit tests in `codegen/tests/test_extractors.py`:
- Test feature extraction against `~/source/core/homeassistant/components/light/const.py` (has IntFlag in const.py)
- Test feature extraction against `~/source/core/homeassistant/components/fan/__init__.py` (has IntFlag in __init__.py)
- Test property extraction against fan (medium complexity, clear _attr_* fields)
- Test base class: light → BoolBaseState (ToggleEntity), number → NumericBaseState (float state), climate → StringBaseState
- Test _attr_* field without default produces `| None` widening

Tests that use `~/source/core` must be guarded with `pytest.mark.skipif(not Path("~/source/core").expanduser().exists(), reason="HA core checkout not available")`. This is a LOCAL dev convenience only — the codegen CI job (T11) always provides the HA checkout, so these tests never skip in CI.

## Focus
- HA core entity classes use `cached_properties=CACHED_PROPERTIES_WITH_ATTR_` as a keyword arg to the class definition — the set is a module-level constant
- `_attr_*` fields are `AnnAssign` nodes in the class body — some have `value` (default), some don't
- Type annotations can be complex: `StateType | date | datetime | Decimal` — extract the full annotation as a string via `ast.unparse()`
- The base class check needs to handle `class LightEntity(ToggleEntity, cached_properties=...)` — ToggleEntity is in the bases, `cached_properties` is a keyword
- `NumberEntity.state` property has return annotation `float | None` — parse via AST, check if it's a numeric type

## Verify
- [ ] FR#1: IntFlag enums are extracted from both `const.py` and `__init__.py` (verified: fan's enum found in `__init__.py`, light's in `const.py`)
- [ ] FR#2: _attr_* fields without defaults are treated as `type | None = Field(default=None)` in extracted data
- [ ] FR#5: Base class is determined via ToggleEntity inheritance (→ Bool), numeric state return (→ Numeric), else String
- [ ] AC#5: Extracted IntFlag enums have same class name, member names, and integer values as HA core source
