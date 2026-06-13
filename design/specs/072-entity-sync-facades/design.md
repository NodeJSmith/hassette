# Design: Domain Entity Sync Facades

**Date:** 2026-06-12
**Status:** archived
**Scope-mode:** hold
**Issue:** #959

## Problem

`AppSync` authors interact with Home Assistant entities through a synchronous
facade so they never touch `async`/`await`. That contract holds for the three
base actions — `BaseEntitySyncFacade` wraps `turn_on`, `turn_off`, and `toggle`.
It breaks the moment an author reaches for anything domain-specific.

Domain entity classes define their own async action methods:
`CoverEntity.open_cover()`, `ClimateEntity.set_temperature()`,
`LightEntity.turn_on(brightness=...)`, and dozens more, each generated from the
Home Assistant service registry. None of these have sync counterparts. A sync
author who wants to open a cover must drop out of the facade abstraction and
write `self.task_bucket.run_sync(cover.open_cover())` by hand — the exact
boilerplate the facade exists to remove. The sync surface silently covers ~3
methods out of the full per-domain action set.

## Goals

- Every domain entity exposes its domain-specific actions synchronously, with
  the same method names and typed parameters as the async versions.
- `LightEntity.sync` is typed as `LightEntitySyncFacade` (not the base), so an
  author's IDE offers `set_brightness`/`turn_on(...)` with full parameter types.
- The existing `.sync.turn_on()` / `.turn_off()` / `.toggle()` calls continue to
  work unchanged.
- The facades are generated, not hand-written — they stay in sync with the HA
  service registry on every codegen run.

## User Scenarios

### Sync app author: builds automations without async

- **Goal:** Control a cover from a synchronous app.
- **Context:** Writing an `AppSync` subclass; never wants to think about the
  event loop.

#### Open a cover to a set position from a sync handler

1. **Look up the entity and call the action synchronously**
   - Sees: `cover.sync.` autocompletes to `open_cover`, `close_cover`,
     `set_cover_position`, `stop_cover`, plus the inherited `turn_on/off/toggle`.
   - Decides: calls `cover.sync.set_cover_position(position=60)`.
   - Then: the call runs to completion synchronously and returns `None`; no
     `await`, no `run_sync`, no coroutine warning.

2. **Pass typed parameters**
   - Sees: Pyright enforces `position: int`; passing a string is a type error at
     author time.
   - Decides: relies on the type to catch mistakes before runtime.
   - Then: the parameter flows through to `call_service` with the correct name.

## Functional Requirements

- **FR#1** Each generated domain entity module emits a
  `{DomainTitle}EntitySyncFacade` class alongside its `{DomainTitle}Entity`
  class.
- **FR#2** The sync facade class defines one synchronous method per
  domain-specific service, with the same method name and the same keyword
  parameters (names, types, required/optional defaults) as the async entity
  method.
- **FR#3** Each domain entity class overrides the `.sync` property to return the
  domain-specific facade type rather than `BaseEntitySyncFacade`.
- **FR#4** Calling a domain sync facade method performs the same Home Assistant
  service call as its async counterpart — same `domain`, `service`, target
  entity, and parameters — executed synchronously (blocking until the call
  completes), with no `await` and no coroutine returned.
- **FR#5** Domain sync facades inherit the base `turn_on` / `turn_off` /
  `toggle` behavior unchanged.
- **FR#6** The new facade classes are exported from
  `src/hassette/models/entities/__init__.py`.
- **FR#7** Domains with no services (state-only domains such as `sensor`) emit no
  entity file and therefore no facade — unchanged from current behavior.

## Edge Cases

- **Service named `toggle` on a domain.** `CoverEntity` defines a `toggle`
  service that overrides the base `toggle`. The generated facade likewise
  overrides `BaseEntitySyncFacade.toggle`, routing through
  `call_service(service="toggle")`. The override is intentional and matches how
  the async entity method already overrides the base.
- **Service with no parameters** (e.g. `open_cover`): facade method takes only
  `self` and emits a `call_service` call with just `domain`/`service`/`target`.
- **Service with required and optional parameters** (e.g. `set_temperature`):
  parameters keep their keyword-only signature and `= None` defaults, identical
  to the async method.
- **`Literal[...]` parameter type aliases.** The generator hoists `Literal`
  selector types into module-level aliases for the async methods. The facade
  reuses the same aliases — no second alias set.
