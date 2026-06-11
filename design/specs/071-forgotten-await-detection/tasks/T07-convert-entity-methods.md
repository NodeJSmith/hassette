---
task_id: "T07"
title: "Protect entity service methods via the codegen template"
status: "planned"
depends_on: ["T04", "T05"]
implements: ["FR#13", "AC#11"]
---

## Summary

Bring the entity classes into scope — the highest-traffic user surface. Every domain entity
(`LightEntity`, `HumidifierEntity`, …) exposes generated fire-and-forget service methods
(`turn_on`, `set_humidity`, …), all Shape B delegates to `api.call_service`. Because they are
generated from one Jinja template, protection is delivered by changing the template + regenerating,
not by editing 31 files. `BaseEntity`'s three hand-written delegates and the `BaseEntitySyncFacade`
are handled directly.

## Prompt

Per the design doc's `## Architecture` → "Entity-wrapper codegen", FR#13, and AC#11:

1. **Template** `codegen/src/hassette_codegen/templates/entity_wrapper.py.j2`: change both method
   branches (with-params and no-params) from
   `async def {{ service.method_name }}(...) -> None: await self.api.call_service(...)` to
   `def {{ service.method_name }}(...) -> Coroutine[Any, Any, None]: return self.api.call_service(...)`.
   Add `from collections.abc import Coroutine` and `from typing import Any` to the template's import
   block (and to `codegen/.../generators/entities.py` if it assembles the import list).
2. **`src/hassette/models/entities/base.py`**: convert the hand-written `BaseEntity.turn_on`,
   `turn_off`, `toggle` (currently `async def ... return await self.api.turn_on/turn_off/toggle_service(...)`)
   to Shape B `def ... -> Coroutine[Any, Any, None]: return self.api.<method>(...)`. They delegate to
   the api methods converted in T04, so they return the api handle directly.
3. **`BaseEntitySyncFacade`** (same file, the runtime sync facade with `turn_on`/`turn_off`/`toggle`):
   verify it still registers. It drives the entity method via `run_sync`; the entity method now
   returns a `RegistrationHandle` (a `collections.abc.Coroutine`, so `asyncio.iscoroutine` accepts it)
   — confirm with a test, adjust only if `run_sync` is fed something other than the handle.
4. **Regenerate** all `src/hassette/models/entities/*.py` via the `hassette-codegen` pipeline (the same
   CLI used in T05; the entity pipeline writes `entities_dir / {domain}.py` from the template). Confirm
   the regenerated files use `def -> Coroutine[...]` and the codegen freshness gate is green.

Add representative tests (TDD — failing test first): `LightEntity.turn_on` (no params),
`HumidifierEntity.set_humidity` (with params), and `BaseEntity.toggle` — each warns
(`pytest.warns(HassetteForgottenAwaitWarning)`) on a dropped un-awaited call attributed to the
caller, acts as today when awaited, and `entity.sync.turn_on()` registers. Run the affected entity
tests + `uv run pyright` locally.

## Prompt notes / scope

Only fire-and-forget entity service methods are in scope. Do NOT convert entity *property* accessors
(`attributes`, `value`, `entity_id`, …) or the async `refresh()` data-returning method — those are
not fire-and-forget. Do NOT add per-domain sync facades (out of scope; only `BaseEntitySyncFacade`'s
three methods exist today).

## Focus

- Entities are generated: `codegen/.../pipeline.py:96-106` writes each `models/entities/{domain}.py`
  from `generate_entity_wrapper` (`generators/entities.py`) using `templates/entity_wrapper.py.j2`.
  The template (lines ~29-58) has the two branches to change. This is the whole win — one template,
  31 regenerated files.
- `BaseEntity.turn_on/turn_off/toggle` at `models/entities/base.py:62-72` delegate to
  `self.api.turn_on/turn_off/toggle_service` — those are themselves Shape B (→ `call_service`) after
  T04, so `BaseEntity.turn_on` returns the api handle through two delegate hops; attribution still
  walks past all `hassette.*` frames to the user.
- `BaseEntitySyncFacade` at `base.py:75-91` is hand-written runtime (not generated, not per-entity).
- This task MUST come after T04 (entity methods delegate to the converted `api.call_service`/
  `turn_on`) and after T05 (codegen-package changes land in order; avoid two tasks editing `codegen/`
  out of sequence).
- Do NOT hand-edit the generated `models/entities/*.py` — change the template and regenerate.

## Verify

- [ ] FR#13: every generated entity service method and `BaseEntity.turn_on`/`turn_off`/`toggle` is `def -> Coroutine[Any, Any, None]` returning the api handle; a forgotten `await` on `entity.turn_on()` / `entity.set_humidity(...)` emits `HassetteForgottenAwaitWarning` attributed to the caller; `BaseEntitySyncFacade` still registers via `run_sync`.
- [ ] AC#11: tests for `LightEntity.turn_on`, `HumidifierEntity.set_humidity`, and `BaseEntity.toggle` assert forgotten-await warning (attributed), correct awaited behavior, and `entity.sync.turn_on()` registration; a regen check confirms `models/entities/*.py` use `def -> Coroutine[...]` and the codegen freshness gate passes.
