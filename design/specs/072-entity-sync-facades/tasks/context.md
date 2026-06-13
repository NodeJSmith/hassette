# Context: Domain Entity Sync Facades

## Problem & Motivation

`AppSync` authors control Home Assistant entities through a synchronous facade so
they never touch `async`/`await`. That contract only holds for the three base
actions — `BaseEntitySyncFacade` wraps `turn_on`, `turn_off`, and `toggle`. Every
domain-specific action (`CoverEntity.open_cover()`,
`ClimateEntity.set_temperature()`, `LightEntity` brightness control, etc.) is
async-only, with no sync counterpart. A sync author who wants one must drop out of
the facade and write `self.task_bucket.run_sync(cover.open_cover())` by hand — the
exact boilerplate the facade exists to remove. This change generates a typed
`{Domain}EntitySyncFacade` per domain so every domain action is available
synchronously, with the async signatures preserved.

## Visual Artifacts

None.

## Key Decisions

1. **The Jinja template is the only hand-edited source.**
   `codegen/src/hassette_codegen/templates/entity_wrapper.py.j2` already receives
   the full `services` list (each with `name`, `method_name`, `params`). Emitting
   a facade class + `.sync` override from the same data needs **no change to
   `generators/entities.py`**. All 25+ domain files regenerate from the template.

2. **Facade methods delegate through `self.entity.api.sync.call_service(...)`** —
   the Api sync facade, which owns the `run_sync` machinery. This mirrors the
   existing `BaseEntitySyncFacade.turn_off` →
   `self.entity.api.sync.turn_off(...)` pattern. Do **not** reuse `gen_wrapper()`
   from `sync_facade/generic.py`: it emits `self.task_bucket.run_sync(...)`, and
   the facade has no `task_bucket`.

3. **Facade methods carry no return-type annotation.** This is load-bearing.
   `api.sync.call_service` returns `ServiceResponse | None`
   (`src/hassette/api/sync.py:212`), not `None`. Annotating a facade method
   `-> None` while its body does `return self.entity.api.sync.call_service(...)`
   raises Pyright `reportReturnType` (enabled — `pyrightconfig.json` is `basic`
   mode and the `reportReturnType: none` override is commented out). Omitting the
   annotation lets Pyright infer `ServiceResponse | None`, matching every existing
   base-facade method.

4. **The facade inherits `BaseEntitySyncFacade[{Domain}State, str]` without
   redeclaring `entity` or `__init__`.** Its methods only touch base-level members
   (`self.entity.api`, `.domain`, `.entity_id`), so the inherited attribute and
   constructor suffice. This avoids `reportIncompatibleVariableOverride` and
   `__init__`-override friction, and preserves inherited `turn_on/off/toggle`.

5. **The `.sync` property override caches in the base `_sync` slot with a `cast`.**
   `_sync` is typed `BaseEntitySyncFacade[StateT, StateValueT] | None`; a domain
   facade instance fits (subclass). The override narrows the getter return type to
   the domain facade via a quoted forward-ref and `cast`. Needs `from typing
   import cast` in the generated file.

6. **`__init__.py` exports are automatic.** `generators/exports.py` scans every
   non-underscore `ClassDef`. The new facade classes export with no manual edit.

7. **Scope is independent of issue #938** (table-driven sync-facade
   consolidation). Entity facades go through the template path, structurally
   separate from the AST-based `sync_facade/generic.py` path #938 consolidates.

## Constraints & Anti-Patterns

- Do **not** hand-edit generated files (`src/hassette/models/entities/{domain}.py`,
  `__init__.py`). Change the template and regenerate.
- Do **not** reuse `gen_wrapper()` for entity facades (no `task_bucket`).
- Do **not** annotate facade methods `-> None` (breaks Pyright / AC#7).
- Do **not** add an entity case to `sync_facade/generic.py` — that is #938.
- Do **not** redeclare `entity` or `__init__` on the facade subclass.
- Regeneration requires a local HA core checkout at the pinned version
  (`codegen/ha-version.txt` = `2026.5.1`); there is none in the worktree.

## Design Doc References

- `## Architecture` — the template changes (facade block, `.sync` override,
  imports), export generation, and the regeneration command.
- `## Key Constraints` — the gen_wrapper / hand-edit / #938 prohibitions.
- `## Dependencies and Assumptions` — HA core checkout requirement, `#938`
  independence.
- `## Test Strategy` — existing tests to confirm, new structural + runtime
  coverage.
- `## Edge Cases` — `toggle` override, param shapes, `Literal` aliases, `.sync`
  caching.

## Convention Examples

### Entity sync-facade delegation pattern

**Source:** `src/hassette/models/entities/base.py`

```python
class BaseEntitySyncFacade(Generic[StateT, StateValueT]):
    entity: BaseEntity[StateT, StateValueT]

    def __init__(self, entity: BaseEntity[StateT, StateValueT]) -> None:
        self.entity = entity

    def turn_off(self):
        """Turn off the entity."""
        return self.entity.api.sync.turn_off(self.entity.entity_id, self.entity.domain)
```

The facade delegates through `self.entity.api.sync.*` — the Api sync facade owns
the `run_sync` machinery. Domain facades generalize this to `call_service`. Note
the **absent return annotation** — load-bearing (see Key Decision 3).

### Async domain method shape (what the facade mirrors)

**Source:** `src/hassette/models/entities/cover.py`

```python
def set_cover_position(self, *, position: int) -> Coroutine[Any, Any, None]:
    """Must be awaited ..."""
    return self.api.call_service(
        domain=self.domain,
        service="set_cover_position",
        target={"entity_id": self.entity_id},
        position=position,
    )
```

The facade method is this body with `self.api` → `self.entity.api.sync` and **no**
return annotation.

### Codegen test convention

**Source:** `codegen/tests/test_entity_generator.py`

```python
class TestEntityWrapperGenerator:
    def test_fan_entity(self) -> None:
        ...

    def test_output_compiles(self) -> None:
        ...
```

Tests render a domain (e.g. `fan`) and assert on the generated source string;
`test_output_compiles` parses the output to confirm it is valid Python.
