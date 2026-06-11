# Handoff: forgotten-await detection feature

**Date:** 2026-06-10 (evening) → pick up 2026-06-11 morning
**Branch / worktree:** `warn-no-await` at `.claude/worktrees/warn-no-await` (currently identical to `main`, no code written yet)
**Next action:** run `/mine.define` to turn the design below into a spec.

## The problem (one line)

In Hassette, registration/side-effect methods (`bus.on_*`, `scheduler.run_*`, `api.call_service`/`set_state`/`fire_event`) are `async`. Forgetting `await` drops the coroutine silently — the listener never registers, no error. This is the highest-impact silent footgun in the framework.

## What we decided last night

Prior-art research is saved next to this file in `research.md` (6 patterns, sourced). We landed on **defense in depth** and made these decisions:

1. **Static layer (Pyright `reportUnusedCoroutine`)** — already on by default in CI. Confirmed direction. BUT: most users won't run CI/Pyright on their personal apps, so this alone isn't enough for them.
   - **Decision → ship a user-facing CLI command** (e.g. `hassette check`) that scans the user's app modules for un-awaited calls to hassette's known must-await methods.
   - Open sub-decision for `/mine.define`: (a) a small **AST scan that hassette maintains** for its own method list, vs (b) **shell out to Pyright** if installed. Note: this revives "Pattern 3 (must-await registry)" from the brief — which I'd originally said to skip *as a third-party plugin*. As a **hassette-owned** command it's fine, because hassette owns its own method list.

2. **Runtime backstop = the real feature. Confirmed, definitely doing this.**
   - Return a **self-reporting awaitable wrapper** from *only* the fire-and-forget methods (not data-returning ones like `get_state()` — those fail loudly downstream).
   - Wrapper sets `_awaited = True` in `__await__`, delegates to the real coroutine, captures the creation stack eagerly (aiohttp `_source_traceback` style), and in `__del__` — if never awaited — emits a warning naming the offending app.
   - This is CPython's own `CoroWrapper` pattern (PEP 492) — blessed, not invented.

3. **Escalation control (IGNORE / LOG / ERROR enum).** Confirmed. Mirror HA's `ReportBehavior`. Ships as a warning, can harden to a hard error later.

## Scope: which methods get protected

Cross-framework consensus: **only methods where a dropped result is a silent no-op.**
- ✅ Protect: `bus.on_state_change` / `on_attribute_change` / `on_call_service` / `on` (+ the HA lifecycle `on_*` hooks); `scheduler.run_in` / `run_once` / `run_every` / `run_minutely` / `run_hourly` / `run_daily` / `run_cron` / `add_job`; `api.call_service` / `fire_event` / `set_state` / `turn_on` / `turn_off` / `toggle_service`.
- ❌ Don't bother: `get_state` / `get_states` / `get_entity` / `get_history` — these return data, so a missing await blows up downstream with an `AttributeError`. Not silent.

## Corrections / gotchas to remember

- **Frame attribution does NOT use a `src/hassette/` path match.** In a real install, hassette lives in site-packages and the user's app is the foreground code. The dev-tree path `src/hassette/` won't exist for users. Resolve the boundary by **module name** instead: walk the stack to the first frame whose module does *not* start with `hassette.` (or isn't under the `hassette` package `__path__`). This is more robust than HA's path-substring heuristic — don't copy HA's path matching literally.
- **"Check at app startup" (the original framing) is the weakest angle** — a dropped coroutine is already gone by the time `on_initialize` returns, so you can't find it by inspecting the app object. The real levers are static (before runtime) + the wrapper (reports near the drop). Don't design a startup-scan-the-app-object approach.
- **Type-checker blind spot:** Pyright/mypy both silently miss a coroutine used as an `if`/`while` condition or assigned to `_`. The runtime wrapper covers this gap. Worth a docs note.
- **Wrapper caveats:** still GC-timed (late), `__del__` warnings easy to miss, a lingering reference suppresses the warning, and per-call stack capture has a small cost — mitigate by capturing only for the protected methods (or behind a debug flag).

## Reference implementations to crib from (in `/mine.define`)

- **HA frame helper (gold standard for attribution):** https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/frame.py — `get_integration_frame()`, `report_usage()`, `ReportBehavior` enum. Adapt the module-name boundary, not its path match.
- **CPython `CoroWrapper`:** the warn-in-`__del__` pattern. https://github.com/python/cpython/blob/3.10/Lib/asyncio/coroutines.py
- **aiohttp `ClientResponse.__del__` / `_source_traceback`:** template for eager stack capture + GC-time warning. https://github.com/aio-libs/aiohttp/blob/master/aiohttp/client_reqrep.py
- **PyO3 #3597:** canonical self-reporting-awaitable discussion. https://github.com/PyO3/pyo3/issues/3597

## Codebase hooks (from local exploration)

- Registration methods: `src/hassette/bus/bus.py`, `src/hassette/scheduler/scheduler.py`, `src/hassette/api/api.py`.
- App lifecycle: `src/hassette/app/app.py` (`on_initialize` / `on_shutdown`), `src/hassette/core/app_handler.py`, `AppLifecycleService` (`initialize_instances()`, `reconcile_app_registrations()`).
- Precedent for `warnings.warn()`: `src/hassette/core/migration_runner.py` (deprecation notices).
- CLI lives in `src/hassette/cli/` — where `hassette check` would go.
- No existing coroutine/frame/AST machinery. `ListenerNameRequiredError` is the only call-time validation precedent.

## When implementing (don't forget — project rules)

- This touches user-facing API → **docs + frontend completeness rules apply** (`.claude/rules/design-completeness.md`). New CLI command needs docs-site coverage. Check whether the escalation setting surfaces anywhere in the UI.
- New CLI command → consider `/cli-affordances` / `/cli-output` for the UX.
- Voice guide applies to any docs written (`.claude/rules/voice-guide.md`).
- TDD discipline for the wrapper (CLAUDE.md "Bug Investigation Workflow"): the `__del__`-fires-warning behavior and the `_awaited` flag are exactly the kind of timing/GC behavior that needs a real test, not inspection. `gc.collect()` + `pytest.warns` is the likely test shape.

## Files

- `design/research/2026-06-10-forgotten-await-detection/research.md` — full prior-art brief
- `design/research/2026-06-10-forgotten-await-detection/HANDOFF.md` — this file