- **First vs cached `.sync` access.** The first `.sync` access constructs the
  facade and caches it in `_sync`; subsequent accesses return the cached
  instance. The cached value is a domain facade (a `BaseEntitySyncFacade`
  subclass), so the base `_sync` slot holds it without type widening at runtime.

## Acceptance Criteria

- **AC#1** `from hassette.models.entities import CoverEntitySyncFacade,
  ClimateEntitySyncFacade, LightEntitySyncFacade` succeeds. (FR#1, FR#6)
- **AC#2** `CoverEntity(...).sync` is an instance of `CoverEntitySyncFacade`, not
  `BaseEntitySyncFacade`. (FR#3)
- **AC#3** `CoverEntity(...).sync.open_cover()` dispatches synchronously to
  `api.sync.call_service(domain=..., service="open_cover",
  target={"entity_id": ...})` — no coroutine is returned. (FR#2, FR#4)
- **AC#4** `ClimateEntity(...).sync.set_temperature(temperature=21.0)` dispatches
  with the `temperature` parameter passed through. (FR#2, FR#4)
- **AC#5** `LightEntity(...).sync.turn_on(brightness=128)` and
  `LightEntity(...).sync.turn_off()` both work — inherited base behavior is
  intact. (FR#5)
- **AC#6** `cd codegen && uv run hassette-codegen generate --ha-core-path
  ../ha-core --check` exits 0 (no drift between template and committed files).
- **AC#7** `uv run pyright` exits 0 with no new errors across the regenerated
  entity files.
- **AC#8** `codegen/tests/test_entity_generator.py` asserts the facade class and
  `.sync` override appear in generated output. (FR#1, FR#2, FR#3)

## Key Constraints

- **Do not reuse `gen_wrapper()` from `codegen/.../sync_facade/generic.py` for
  entity facades.** `gen_wrapper()` emits `self.task_bucket.run_sync(...)`.
  `BaseEntitySyncFacade` has no `task_bucket` and neither does an entity. The
  established entity-facade delegation goes through `self.entity.api.sync.*`
  (see `BaseEntitySyncFacade.turn_off` at
  `src/hassette/models/entities/base.py:99`). The entity sync facade is emitted
  directly by the Jinja template, not by the AST wrapper utility.
- **Do not hand-edit generated files.** `src/hassette/models/entities/{domain}.py`
  and `__init__.py` are codegen output. All changes go through the template
  (`entity_wrapper.py.j2`); regenerate to apply.
- **Do not add an entity-facade case to `sync_facade/generic.py`** as part of
  this work — that is #938's table-driven consolidation, deliberately out of
  scope (see Dependencies).

## Dependencies and Assumptions

- **HA core checkout required for regeneration.** There is no `ha-core/` checkout
  in the worktree. Regeneration and the `--check` freshness gate both need it,
  cloned at the version pinned in `codegen/ha-version.txt`:
  ```bash
  git clone --depth 1 --branch "$(cat codegen/ha-version.txt)" \
    https://github.com/home-assistant/core.git ha-core
  ```
  CI does this via the `codegen-freshness` job in `.github/workflows/lint.yml`.
- **`api.sync.call_service` exists** (`src/hassette/api/sync.py:205`) and is the
  delegation target for every facade method.
- **Issue #938 (consolidate sync-facade codegen into table-driven generation) is
  independent.** Entity facades are generated through the Jinja template path
  (`entity_wrapper.py.j2` + `generators/entities.py`), structurally separate from
  the AST-based `sync_facade/generic.py` path that #938 consolidates. #959 ships
  on its own; if #938 later chooses to absorb entity-facade generation, that is a
  separate migration. Confirmed decision: do #959 now, independent of #938.

## Architecture

The entire change is driven by the Jinja template. `generate_entity_wrapper()`
(`codegen/src/hassette_codegen/generators/entities.py:24`) already passes the
template everything needed — a `services` list where each entry carries
`name` (HA service id), `method_name`, and `params` (each with `name`,
`python_type`, `required`). The async entity methods are rendered from exactly
this data. The facade methods need the same data routed to a different call
target, so **no generator code changes are required**.

### Template changes (`entity_wrapper.py.j2`)

1. **Add the facade class block** after the `{{ domain_title }}Entity` class.
   It inherits `BaseEntitySyncFacade[{{ domain_title }}State, str]` and, for each
   service, emits a synchronous method whose body mirrors the async method but
   calls `self.entity.api.sync.call_service(...)` instead of
   `self.api.call_service(...)`:

   ```python
   class CoverEntitySyncFacade(BaseEntitySyncFacade[CoverState, str]):
       def open_cover(self):
           return self.entity.api.sync.call_service(
               domain=self.entity.domain,
               service="open_cover",
               target={"entity_id": self.entity.entity_id},
           )

       def set_cover_position(self, *, position: int):
           return self.entity.api.sync.call_service(
               domain=self.entity.domain,
               service="set_cover_position",
               target={"entity_id": self.entity.entity_id},
               position=position,
           )
   ```

   **Facade methods carry no return-type annotation**, matching
   `BaseEntitySyncFacade.turn_off` (`src/hassette/models/entities/base.py:99`).
   This is load-bearing, not stylistic: `api.sync.call_service` returns
   `ServiceResponse | None` (`src/hassette/api/sync.py:212`), not `None`.
   Annotating a facade method `-> None` while its body does `return
   self.entity.api.sync.call_service(...)` would raise Pyright `reportReturnType`
   and fail AC#7. Omitting the annotation lets Pyright infer `ServiceResponse |
   None` — no error, and consistent with every existing base-facade method. (The
   async entity methods differ — they are typed `-> Coroutine[Any, Any, None]`
   because they delegate to `api.call_service`, whose coroutine resolves to the
   service response; the sync facade has already resolved it.)

   The facade does **not** redeclare `entity` or `__init__`. Its methods only
   touch base-level members (`self.entity.api`, `.domain`, `.entity_id`), so the
   inherited `entity: BaseEntity[StateT, StateValueT]` and base `__init__` are
   sufficient. This avoids `reportIncompatibleVariableOverride` and
   `__init__`-override friction entirely.

2. **Add the `.sync` property override** inside the entity class:

   ```python
   @property
   def sync(self) -> "CoverEntitySyncFacade":
       if self._sync is None:
           self._sync = CoverEntitySyncFacade(entity=self)
       return cast("CoverEntitySyncFacade", self._sync)
   ```

   `_sync` is declared on `BaseEntity` as
   `BaseEntitySyncFacade[StateT, StateValueT] | None`. A domain facade instance
   fits that slot (it is a subclass), so caching reuses the base slot. The
   getter return type is narrowed to the domain facade; the `cast` reconciles the
   widened `_sync` field type. Narrowing a property getter's return type in a
   subclass is permitted by Pyright. The forward reference is quoted because the
   facade class is defined after the entity class in the same module.

3. **Imports.** The `.sync` override needs `cast`; add `from typing import cast`
   (the template currently imports `Any` and conditionally `Literal`). The facade
   needs `BaseEntity`'s sibling `BaseEntitySyncFacade` — extend the existing
   `from .base import BaseEntity` to `from .base import BaseEntity,
   BaseEntitySyncFacade`.

### Export generation

`__init__.py` is regenerated by the init generator, which scans every
non-underscore `ClassDef` in the package. The new `{Domain}EntitySyncFacade`
classes are picked up automatically — no manual export edits, satisfying FR#6.

### Regeneration

After the template change, regenerate all domains and verify:

```bash
git clone --depth 1 --branch "$(cat codegen/ha-version.txt)" \
  https://github.com/home-assistant/core.git ha-core   # if not already present
