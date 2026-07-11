---
task_id: "T04"
title: "Regenerate sync facades and widen cleanup timeout types"
status: "planned"
depends_on: ["T02", "T03"]
implements: ["FR#10", "FR#11", "AC#9"]
---

## Summary
Regenerate both sync facade files via the codegen tool (they pick up all signature changes from T02 and T03 automatically), and widen `cleanup` timeout from `int | None` to `float | None` on App, Resource, and DatabaseService. Run the full test suite to verify all core code changes work together.

## Target Files
- regenerate: `src/hassette/scheduler/sync.py`
- regenerate: `src/hassette/bus/sync.py`
- modify: `src/hassette/app/app.py`
- modify: `src/hassette/resources/base.py`
- modify: `src/hassette/core/database_service.py`
- read: `.pre-commit-config.yaml` (codegen hook names)

## Prompt
**1. Regenerate sync facades** — the codegen tool automatically picks up `*` position changes, `name` type changes, and `on_error` additions from the async source files. Run the codegen commands that the pre-commit hooks use:

Check `.pre-commit-config.yaml` for the exact commands under `generate_scheduler_sync_facade` and `generate_bus_sync_facade` hooks, and run them. The hooks are listed at lines 98 and 108.

After regeneration, verify the generated files have:
- `SchedulerSyncFacade`: `name` is keyword-only (after `*`) with no default on all 8 methods
- `BusSyncFacade`: `on_homeassistant_*` methods have `*` and keyword-only params; all methods have `name: str` (no default); delegate methods include `on_error`
- All delegation calls use keyword args (not positional) for the now-keyword-only params

**2. Widen timeout types** — change `timeout: int | None = None` to `timeout: float | None = None` on:
- `src/hassette/app/app.py:152` — `App.cleanup()`
- `src/hassette/resources/base.py:621` — `Resource.cleanup()`
- `src/hassette/core/database_service.py:347` — `DatabaseService.cleanup()`

Do NOT change `remote.py` — those mirror HA's service schema.

Also update the docstrings on all three `cleanup` methods to reflect the `float` type (if they mention `int`).

**3. Run the full test suite** — `uv run nox -s dev` to verify all core code changes from T01-T04 work together.

## Focus
The sync facade codegen reads the async source's AST. For keyword-only params, `format_signature_and_call()` in `codegen/src/hassette_codegen/sync_facade/ast_utils.py:78-134` emits `param=param` delegation style automatically. No manual intervention needed.

If the codegen tool isn't on PATH, check `.pre-commit-config.yaml` for the exact `entry:` command.

The timeout type change is mechanical — `int` → `float` in the annotation only. No behavioral change (Python's `int` is a subtype of `float` in practice).

## Verify
- [ ] FR#10: `App.cleanup`, `Resource.cleanup`, `DatabaseService.cleanup` accept `timeout: float | None`
- [ ] FR#11: Generated `SchedulerSyncFacade` and `BusSyncFacade` mirror their async counterparts' signature changes
- [ ] AC#9: `uv run nox -s dev` passes with all changes from T01-T04
