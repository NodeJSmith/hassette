---
task_id: "T05"
title: "Update codegen, regenerate sync facades, fix parity and cleanup-guard tests"
status: "done"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#11", "AC#7", "AC#9", "AC#10"]
---

## Summary

De-asyncing the public methods (T02–T04) breaks every mechanism that detects "async-ness" via
`ast.AsyncFunctionDef` or `inspect.iscoroutinefunction`/`inspect.iscoroutine`. This task fixes them in
the same wave: widen the sync-facade codegen to also match `def -> Coroutine[...]`, regenerate the
three sync facades and the RecordingApi facade, fix the two RecordingApi parity tests to discover
methods by return annotation (OR-semantics), and switch two cleanup-guard tests from
`inspect.iscoroutine` to `asyncio.iscoroutine`. Without this, sync (`AppSync`) registration silently
drops and the parity tests pass vacuously.

## Prompt

Per the design doc's `## Architecture` → "Codegen and parity-test updates" and `## Replacement
Targets`:

1. **Widen `is_wrappable`** in `codegen/src/hassette_codegen/sync_facade/ast_utils.py` (line ~169) to
   also return `True` for a plain `def` whose return annotation is a `Coroutine[...]` subscript
   (`ast.Subscript` with `.value.id == "Coroutine"`), in addition to `ast.AsyncFunctionDef`. Change
   its return type from `TypeGuard[ast.AsyncFunctionDef]` to
   `TypeGuard[ast.FunctionDef | ast.AsyncFunctionDef]`. Update `gen_wrapper`'s parameter type
   (`generic.py:209`) to `ast.FunctionDef | ast.AsyncFunctionDef` (the fields used exist on both).
   The `is_overload` exclusion and lifecycle-method exclusions already apply to both paths.
   **CRITICAL — also fix the `is_delegatable` overlap:** `generic.py:270-271` runs `is_wrappable`
   and `is_delegatable` independently over the class body. A converted `def -> Coroutine[...]`
   matches BOTH after the widening (it is a plain public `def`), so the generated facade would
   contain two definitions of each registration method — one `run_sync`-wrapped, one bare
   passthrough — and Python keeps the last one (the passthrough), silently breaking sync
   registration. Add `and not is_wrappable(node)` to the delegates comprehension (generic.py:271)
   or to `is_delegatable` itself (ast_utils.py:183).
2. **RecordingApi codegen** (`recording.py:134-137` and `147-150`) hard-filters on
   `isinstance(node, ast.AsyncFunctionDef)` — apply the same `def -> Coroutine[...]` widening so the
   six converted api write methods stay in the generated facade. Cascading annotation-only fixes
   (Pyright runs on `codegen/` in CI): widen the `ast.AsyncFunctionDef` parameter annotations in
   `recording_transform.py:97,171,194` and `recording_imports.py:196` to
   `ast.FunctionDef | ast.AsyncFunctionDef`.
3. **Regenerate** the sync facades via the `hassette-codegen` CLI (entry point
   `hassette_codegen.__main__:main`; sync-facade subcommand under `sync_facade/cli.py` /
   `__main__.py` — run `uv run hassette-codegen --help` to find the exact invocation). Regenerate
   `src/hassette/bus/sync.py`, `src/hassette/scheduler/sync.py`, `src/hassette/api/sync.py`, and the
   RecordingApi sync facade. Confirm the regenerated files still contain `run_sync`-wrapped
   registration methods (not bare passthrough delegates).
4. **Fix the two parity tests** — `tests/unit/test_recording_api_protocol_parity.py:28` and
   `test_recording_api_write_parity.py:73`. Their `public_async_methods` discovers via
   `inspect.iscoroutinefunction`; change to **OR semantics**:
   `iscoroutinefunction(m) or getattr(get_type_hints(m).get("return"), "__origin__", None) is
   collections.abc.Coroutine`. Use the `getattr(..., "__origin__", None)` form — non-generic return
   types (`-> SomeClass`) have no `__origin__`, and a bare attribute access would crash the tests
   with an `AttributeError` when a plain sync method is added later. (No
   `from __future__ import annotations` in the source modules, so `get_type_hints` resolves at
   runtime — verified.)
5. **Fix cleanup guards** — `tests/integration/test_registration.py:79` and
   `tests/unit/test_scheduler_resource.py:164` guard cleanup with
   `if inspect.iscoroutine(coro): coro.close()`. `inspect.iscoroutine` returns `False` for a
   `RegistrationHandle` (it checks the `CO_COROUTINE` code-object flag; only `asyncio.iscoroutine`
   returns `True`). Switch them to `asyncio.iscoroutine(coro)` (or
   `isinstance(coro, collections.abc.Coroutine)`).
6. **Add a sync-facade registration test**: call a protected method through each sync facade
   (`bus.sync` / `scheduler.sync` / `api.sync`) and assert the listener/job actually registers
   (exercises `asyncio.iscoroutine(handle)` + `task_bucket.run_sync` driving it to completion).

Run `uv run pyright` on `codegen/` and the regenerated files, run the parity tests, the two
cleanup-guard test files, and the codegen tests locally; confirm all pass. The schema/codegen
freshness gate must be green (regenerated output committed).

## Focus

- Confirmed by review: `is_wrappable` at `ast_utils.py:169`; `gen_wrapper` at `generic.py:209`;
  RecordingApi filters at `recording.py:134-137,147-150`; cascading params at
  `recording_transform.py:97,171,194` and `recording_imports.py:196`. All verified.
- `task_bucket.run_sync` (`src/hassette/task_bucket/task_bucket.py`) is **unchanged** but relies on
  two handle properties delivered by T01: `asyncio.iscoroutine(handle)` is `True` (so
  `asyncio.run_coroutine_threadsafe` at line 238 accepts it) and `handle.__name__` exists (logged at
  lines 241,244 on error paths; line 234 calls `fn.close()` in the in-loop path — the handle's
  `close()` sets `_awaited=True` so no spurious warning). If T01 didn't deliver these, flag it.
- The generated sync facade files carry a "Do not edit this file directly" header — regenerate, do
  not hand-edit.
- This task MUST follow T02–T04 (the methods must already be converted before regeneration and before
  the parity tests can be meaningfully fixed).

## Verify

- [ ] FR#11: calling a protected method through each sync facade (`bus.sync`/`scheduler.sync`/`api.sync`) registers the listener/job — verified by a test asserting the registration took effect.
- [ ] AC#7: a test drives a protected method through a sync facade and asserts the handle passes `asyncio.iscoroutine` and `run_sync` completes the registration.
- [ ] AC#9: after regeneration, `git diff` shows the sync facade files still contain `run_sync`-wrapped registration methods (not bare passthrough delegates), and the codegen/schema freshness check passes.
- [ ] AC#10: both RecordingApi parity tests still discover all six converted api write methods (OR-semantics) and continue to assert parity — they are not vacuously passing.
