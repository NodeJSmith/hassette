---
task_id: "T08"
title: "Implement entity wrapper generator"
status: "planned"
depends_on: ["T05", "T06", "T07"]
implements: ["FR#3", "AC#4"]
---

## Summary
Builds the entity wrapper generator that takes extracted service definitions and produces typed entity classes with service call methods. Each entity extends `BaseEntity[DomainState, ValueType]` and provides keyword-only async methods matching HA's services.yaml fields.

## Prompt
Create:

**`codegen/src/hassette_codegen/generators/entities.py`:**
- Input: `ExtractedDomain` with service extraction results + overrides
- Load Jinja2 template from `templates/entity_wrapper.py.j2`
- Render one `.py` file per domain (only for domains with services) containing:
  1. Imports (typing Literal, domain state class, base entity, override extra_imports)
  2. Type aliases for constrained Literals (e.g., `Flash = Literal["short", "long"]` from select selectors)
  3. `{Domain}Entity(BaseEntity[{Domain}State, {ValueType}])` class
  4. `attributes` property returning the domain's Attributes class
  5. One async method per service: `async def {method_name}(self, *, {typed_params}) -> None`
     - All params keyword-only (`*`)
     - Types from type_mapping (applied after overrides — param_type_overrides win)
     - Param renames applied from overrides
     - Method body: `await self.api.call_service(domain=self.domain, service="{name}", target={"entity_id": self.entity_id}, **{non_none_params})`
- Domains with no services.yaml: skip entity generation entirely (state-only domain)
- Return rendered content as string

**`codegen/src/hassette_codegen/templates/entity_wrapper.py.j2`:**
Template matching the pattern established in `src/hassette/models/entities/light.py` (the hand-written reference). Reference it directly for the target format.

**Value type determination:**
- ToggleEntity domains → `str` (state is "on"/"off" string)
- Numeric domains → `str` (state is string repr of number)
- String domains → `str`
- (All domains use `str` as the ValueType in practice — this matches existing LightEntity)

Unit tests in `codegen/tests/test_entity_generator.py`:
- Render fan entity → output contains `FanEntity(BaseEntity[FanState, str])`, methods for turn_on/turn_off/toggle/set_percentage/set_preset_mode/set_direction/oscillate
- Render cover entity → output contains open_cover/close_cover/stop_cover/set_cover_position
- Override renames applied: media_player's `media_content_type` → `media_type` in method signature
- Generated output passes py_compile
- All method params are keyword-only (star in signature)

## Focus
- Reference `src/hassette/models/entities/light.py` — this is the canonical format. Methods call `self.api.call_service()` directly with domain, service name, target, and kwargs.
- `call_service` in `src/hassette/api/api.py:519` already strips None values from kwargs — entity methods just pass all params through
- The `attributes` property is a simple delegation: `return self.state.attributes`
- BaseEntity provides `turn_on(**data)`, `turn_off()`, `toggle()` as fallbacks — generated entities override these with typed signatures
- Literal type aliases (like `Flash = Literal["short", "long"]`) should be generated at module level, one per `select` selector

## Verify
- [ ] FR#3: Generated entity methods have typed signatures matching services.yaml field definitions
- [ ] AC#4: Parameter names match services.yaml keys (after override renames), types match selector mapping, optional params default to None
