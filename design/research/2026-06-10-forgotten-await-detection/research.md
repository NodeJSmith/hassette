---
topic: "detecting forgotten await on framework async methods"
date: 2026-06-10
status: Draft
---

# Prior Art: Detecting a Forgotten `await` on Framework Async Methods

## The Problem

In an async-first framework, methods like `bus.on_state_change(...)` or `api.call_service(...)` return a coroutine. If the user forgets `await`, the coroutine is created and immediately dropped — the listener never registers, the service never fires, and there is **no error**. Python's only built-in signal is a `RuntimeWarning: coroutine '...' was never awaited`, emitted by the garbage collector at a nondeterministic later time, with no indication of which app caused it. For a framework whose whole value proposition is "register handlers and they run," this is the single highest-impact silent failure mode.

## How We Do It Today

Hassette has **no** detection machinery for this. There is `ListenerNameRequiredError` (raised at call time when `name=` is omitted), and the migration runner uses `warnings.warn()` for deprecations — but nothing inspects coroutines, walks frames, or runs AST/type analysis on user apps. The `warn-no-await` branch is currently identical to `main` (no work started). The framework/user boundary is clean (`src/hassette/` vs. user app modules), and `AppLifecycleService.initialize_instances()` (after `await inst.initialize()`) is a natural hook point.

## Patterns Found

### Pattern 1: Built-in GC RuntimeWarning (the baseline, do nothing)

**Used by**: Every async-Python program, inherited from CPython.
**How it works**: When a never-awaited coroutine's refcount hits zero, CPython emits `RuntimeWarning: coroutine '...' was never awaited`. asyncio debug mode (`PYTHONASYNCIODEBUG=1`, `loop.set_debug(True)`, `sys.set_coroutine_origin_tracking_depth`) adds a "Coroutine created at" traceback.
**Strengths**: Zero code; can be promoted to a hard error via `warnings.filterwarnings("error", ...)` or `-W error`.
**Weaknesses**: Fires at GC time (late, nondeterministic, can point at the wrong place); doesn't name the offending app; suppressed entirely if any reference lingers; easy to miss in logs.
**Where they draw the line**: Every coroutine indiscriminately — no notion of which one mattered.
**Example**: https://docs.python.org/3/library/asyncio-dev.html

### Pattern 2: Type-checker "unused coroutine" diagnostic (static, earliest signal)

**Used by**: Pyright (`reportUnusedCoroutine`, **on by default**), mypy (`unused-coroutine` default + opt-in `unused-awaitable`).
**How it works**: The checker knows the call returns `Coroutine[...]`. A bare call statement whose result is discarded is flagged before the code runs. Requires the method to be honestly annotated as returning a coroutine.
**Strengths**: Earliest and most precise signal; exact call-site location; **free — Hassette already runs Pyright in CI**; no false attribution.
**Weaknesses**: Blind spot — a coroutine used as an `if`/`while` condition, passed to `bool()`, or assigned to `_` is silently dropped and *not* flagged. Only helps users who run a type checker; gives no runtime protection.
**Where they draw the line**: Any discarded Coroutine-returning statement — generic, not framework-specific.
**Example**: https://github.com/microsoft/pyright/issues/3563

### Pattern 3: Linter rule on a must-await registry (static, AST)

