---
task_id: "T01"
title: "Emit domain sync facades from the entity template"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#7", "AC#8"]
---

## Summary

Extend the entity-wrapper Jinja template so every service-bearing domain renders a
`{DomainTitle}EntitySyncFacade` class alongside its entity class, plus a typed
`.sync` property override on the entity. The facade exposes one synchronous method
per domain service, mirroring the async method's signature but routing through the
Api sync facade. Add codegen structural tests that assert the new output appears.
This task changes the template only — no generated files are regenerated here
(that is T02).

## Prompt

Edit `codegen/src/hassette_codegen/templates/entity_wrapper.py.j2` and add tests to
`codegen/tests/test_entity_generator.py`. Do NOT touch
`codegen/src/hassette_codegen/generators/entities.py` — it already passes the
template everything needed (`services`, each with `name`, `method_name`, and
`params` where each param has `name`, `python_type`, `required`).

Follow the `## Architecture` section of
`design/specs/072-entity-sync-facades/design.md` and Key Decisions 2–5 in
`context.md`. Make these template changes:

1. **Imports.** The current header is
   `from typing import Any{% if type_aliases %}, Literal{% endif %}`. Add `cast`
   **unconditionally** (it is used by the `.sync` override in every generated
   file, so it must not sit behind the `{% if type_aliases %}` guard) —
   i.e. `from typing import Any, cast{% if type_aliases %}, Literal{% endif %}`.
   Extend `from .base import BaseEntity` to also import `BaseEntitySyncFacade`.
   Note: `reportUnusedImport` is `error` in `pyrightconfig.json`, but every
   generated file uses both `cast` and `BaseEntitySyncFacade` (state-only domains
   emit no file), so neither import is ever unused.

2. **`.sync` property override** inside the `{{ domain_title }}Entity` class
   (after the `attributes` property, before the service methods, or wherever
   keeps the diff clean):

   ```python
   @property
   def sync(self) -> "{{ domain_title }}EntitySyncFacade":
       if self._sync is None:
           self._sync = {{ domain_title }}EntitySyncFacade(entity=self)
       return cast("{{ domain_title }}EntitySyncFacade", self._sync)
   ```

3. **Facade class** after the entity class, iterating the same `services` loop the
   entity methods use. It inherits `BaseEntitySyncFacade[{{ domain_title }}State,
   str]` and does NOT redeclare `entity` or `__init__`. For each service emit a
   method with the SAME `method_name` and the SAME parameter block (keyword-only,
   required params no default, optional params `= None`) as the async entity
   method — but with **no return-type annotation** and a body that calls
   `self.entity.api.sync.call_service(...)`:

   ```python
   class {{ domain_title }}EntitySyncFacade(BaseEntitySyncFacade[{{ domain_title }}State, str]):
   {% for service in services %}
       def {{ service.method_name }}(self, *, <params...>):
           return self.entity.api.sync.call_service(
               domain=self.entity.domain,
               service="{{ service.name }}",
               target={"entity_id": self.entity.entity_id},
               <param=param ...>
           )
   {% endfor %}
   ```

   Mirror the existing async-method param rendering exactly (the `{% if
   service.params %}` / keyword-only / `= None` structure already in the template)
   so signatures match. A no-param service emits `def method(self):`.

4. **Add codegen structural tests** to `codegen/tests/test_entity_generator.py`
   under `TestEntityWrapperGenerator`. Assert, for a rendered domain (use `fan` or
   `cover` to match existing fixtures), that the output contains:
   - `class {Domain}EntitySyncFacade(BaseEntitySyncFacade[`
   - a `def sync(self) -> "{Domain}EntitySyncFacade"` property on the entity class
   - one facade method per service, with the same parameter names as the async
     method
   - that the facade methods have NO `-> None` annotation
   Extend or rely on `test_output_compiles` to confirm the whole module still
   parses as valid Python.

Run the codegen tests: `cd codegen && uv run pytest tests/test_entity_generator.py
-q --rootdir=.`

## Focus

- Template: `codegen/src/hassette_codegen/templates/entity_wrapper.py.j2` (~58
  lines currently). The async service-method rendering (the `{% for service in
  services %}` loop) is your reference for the facade param block — reuse the same
  `{% if service.params %}` branches.
- Data model: `ServiceForTemplate`/`ServiceParam` dataclasses in
  `codegen/src/hassette_codegen/generators/entities.py` (near the top, ~lines
  11–21).
- `Literal` params are hoisted to module-level aliases (`type_aliases`) already
  emitted before the entity class; the facade reuses the same alias names — do not
  emit a second alias set.
- Edge case: a domain whose own service is named `toggle` (e.g. `cover`) will
  generate a facade `toggle` that overrides `BaseEntitySyncFacade.toggle`. This is
  intentional and matches how the async entity already overrides base `toggle`.
- The base facade reference is `src/hassette/models/entities/base.py:91-109`.
- Pyright runs in `basic` mode with `reportReturnType` enabled — the missing
  return annotation on facade methods is required, not optional. Verified in
  `pyrightconfig.json`. Note `analyzeUnannotatedFunctions: true` is also set:
  that flag is what gives the no-annotation approach teeth — without it Pyright
  would silently skip the unannotated facade methods. Both flags together make
  omitting the annotation both safe (no `reportReturnType` error) and analyzed.
- Codegen tests run with `--rootdir=.` from inside `codegen/` and do NOT need an
  HA core checkout (they render from in-test fixture data).

## Verify

- [ ] FR#1: Rendered output for a service-bearing domain contains a `class
      {Domain}EntitySyncFacade(BaseEntitySyncFacade[{Domain}State, str])` block.
- [ ] FR#2: The facade defines one method per service, each with the same
      `method_name` and keyword parameter signature (names, required/optional
      defaults) as the async entity method.
- [ ] FR#3: The entity class renders a `sync` property annotated
      `-> "{Domain}EntitySyncFacade"` that constructs and caches the domain facade.
- [ ] FR#4: Each facade method body calls `self.entity.api.sync.call_service(domain=,
      service=, target=, **params)` and carries no return-type annotation.
- [ ] FR#5: The facade inherits from `BaseEntitySyncFacade` (so `turn_on`,
      `turn_off`, `toggle` remain available) and does not redeclare `entity`/`__init__`.
- [ ] FR#7: A domain with no services still renders nothing (existing
      `test_no_services_returns_none` still passes).
- [ ] AC#8: `cd codegen && uv run pytest tests/test_entity_generator.py -q
      --rootdir=.` passes, including the new facade-structure assertions and
      `test_output_compiles`.