cd codegen && uv run hassette-codegen generate --ha-core-path ../ha-core
cd codegen && uv run hassette-codegen generate --ha-core-path ../ha-core --check  # exits 0
```

This overwrites all 25+ `src/hassette/models/entities/{domain}.py` files and
`__init__.py`. A pre-flight `grep -rn "def sync" src/hassette/models/entities/`
confirms no domain file currently hand-defines `.sync` (only `base.py` does), so
regeneration overwrites nothing bespoke.

## Replacement Targets

No existing code is being replaced. This change is purely additive: it adds a
facade class and a `.sync` override per domain. The base `turn_on/off/toggle`
facade methods remain the inheritance base.

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
the `run_sync` machinery. Domain facades generalize this to `call_service`.

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

The facade method is this body with `self.api` → `self.entity.api.sync` and the
return type `None`.

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

## Alternatives Considered

- **Reuse `gen_wrapper()` from `sync_facade/generic.py`** (as the issue's Context
  suggested). Rejected: `gen_wrapper()` emits `self.task_bucket.run_sync(...)`,
  but the facade has no `task_bucket`. The established entity-facade delegation is
  `self.entity.api.sync.*`. Forcing `gen_wrapper()` here would require bolting a
  `task_bucket` onto `BaseEntitySyncFacade` — adding state to fit a tool rather
  than using the existing, simpler delegation.
- **Construct the facade fresh on every `.sync` access** (no caching, no `cast`).
  Rejected for consistency: `BaseEntity.sync` caches in `_sync`, and matching that
  keeps base and domain behavior identical. The `cast` cost is one import.
- **Block on #938 and build entity facades into a consolidated table-driven
  generator.** Rejected: the two paths are structurally decoupled; blocking would
  stall #959 for no architectural gain.
- **Do nothing / keep manual `run_sync`.** Rejected: it leaves the sync facade
  contract broken for every domain-specific action — the problem this solves.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/test_recording_sync_facade.py` — exercises the Api sync facade
  (`api.sync.*`) directly, not `entity.sync.*`. It should pass unchanged; confirm
  the regenerated entity files don't break its imports of `LightEntity`.
