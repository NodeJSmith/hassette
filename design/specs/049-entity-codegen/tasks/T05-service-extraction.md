---
task_id: "T05"
title: "Implement service extraction and type mapping"
status: "planned"
depends_on: ["T03"]
implements: ["FR#3", "FR#12", "AC#4", "AC#14"]
---

## Summary
Builds the hybrid PyYAML + AST service extractor and the selector-to-Python type mapping. Parses services.yaml for field definitions (names, selectors, required/optional, sections) and cross-references with AST-parsed service registrations in __init__.py. Produces typed method signature data for each service.

## Prompt
Create two modules:

**`codegen/src/hassette_codegen/extractors/services.py`:**
- Input: domain component directory path
- Load `services.yaml` with `yaml.safe_load()` (handles anchors automatically)
- For each service definition, extract:
  - Service name (e.g., `turn_on`, `set_temperature`)
  - Fields: name, selector type, required/optional
  - **Section flattening**: when a field entry has a nested `fields` key (e.g., `advanced_fields` in light), flatten sub-fields into the top-level field list
- Cross-reference with AST: parse `__init__.py` for `async_register_entity_service()` calls to get:
  - Method target name (3rd positional arg — string)
  - Required feature flags (4th positional arg — list of enum references)
- Return: `list[ExtractedService]` with `name`, `method_name`, `fields: list[ServiceField]`, `required_features: list[str]`
- Handle: missing services.yaml (return empty list), domain with zero fields in a service (empty field list)

**`codegen/src/hassette_codegen/type_mapping.py`:**
- Map YAML selector types to Python type strings:
  - `number` → `int` (if step is None or ≥ 1) or `float` (if step < 1)
  - `boolean` → `bool`
  - `text` → `str`
  - `select` → `Literal[...]` with options extracted
  - `color_rgb` → `tuple[int, int, int]`
  - `color_temp` → `int`
  - `object` → `Any`
  - `state` → `str`
  - `entity` → `str`
  - `area` → `str`
  - `media` → `dict[str, Any]`
  - `constant` → `Any`
- Unknown selectors → `Any` + emit warning to stderr naming the selector and domain
- All service params are optional (default `None`) unless marked `required: true` in YAML

Unit tests in `codegen/tests/test_services.py`:
- Test against `~/source/core/homeassistant/components/fan/services.yaml` (clean, well-behaved)
- Test against `~/source/core/homeassistant/components/light/services.yaml` (has advanced_fields sections to flatten)
- Test section flattening produces all expected params for light.turn_on (10+ from advanced_fields)
- Test type mapping covers all 12 selector types
- Test unknown selector emits warning and returns `Any`
- Test domain with no services.yaml returns empty list

## Focus
- Light's services.yaml has `advanced_fields` sections with `collapsed: true` and nested `fields:` — the flattener must recurse into these
- `async_register_entity_service` call pattern: `component.async_register_entity_service(SERVICE_NAME, schema, "async_method_name", [Feature.X])` — 4th arg is optional
- PyYAML resolves YAML anchors (`&transition`, `*color_support`) transparently — no special handling needed
- The `required` key on service fields defaults to `false` when absent — treat all params as optional unless explicitly required
- Some services have `target:` definitions — these are entity targeting, not method params (ignore)

## Verify
- [ ] FR#3: Service definitions are parsed from services.yaml + AST, producing typed method signatures with parameter names, types, and optionality
- [ ] FR#12: services.yaml is parsed with PyYAML directly (no hassfest import)
- [ ] AC#4: Parameter names match services.yaml field keys, types match selector mapping, optional params default to None
- [ ] AC#14: Nested sections (advanced_fields) in light are flattened into method signature — verified by light.turn_on including 10+ advanced_fields params
