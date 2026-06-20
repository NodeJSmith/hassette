---
task_id: "T01"
title: "Move await_guard to utils, add api->core RULE"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#7", "AC#3", "AC#6"]
---

## Summary
Move `src/hassette/core/await_guard.py` to `src/hassette/utils/await_guard.py` — it is a pure leaf utility (imports only `exceptions` + `types.enums`) that is wrongly housed in `core`. Update the three `src/` importers and the four test importers to the new path. This retires the `api → core` runtime cycle fully (`guard_await` was `api`'s only runtime `core` import). Then add the first boundary RULE forbidding `api` from runtime-importing `hassette.core`. This is the lowest-risk unit and lands first.

## Target Files
- create: `src/hassette/utils/await_guard.py` (moved from core; content unchanged except internal references if any)
- delete: `src/hassette/core/await_guard.py`
- modify: `src/hassette/api/api.py` (line 173 import path)
- modify: `src/hassette/bus/bus.py` (line 101 import path)
- modify: `src/hassette/scheduler/scheduler.py` (line 74 import path)
- modify: `tools/check_module_boundaries.py` (append the api->core Rule)
- modify: `tests/unit/core/test_await_guard.py` (line 31 import path; optionally relocate file to tests/unit/utils/)
- modify: `tests/unit/scheduler/test_scheduler_coroutine_conversion.py` (line 19 import path)
- modify: `tests/unit/test_api_coroutine_conversion.py` (line 19 import path)
- modify: `tests/unit/bus/test_bus_coroutine_conversion.py` (line 22 import path)
- read: `design/specs/078-break-import-cycles-clean-wins/design.md` (Architecture → Change 1; Change 4)
- read: `design/specs/078-break-import-cycles-clean-wins/tasks/context.md`

## Prompt
Read `context.md` and the design doc's `## Architecture` → "Change 1" and "Change 4" sections.

1. **Move the file.** Move `src/hassette/core/await_guard.py` to `src/hassette/utils/await_guard.py`. The module body does not change — it already imports only `hassette.exceptions` and `hassette.types.enums`, both of which sit below `utils`, so no new cycle is created. Preserve the module docstring (it references `design/specs/071-forgotten-await-detection/design.md`).
2. **Update the three production importers** to `from hassette.utils.await_guard import guard_await`:
   - `src/hassette/api/api.py:173`
   - `src/hassette/bus/bus.py:101`
   - `src/hassette/scheduler/scheduler.py:74`
3. **Update the four test importers** (they import `RegistrationHandle` and/or `guard_await`) to the new path:
   - `tests/unit/core/test_await_guard.py:31`
   - `tests/unit/scheduler/test_scheduler_coroutine_conversion.py:19`
   - `tests/unit/test_api_coroutine_conversion.py:19`
   - `tests/unit/bus/test_bus_coroutine_conversion.py:22`
   Optionally relocate `tests/unit/core/test_await_guard.py` to `tests/unit/utils/test_await_guard.py` to mirror the source move — only if `tests/unit/utils/` exists or is trivial to create; otherwise just fix the import. Do not change any test assertions.
4. **Add the boundary RULE.** In `tools/check_module_boundaries.py`, append a `Rule` to `RULES` (all four fields required — see the Convention Example in context.md):
   - `name`: e.g. `"api-no-core"`
   - `applies=lambda layer: layer == "api"`
   - `forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core.")`
   - `reason`: a one-line explanation that `api` must not import `core` (core sits above the service layer; #1079).
   Note `applies` receives the bare layer name from `layer_of()`, not a dotted path.

Do NOT add a `bus` or `scheduler` rule — those cycles persist (bus imports `core.commands.InvokeHandler`, scheduler imports `SchedulerService`).

## Focus
- `guard_await` is used at multiple call sites inside `api.py`, `bus.py`, `scheduler.py` (e.g. `api.py:445,518,894`), but the **import** is single per file — only the import line changes.
- `await_guard.py` also defines `RegistrationHandle[T]`; the four test files import that symbol. Moving the whole module keeps `RegistrationHandle` and `guard_await` together.
- The indented `from hassette.core...` imports in `api.py:214`, `bus.py:122`, etc. sit inside `if typing.TYPE_CHECKING:` blocks (which is exactly why the boundary checker exempts them) — they are NOT touched and do not violate the new RULE.
- After the move, `api/` has zero runtime `core` imports; `bus/` and `scheduler/` still import `core` (expected, out of scope) — so the RULE is `api`-only.
- Verify the move did not orphan anything: `grep -rn "core.await_guard\|core import await_guard" src tests` should return nothing after the edits.

## Verify
- [ ] FR#1: `from hassette.utils.await_guard import guard_await, RegistrationHandle` succeeds; `src/hassette/core/await_guard.py` no longer exists; `api/api.py`, `bus/bus.py`, `scheduler/scheduler.py` import from `hassette.utils.await_guard`.
- [ ] FR#2: `grep -rn "from hassette.core" src/hassette/api` returns only `TYPE_CHECKING`-guarded lines (no runtime `core` import remains in `api/`).
- [ ] FR#7: `tools/check_module_boundaries.py` `RULES` contains an `api`-layer rule forbidding `hassette.core[.*]`, with all four `Rule` fields populated.
- [ ] AC#3: inserting a throwaway top-level `from hassette.core.core import Hassette` into any `api/` file makes `python tools/check_module_boundaries.py` exit non-zero; the clean tree exits zero.
- [ ] AC#6: `grep -rn "from hassette.core" src/hassette/api` returns only `TYPE_CHECKING`-guarded lines (the `api` half of AC#6; the `web` half is verified in T03). Sanity: `uv run pyright` reports zero new errors and the four adapted test files pass (`uv run pytest tests/unit/core/test_await_guard.py tests/unit/bus/test_bus_coroutine_conversion.py tests/unit/scheduler/test_scheduler_coroutine_conversion.py tests/unit/test_api_coroutine_conversion.py`).