- `tests/unit/test_entity_coroutine_conversion.py` — exercises the entity `.sync`
  path (`test_entity_sync_turn_on_registers`). Confirm the narrowed `.sync`
  return type (`LightEntitySyncFacade` instead of base) stays call-compatible
  with its existing assertions.
- `codegen/tests/test_entity_generator.py` — extend (see below); existing
  `test_output_compiles` already validates the facade block parses.

### New Test Coverage

- **Codegen structural** (`codegen/tests/test_entity_generator.py`): assert the
  rendered output for a domain contains `class {Domain}EntitySyncFacade`, a `def
  sync` property override, and one facade method per service with matching
  parameter signatures. (FR#1, FR#2, FR#3)
- **Runtime dispatch** (`tests/unit/test_recording_sync_facade.py` or a new
  `tests/unit/test_sync_entity_facade.py`): construct domain entities via the
  recording-api test infrastructure and assert dispatch for: a no-param method
  (`CoverEntitySyncFacade.open_cover`), a required-param method
  (`ClimateEntitySyncFacade.set_temperature(temperature=21.0)`), an optional-param
  method (`LightEntitySyncFacade.turn_on(brightness=128)`), and that `.sync`
  returns the domain facade type. (FR#2, FR#3, FR#4, FR#5)

### Tests to Remove

No tests to remove.

## Documentation Updates

- **`docs/` entity / sync-facade page** — if the docs site documents the `.sync`
  facade and lists which methods it covers, update it to state that domain
  actions are now available synchronously. Locate via
  `grep -rln "sync" docs/` for the entity/AppSync pages; update the page that
  describes the sync facade contract.
- **Docstrings** — the generated facade methods carry a one-line docstring from
  the template; ensure it reads correctly for the sync variant (no "must be
  awaited" wording, since these are synchronous).
- **CHANGELOG** — none (release-please generates it from the conventional commit;
  use `feat:` so it lands in the Features section).

## Impact

### Changed Files

- `codegen/src/hassette_codegen/templates/entity_wrapper.py.j2` — the only
  hand-edited source change (facade block, `.sync` override, imports).
- `src/hassette/models/entities/{domain}.py` (all 25+ service-bearing domains) —
  regenerated.
- `src/hassette/models/entities/__init__.py` — regenerated (new exports).
- `codegen/tests/test_entity_generator.py` — extended assertions.
- `tests/unit/test_recording_sync_facade.py` (or new `test_sync_entity_facade.py`)
  — runtime dispatch tests.

### Behavioral Invariants

- `entity.sync.turn_on()` / `.turn_off()` / `.toggle()` must keep working for
  every domain (inherited from `BaseEntitySyncFacade`).
- The async entity methods (`entity.open_cover()`, etc.) are unchanged.
- State-only domains (no services) still emit no entity file.
- The `forgotten_await` guard behavior on async methods is untouched — facade
  methods are synchronous and return `None`, so they are outside that mechanism.

<!-- Gap check 2026-06-12: 1 hit, compatible (no fix needed) — tests/unit/test_entity_coroutine_conversion.py:322 calls entity.sync.turn_on() via the inherited base route; LightEntity.sync becomes LightEntitySyncFacade (subclass), route preserved → T03 Verify (confirm still green). No external consumers of *EntitySyncFacade (additive). -->

### Blast Radius

Limited to sync `AppSync` authors, who gain new methods. No async author is
affected. No runtime path other than the entity facade changes. The codegen
template change ripples only into generated entity files, all verified by the
`--check` freshness gate and Pyright.

## Open Questions

None.
