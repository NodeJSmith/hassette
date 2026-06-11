---
task_id: "T01"
title: "Add RegistrationHandle, behavior enum, warning, config, attribution"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#4", "FR#6", "FR#7", "FR#8", "FR#12", "AC#1", "AC#4", "AC#5"]
---

## Summary

Build the foundation every later task depends on: the self-reporting `RegistrationHandle[T]`
awaitable (a real `collections.abc.Coroutine` subclass that warns in `__del__` when never awaited),
the `ForgottenAwaitBehavior` enum, the `HassetteForgottenAwaitWarning` category, the per-app config
setting with a global default, and the module-name attribution helper (correcting the existing
path-fragment `source_capture.py`). No public Bus/Scheduler/Api methods are converted in this task —
that comes in T02–T04. This task ships the machinery plus its unit tests.

## Prompt

Implement the runtime-wrapper foundation described in the design doc's `## Architecture`
(subsections "The self-reporting awaitable handle", "Escalation enum and config", "Warning
category", "Source-capture correction") and `## Key Constraints`.

1. **`src/hassette/core/await_guard.py`** (new):
   - `RegistrationHandle[T]` subclassing `collections.abc.Coroutine[Any, Any, T]`. Implement
     `send`, `throw(self, exc: BaseException)` (single-arg form — PEP 706, NOT the 3-arg ABC form),
     `close`, and `__await__`, each delegating to the wrapped inner coroutine `self._coro`.
   - **Set `self._awaited = True` in every one of `__await__`, `send`, `throw`, AND `close`** before
     delegating. All four are legitimate drive/teardown entry points; missing any causes a
     false-positive warning (see `## Edge Cases` → "Driven-but-not-`__await__`ed paths").
   - Expose `__name__` delegating to `self._coro.__name__` (set in `__init__` or as a property) —
     `task_bucket.run_sync` logs `fn.__name__` on error paths.
   - Constructor takes the inner coroutine, the owning app/owner, the **already-resolved**
     `ForgottenAwaitBehavior`, and the **pre-captured** `source_location` (do NOT walk the stack
     inside the handle). The per-app-then-global resolution happens inside `guard_await` (from
     `owner`), NOT at the T02–T04 call sites — their signature is
     `guard_await(coro, *, owner, source_location)` with no behavior argument.
   - `__del__`: if `_awaited` is `False`, resolve the offending app by attribution (below), emit per
     the resolved behavior, then call `self._coro.close()` to suppress CPython's native
     "coroutine was never awaited" double-warning. Guard everything so it never raises during
     interpreter shutdown (include the `if warnings is not None` teardown guard). `IGNORE` →
     suppress; `WARN` → `warnings.warn(HassetteForgottenAwaitWarning(...), stacklevel=…)`; `ERROR` →
     emit in a form `filterwarnings("error", category=HassetteForgottenAwaitWarning)` escalates.
   - `guard_await(coro, *, owner, source_location)` helper that constructs and returns the handle.
2. **`src/hassette/exceptions.py`**: add `HassetteForgottenAwaitWarning(RuntimeWarning)`.
3. **`src/hassette/types/enums.py`**: add `ForgottenAwaitBehavior(StrEnum)` with `IGNORE`, `WARN`,
   `ERROR` members, following the `RestartType` style (auto(), per-member docstring) — see
   `context.md` Convention Examples.
4. **Config** (`src/hassette/config/` — `AppConfig` plus the root Hassette config model): add
   `forgotten_await_behavior` as a per-app setting (`ForgottenAwaitBehavior | None = None`) with a
   global default on the root config; the handle resolves per-app, falling back to global, default
   `WARN`.
5. **`src/hassette/utils/source_capture.py`**: replace the banned path-fragment attribution
   (`INTERNAL_PATH_FRAGMENTS`) with a module-name check —
   `frame.f_globals.get("__name__", "").startswith("hassette.")` — so attribution works from
   site-packages, on any OS, and skips all `hassette.*` frames. Add a `limit` argument to the
   `inspect.stack()` call (a few frames suffice; ~12× cheaper than unbounded).
6. Optionally enable `logging.captureWarnings(True)` in Hassette's logging setup so the warning also
   lands in the app log stream.

Write unit tests (TDD — failing test first, per CLAUDE.md "Bug Investigation Workflow"):
`gc.collect()` + `pytest.warns(HassetteForgottenAwaitWarning)` for the drop case; the four
`_awaited` entry points; `__del__` no-double-native-warning; `__name__`; per-app-over-global config;
attribution from a non-`hassette` module frame. Use `pytest.warns`, NOT `caplog`.

## Focus

- `collections.abc.Coroutine` is in `asyncio.coroutines._COROUTINE_TYPES` for Python 3.11–3.13
  (verified), so a subclass instance satisfies `asyncio.iscoroutine()` — this is the load-bearing
  property the sync path (T05) relies on. The ABC's abstract methods are `send`, `throw`, `close`,
  `__await__`; implement all four or instantiation raises `TypeError: abstract class`.
- Existing precedent: `src/hassette/core/migration_runner.py:85` for `warnings.warn`;
  `src/hassette/types/enums.py` `RestartType` for the enum style; `RestartSpec` for per-app config
  precedent.
- `source_capture.py` today: `INTERNAL_PATH_FRAGMENTS` at line 9, `is_internal_frame` ~line 12,
  `inspect.stack()` at line 83. It is missing `hassette/api/` and is forward-slash-only (Windows
  bug) — the module-name rewrite fixes both. `_on_internal` (bus.py:352) and `schedule`
  (scheduler.py:380) currently *call* `capture_registration_source()`; T02/T03 move those calls.
- Capture must be eager (at the call site, user frame live) — but in THIS task the handle only
  *stores* a passed-in `source_location`; the callers (T02–T04) do the capture. Test attribution by
  constructing a handle with a synthetic `source_location` whose frames include a non-`hassette`
  module.
- **Resolve `ForgottenAwaitBehavior` at construction time, not in `__del__`.** `guard_await` resolves
  per-app-then-global from `owner` and passes the resolved enum value into the handle constructor;
  the handle stores it as a plain value. (Callers in T02–T04 do NOT resolve or pass behavior — they
  call `guard_await(coro, owner=..., source_location=...)`.) `__del__` may run at shutdown when the
  owning app is already torn down — reading config there could fail. Store the resolved behavior
  (and the owner identity string for the message) eagerly.
- Do NOT raise from `__del__`. Wrap emission and `close()` in guards.

## Verify

- [ ] FR#1: dropping an un-awaited `RegistrationHandle` and forcing `gc.collect()` emits a `HassetteForgottenAwaitWarning`.
- [ ] FR#2: the warning message contains the owning app identifier and the captured source file:line.
- [ ] FR#4: a handle driven via any of `__await__`/`send`/`throw`/`close` does NOT warn, and no native `coroutine was never awaited` warning fires for the inner coroutine (inner `close()` called in `__del__`).
- [ ] FR#6: `IGNORE` suppresses, `WARN` emits the warning, `ERROR` emits in a form `filterwarnings("error")` escalates to raise.
- [ ] FR#7: with no explicit config, the resolved behavior is `WARN`.
- [ ] FR#8: attribution walks to the first frame whose `__name__` is not under `hassette.` (test with a synthetic non-`hassette` module frame); `source_capture.py` no longer uses path-fragment matching and bounds `inspect.stack()` with `limit`.
- [ ] FR#12: a handle held alive (stored on an object) does not warn until that object is collected — documented shutdown-timing behavior is observable in a test.
- [ ] AC#1: a test drops an un-awaited handle, `gc.collect()`, asserts `pytest.warns(HassetteForgottenAwaitWarning)` with app id + file:line in the message.
- [ ] AC#4: parametrized test asserts default `WARN`, `IGNORE` suppression, `ERROR`+`filterwarnings("error")` raise, and a per-app override beats the global default.
- [ ] AC#5: a test attributes the warning to the correct app from a module-name frame outside the `hassette` package, with framework frames skipped.
- [ ] `RegistrationHandle` is instantiable (all of `send`/`throw`/`close`/`__await__` implemented) and `asyncio.iscoroutine(handle)` is `True` — the property T05's sync path depends on.