**Used by**: flake8-async (`ASYNC105` missing-await against a curated list; `ASYNC300` create-task-no-reference), partially in Ruff `ASYNC` rules.
**How it works**: A pure-AST linter carries a hardcoded set of must-await functions and flags un-awaited calls to them.
**Strengths**: Fast, CI-friendly, no type info needed for known-list cases.
**Weaknesses**: Reach limited to functions the plugin already knows (trio's API). A **custom plugin** would be required to teach it Hassette's methods. Ruff maintainers state generic unawaited detection "may not catch all cases" without type info.
**Where they draw the line**: Only methods on an explicit allowlist — the "registry of must-await methods" idea, maintained per-plugin.
**Example**: https://flake8-async.readthedocs.io/en/latest/rules.html

### Pattern 4: Self-reporting awaitable wrapper (runtime, warn in `__del__`)

**Used by**: CPython's own debug `CoroWrapper` (PEP 492); PyO3 (#3597, mimicking CPython); structurally identical to aiohttp's `ClientResponse.__del__` / `_source_traceback`.
**How it works**: Registration methods return a small awaitable wrapper instead of a bare coroutine. `__await__` sets `_awaited = True` and delegates to the real coroutine. The wrapper captures the creation stack eagerly. In `__del__`, if `_awaited` is still False, it emits a warning embedding the captured creation site — pointing straight at the line the user forgot to await.
**Strengths**: Works at runtime regardless of whether users run a type checker; embeds the precise creation site; **can be applied selectively to only the methods that matter**; the stdlib uses this exact technique (blessed pattern).
**Weaknesses**: Still GC-timed; `__del__` warnings easy to suppress/miss; per-call stack capture has a small cost (mitigate with a debug flag or protect only key methods); wrapper must faithfully proxy the coroutine protocol; a lingering reference suppresses the warning.
**Where they draw the line**: Author's choice — and that's the advantage. Wrap *only* the fire-and-forget registration/side-effect methods whose dropped result is a silent no-op.
**Example**: https://github.com/PyO3/pyo3/issues/3597 ; https://github.com/aio-libs/aiohttp/blob/master/aiohttp/client_reqrep.py

### Pattern 5: Frame/stack inspection to attribute the mistake (runtime, attribution layer)

**Used by**: Home Assistant (`homeassistant/helpers/frame.py`) for blocking-call and thread-safety detection — same domain as Hassette.
**How it works**: On detecting a misuse, HA walks the stack outward (`get_integration_frame()`) to the first user-code frame, extracts the integration name, and routes through `report_usage()` with a `ReportBehavior` enum (`IGNORE` / `LOG` / `ERROR`) that differs for core vs. custom code and names the version a behavior will break in. `report_non_thread_safe_operation()` always raises.
**Strengths**: Turns an anonymous warning into "app `foo` did X at file:line." The IGNORE/LOG/ERROR enum gives a graceful warn-now/error-later escalation. Reusable across many footgun checks. **Cleaner for Hassette than for HA** — the `src/hassette/` boundary beats HA's path-substring heuristic.
**Weaknesses**: Stack walking has a cost (HA only does it once a problem is detected, never on the hot path); needs a stable framework/user boundary.
**Where they draw the line**: Specific known-dangerous APIs only (blocking `open`, thread-unsafe `async_*` methods), not universally. HA escalated these warn → block across releases.
**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/frame.py

### Pattern 6: Eliminate the footgun by design (sync registration / structured concurrency)

**Used by**: AppDaemon (sync-first registration), Trio (nurseries / structured concurrency).
**How it works**: AppDaemon's `listen_state` / `run_in` are synchronous and return immediately — no coroutine to drop. Trio forbids fire-and-forget: every task spawns into a nursery whose scope won't close until children finish, so an orphaned coroutine can't exist.
**Strengths**: The bug class is impossible by construction.
**Weaknesses**: A design constraint, not a retrofit. AppDaemon discourages async apps entirely; Trio imposes a stricter concurrency model. **Not available to Hassette**, which deliberately chose async-await registration.
**Where they draw the line**: N/A — the whole API surface avoids the problem.
**Example**: https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html ; https://trio.readthedocs.io/en/stable/reference-core.html

## Anti-Patterns

- **Relying solely on the default GC RuntimeWarning.** Late, GC-timed, unattributed, suppressed by any lingering reference. A backstop, not a solution. (https://superfastpython.com/asyncio-coroutine-was-never-awaited/)
- **Assuming a pure-AST linter catches "you forgot await" for your own methods.** It can't without type info or a maintained allowlist; Ruff maintainers say so. (https://github.com/astral-sh/ruff/issues/9833)
- **Trusting the type checker in conditional contexts.** Pyright and mypy both silently drop a coroutine used as an `if`/`while` condition. A static rule alone is not airtight. (https://github.com/microsoft/pyright/issues/9579)
- **`asyncio.create_task()` without keeping a reference** — the task can be GC'd mid-flight. The flip side of the same bug; flake8-async `ASYNC300` exists for it.

## Emerging Trends

- **Escalation ladders (warn → error → block).** HA's `ReportBehavior` enum + version-tagged deprecations; both its blocking-call and thread-safety checks visibly climbed the ladder across 2024.x.
- **Defense in depth is the consensus.** No single layer suffices — type checker for early/most cases, self-reporting awaitable + frame attribution for the runtime gap and the culprit's name. Mature frameworks combine a static signal with an attributed runtime report.

## Relevance to Us

The cross-framework consensus answers the open scope question directly: **protect only the methods where a dropped result is a silent no-op** — registration (`bus.on_*`), scheduling (`scheduler.run_*`), and fire-and-forget side effects (`api.call_service` / `set_state` / `fire_event`). Data-returning methods like `get_state()` fail loudly downstream and don't need this. That's where AppDaemon, HA, and the wrapper-using libraries all draw the line.

Two of Hassette's existing properties make the strongest patterns unusually cheap here:
1. **Pyright already runs in CI** with `reportUnusedCoroutine` on by default — Pattern 2 is nearly free, contingent only on the registration methods being annotated to return a coroutine (not swallowed behind a `-> None` or a decorator that erases the type).
2. **The `src/hassette/` framework/user boundary is explicit** — Pattern 5's frame attribution is cleaner than HA's path-substring heuristic. The first frame outside `src/hassette/` is the offending app.

The "check at app startup" framing in the original ask is the weakest fit: a dropped coroutine isn't observable by inspecting the app object after `on_initialize` returns — the coroutine is already gone. The realistic levers are (a) static, before runtime, and (b) the wrapper, which reports near the drop, not at a startup scan.

## Recommendation

Adopt **defense in depth**, cheapest-to-strongest:

1. **Static (free, ship first):** Confirm Pyright `reportUnusedCoroutine` is active and that `bus.on_*` / `scheduler.run_*` / `api` side-effect methods are annotated to return a coroutine. Most users get a static error the moment they write the bare call. Add a docs note about the `if coroutine:` blind spot.
2. **Runtime backstop with attribution (the real feature):** Return a self-reporting awaitable wrapper (Pattern 4) from *only* the fire-and-forget methods. Capture the creation stack eagerly (aiohttp style); in `__del__` when `_awaited` is False, emit a warning that names the offending app by walking to the first frame outside `src/hassette/` (Pattern 5).
3. **Escalation control (Pattern 5's enum):** Route through one IGNORE / LOG / ERROR setting so it ships as a warning and can harden to an error later, mirroring HA's roadmap.

Skip the custom flake8/Ruff plugin (Pattern 3) — Pyright already covers the static case for a typed framework, and a plugin is a maintenance burden for marginal extra coverage. Pattern 6 (sync registration) is off the table given the committed async-await design.

## Sources

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/frame.py — HA frame inspection + ReportBehavior enum (the gold standard for attribution)
- https://github.com/python/cpython/blob/3.10/Lib/asyncio/coroutines.py — CPython debug CoroWrapper (the warn-in-`__del__` pattern)
- https://github.com/aio-libs/aiohttp/blob/master/aiohttp/client_reqrep.py — `_source_traceback` + `__del__` warning template
- https://github.com/PyO3/pyo3/issues/3597 — canonical statement of the self-reporting awaitable pattern

### Blog posts & writeups
- https://superfastpython.com/asyncio-coroutine-was-never-awaited/ — why the GC warning is a weak signal
- https://www.geeksforgeeks.org/python/python-runtimewarning-coroutine-was-never-awaited/ — GC-timing explanation

### Documentation & standards
- https://docs.python.org/3/library/asyncio-dev.html — asyncio debug mode, origin tracking
- https://developers.home-assistant.io/docs/asyncio_blocking_operations/ — HA blocking-call detection
- https://developers.home-assistant.io/docs/asyncio_thread_safety/ — HA detect/report/block thread-unsafe calls
- https://flake8-async.readthedocs.io/en/latest/rules.html — ASYNC105 / ASYNC300
- https://github.com/astral-sh/ruff/issues/9833 — Ruff: generic unawaited detection needs type info
- https://github.com/microsoft/pyright/issues/3563 , https://github.com/microsoft/pyright/issues/9579 — Pyright reportUnusedCoroutine + conditional blind spot
- https://github.com/python/mypy/issues/16921 — mypy unused-coroutine blind spots
- https://peps.python.org/pep-0492/ — PEP 492 (coroutine wrapper origins)
- https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html — AppDaemon sync-first design
- https://trio.readthedocs.io/en/stable/reference-core.html — Trio structured concurrency

*Note: URLs were not live-verified.*
