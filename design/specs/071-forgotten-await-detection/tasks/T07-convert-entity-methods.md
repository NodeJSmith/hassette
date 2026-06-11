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
   Add `from collections.abc import Coroutine` and `from typing import Any` as **unconditional**
   top-level imports in the template. CRITICAL: today the `Any` import is gated on
   `{% if needs_any %}` (template lines 1-6), and `needs_any` (`generators/entities.py:78`) checks
   *parameter* types only — 26 of 31 generated files have no `Any`-typed parameter, so keeping the
   gate produces a hard `NameError` on module import once the return annotations carry
   `Coroutine[Any, Any, None]`. The return annotation always needs both names: make them
   unconditional and simplify the template's conditional block to gate only `Literal`
   (`type_aliases`); `needs_any` can then be dropped from the generator context if unused.
2. **`src/hassette/models/entities/base.py`**: convert the hand-written `BaseEntity.turn_on`,
   `turn_off`, `toggle` (currently `async def ... return await self.api.turn_on/turn_off/toggle_service(...)`)
   to Shape B `def ... -> Coroutine[Any, Any, None]: return self.api.<method>(...)`. They delegate to
   the api methods converted in T04, so they return the api handle directly.
3. **`BaseEntitySyncFacade`** (same file, the runtime sync facade with `turn_on`/`turn_off`/`toggle`):
   verify it still registers. Note HOW it works: it routes through `self.entity.api.sync.turn_on(...)`
   (the generated api sync facade, regenerated in T05), **bypassing the entity's async method
   entirely** — it does not drive the entity method through `run_sync`. The `entity.sync.turn_on()`
   test is therefore regression coverage of the `api.sync` path; the test that exercises the entity
   conversion itself is a direct `await entity.turn_on()`. No facade code change expected.
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
