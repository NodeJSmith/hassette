# Design: Forgotten-await Detection for User Apps

**Date:** 2026-06-11
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-06-10-forgotten-await-detection/research.md (+ HANDOFF.md)
**Reviewed:** challenged 2026-06-11 round 1 (contract-caller, senior-engineer, systems-architect),
12 findings folded in; round 2 re-challenge (contract-caller, senior-engineer) verified the
architecture spine sound and folded in ~11 refinements to the fixes (handle protocol completeness,
codegen surface, delegate consistency).

## Problem

Hassette's registration and fire-and-forget methods are `async`. When a user writes
`self.bus.on_state_change(...)` without `await`, the coroutine is created and immediately
dropped: the listener never registers, the job never schedules, the service never fires —
and **there is no error**. Python's only built-in signal is a GC-timed
`RuntimeWarning: coroutine '...' was never awaited` that fires at a nondeterministic later
moment, names no app, and is suppressed entirely if any reference to the coroutine lingers.

For a framework whose entire value proposition is "register a handler and it runs," this is
the single highest-impact silent failure mode. A user adds a handler, sees nothing happen,
and has no diagnostic pointing at the missing `await`.

We verified empirically (2026-06-11) that Pyright's `reportUnusedCoroutine` — already set to
`error` in `pyrightconfig.json` — catches every bare call to these methods, including the
`if coroutine:` conditional case (via `reportUnnecessaryComparison`), overloaded methods
(`call_service`), and `None`-returning methods (`turn_on`). The static layer is therefore a
complete free win for any user who runs Pyright — its only remaining gap is assignment
(`_ = coro()` / `self.sub = coro()`), which Pyright treats as "used."

The runtime backstop is the load-bearing layer for a **different population: users who run no
type checker on their own app code at all** (common among Home Assistant hobbyists). For them
the static layer does nothing; the wrapper is the only protection. It also closes the one static
gap (assignment) for type-checker users.

## Goals

- A user who forgets `await` on a protected method gets a clear warning that **names the
  offending app and points at the call site**, at runtime, without running any type checker.
- The warning works for both bare calls and the assignment blind spot.
- Awaiting a protected method behaves exactly as today — same return value, same timing
  (`sub.listener.db_id` valid on return).
- Pyright's existing static detection continues to fire on bare calls (the static return type
  stays coroutine-typed), including for overloaded and `None`-returning methods.
- **The sync-facade path (`AppSync`) keeps working** — sync callers still register listeners and
  schedule jobs after the conversion.
- The warning severity is controllable (`IGNORE`/`WARN`/`ERROR`), default `WARN`, per-app with a
  global default.
- Documentation tells users how to enable Pyright (copy-paste config) for the earliest signal.

## Non-Goals

- **`hassette check` AST-scan CLI command.** Deferred to a documented phase-2 possibility.
  Rationale: Pyright is strictly better than an in-house AST scanner (it catches the
  `if coroutine:`, overload, and `None`-return cases, needs no Hassette-maintained method list,
  and is already configured). Documented as a future option; not built now.
- **True hard-fail (process crash) on a forgotten await.** Detection happens in `__del__`, and
  Python swallows exceptions raised from `__del__`. `ERROR` produces a loud, visible traceback
  but cannot crash the process at the drop site. A genuine hard-fail would require a
  non-`__del__` detection point (a deterministic sweep), out of scope — keeping a registry
  reference alive to enable a sweep would suppress the GC `__del__` the design depends on.
- **Immediate detection of the `self.sub = coro()` pattern.** When the un-awaited handle is
  stored on `self`, its scope is the app lifetime, so the warning fires at app *shutdown*, not at
  registration (see Edge Cases + FR#12). The bare-drop case fires promptly; the stored-on-self
  case is a documented weaker guarantee, with Pyright as the earlier signal.
- **Protecting data-returning query methods** (`get_state`, `get_states`, `get_entity`,
  `get_history`). A dropped coroutine there blows up downstream with an `AttributeError` — not
  silent, no special handling.
- **Startup-scan-the-app-object approach.** A dropped coroutine is already gone by the time
  `on_initialize` returns. Rejected during research.

## User Scenarios

### App author: writes a Hassette automation

- **Goal:** register handlers and schedule jobs that actually run.
- **Context:** writing or editing an app module, running Hassette locally or as a daemon.

#### Forgets `await` on a bare registration call

1. **Writes `self.bus.on_state_change("light.kitchen", handler=self.h, name="k")`** (no `await`).
   - Sees: nothing at first — the handler never fires.
   - Then: shortly after the dropped handle is garbage-collected, a
     `HassetteForgottenAwaitWarning` is emitted naming the app and the file:line of the call.
2. **Reads the warning**, adds `await`, reloads — the handler now fires.

#### Forgets `await` but assigns the result

1. **Writes `sub = self.bus.on(topic="x", handler=self.h, name="k")`** but never awaits it.
   - Sees: Pyright does *not* flag assignment; the handler never fires.
   - Then: when `sub` is collected, the warning fires. This is the case only the runtime layer
     catches. If `sub` is `self.sub`, the warning fires at shutdown (FR#12).

#### Uses the sync API (`AppSync`)

1. **Writes `self.bus.sync.on_state_change(...)`** in a sync hook.
   - Sees: the listener registers and the handler fires — the sync facade path is unaffected by
     the conversion.

#### Runs Pyright (recommended)

1. **Enables Pyright per the docs** and writes a bare protected call.
   - Sees: an `error` from `reportUnusedCoroutine` at edit/CI time — the earliest signal.

## Functional Requirements

- **FR#1** A bare call to a protected method whose handle is garbage-collected without ever being
  awaited emits a `HassetteForgottenAwaitWarning`.
- **FR#2** The warning names the owning app (key/instance) and includes the source location
  (file and line) of the call site.
- **FR#3** Awaiting a protected method returns the same value it returns today (`Subscription`,
  `ScheduledJob`, `ServiceResponse`, `dict`, or `None`) with the same registration timing
  (`sub.listener.db_id` valid immediately on return).
- **FR#4** A protected method whose handle is awaited exactly once emits no warning, and emits no
  secondary native `coroutine was never awaited` RuntimeWarning for the inner coroutine.
- **FR#5** Pyright's `reportUnusedCoroutine` continues to flag bare calls to protected methods,
  including overloaded (`call_service`) and `None`-returning (`turn_on`/`turn_off`/`set_state`/
  `toggle_service`) methods.
- **FR#6** A config setting selects warning behavior: `IGNORE` suppresses, `WARN` emits
  `HassetteForgottenAwaitWarning`, `ERROR` emits it in a form `filterwarnings("error")` / `-W error`
  escalates to a raised exception. The setting is resolvable per app, with a global default.
- **FR#7** The default warning behavior is `WARN`.
- **FR#8** App attribution walks the captured creation stack to the first frame whose module does
  not belong to the `hassette` package (a `__name__`-based check, not a filesystem-path match),
  identifying user code whether Hassette runs from a source tree or site-packages, on any OS.
- **FR#9** The protected-method set is the *complete* set of public (non-`_`) registration /
  scheduling / fire-and-forget methods on Bus, Scheduler, and Api — derived by enumeration, not a
  hand-maintained subset, and pinned by a completeness test (AC#6) so a newly-added registration
  method cannot silently lose protection. It covers, at minimum:
  - **Bus** — `on`, `on_state_change`, `on_attribute_change`, `on_call_service`, `add_listener`,
    `on_service_registered`, `on_component_loaded`, `on_hassette_service_status`,
    `on_app_state_changed`, and their delegates `on_homeassistant_restart`/`on_homeassistant_start`/
    `on_homeassistant_stop`, `on_websocket_connected`/`on_websocket_disconnected`,
    `on_app_running`/`on_app_stopping`, `on_hassette_service_failed`/`on_hassette_service_crashed`/
    `on_hassette_service_started`.
  - **Scheduler** — `add_job`, `schedule`, `run_in`, `run_once`, `run_every`, `run_minutely`,
    `run_hourly`, `run_daily`, `run_cron`.
  - **Api** — `call_service`, `fire_event`, `set_state`, `turn_on`, `turn_off`, `toggle_service`.

  Exclusions (`bus.emit` — event delivery failure is observable; data-returning query methods
  `get_state`/`get_states`/`get_entity`/`get_history` — they fail loudly downstream) carry a stated
  rationale and are asserted *out* of the set by the same completeness test.
- **FR#10** A protected method that is a thin delegate to another protected method (e.g.
  `on_homeassistant_restart` → `on_call_service`, `run_in` → `schedule`) is protected against a
  forgotten `await` on the delegate itself, and emits the *same* attributed
  `HassetteForgottenAwaitWarning` as a primary method (not the unattributed native warning).
- **FR#11** The auto-generated sync facades (`bus.sync`, `scheduler.sync`, `api.sync`) continue
  to register listeners / schedule jobs / fire services synchronously after the conversion — a
  protected call through a sync facade has the same effect it has today.
- **FR#12** When the un-awaited handle is reachable for the app's lifetime (stored on `self`),
  the warning fires at app shutdown rather than at registration. (Documented guarantee, weaker
  than the bare-drop case; not a separate mechanism.)
- **FR#13** The generated entity-wrapper methods (every domain entity's fire-and-forget service
  method — `LightEntity.turn_on`, `HumidifierEntity.set_humidity`, etc.) and `BaseEntity`'s
  `turn_on`/`turn_off`/`toggle` are protected the same way: a forgotten `await` on
  `entity.<method>()` emits a `HassetteForgottenAwaitWarning` attributed to the user's call site, and
  awaiting behaves as today. Because these are generated, protection is delivered by the codegen
  template, not per-file edits, and the entity sync facade (`BaseEntitySyncFacade`) continues to
  register synchronously.

## Edge Cases

- **Double native warning.** The wrapped inner coroutine (`_on_internal`, `_add_job`, `_call_service`, …) is a real
  CPython coroutine. If only the handle's `__del__` warned, CPython's own finalizer would *also*
  emit `RuntimeWarning: coroutine '_on_internal' was never awaited`, naming a private method and,
  under `-W error`, firing first and killing the test on the wrong exception. The handle must call
  `self._coro.close()` in `__del__` (guarded) to suppress the native finalizer (FR#4).
- **Lingering reference suppresses the warning.** If the user keeps a reference alive, `__del__`
  never runs. Documented (FR#12 is the common form). Same constraint the stdlib GC warning has.
- **Interpreter shutdown.** `__del__` may run during shutdown when the warnings machinery is
  partially torn down. All emission paths are guarded so they never raise during shutdown.
- **Handle awaited more than once.** Awaiting twice is already a `RuntimeError` in CPython; the
  handle delegates and inherits that. It must not warn for a handle awaited at least once.
- **Driven-but-not-`__await__`ed paths (false-positive risk).** A handle can be reached by the loop
  without `__await__`: `run_coroutine_threadsafe` calls `send` directly; a task cancelled before it
  runs gets `throw(CancelledError)` first; `run_sync`'s in-loop error path calls `close`. Each of
  these is a *legitimate* path, not a forgotten await — so `_awaited` is set in all four entry points
  (Architecture). Without that, the handle warns spuriously on cancellation, threadsafe scheduling,
  or the sync error path.
- **`ERROR` level inside `__del__`.** Under `filterwarnings("error")` the raised exception occurs
  inside `__del__` and is swallowed by Python (printed as "Exception ignored in..."). Traceback is
  visible; the process does not crash. Documented.
- **Propagated registration errors.** Exceptions from the awaited path
  (`ListenerNameRequiredError`, `DuplicateListenerError`, glob `ValueError`s) must propagate
  unchanged when the handle is awaited; the handle is transparent to them.
- **Synchronous validation must precede the handle.** Several methods raise `ValueError` /
  `ListenerNameRequiredError` *before* the awaited work today (bus.py:539-547). After conversion
  these checks must run synchronously at call time, before the handle is constructed, so an
  invalid call raises immediately instead of deferring the error into the awaitable.
- **`iscoroutinefunction` on a protected method changes to `False`.** The method is now plain
  `def`. The awaited *result* still satisfies `asyncio.iscoroutine` (the handle subclasses
  `collections.abc.Coroutine` — see Architecture), so `run_coroutine_threadsafe` and other
  coroutine-object consumers keep working. Two parity tests and the codegen must be updated to
  discover the methods by their `Coroutine[...]` return annotation rather than by
  `iscoroutinefunction` / `ast.AsyncFunctionDef` (Replacement Targets).

## Acceptance Criteria

- **AC#1** (FR#1, FR#2) A test calls a protected method without `await`, drops the handle, forces
  `gc.collect()`, and asserts via `pytest.warns(HassetteForgottenAwaitWarning)` that a warning
  fires whose message contains the app identifier and the call-site file:line.
- **AC#2** (FR#3, FR#4) A test `await`s a protected method, asserts the returned object is the
  expected type, that registration completed (`sub.listener.db_id` is an int), that no
  `HassetteForgottenAwaitWarning` fires, and (under default filters) no native
  `coroutine was never awaited` RuntimeWarning fires for the inner coroutine.
- **AC#3** (FR#5) A Pyright probe fixture confirms a bare protected call is still reported as
  `reportUnusedCoroutine` after the conversion — covering a simple method, an **overloaded**
  method (both `ServiceResponse` and `None` overloads), and a bare **`None`-returning** method.
- **AC#4** (FR#6, FR#7) Tests assert: default emits `WARN`; `IGNORE` suppresses; `ERROR` +
  `filterwarnings("error", category=HassetteForgottenAwaitWarning)` raises; and a per-app override
  takes precedence over the global default.
- **AC#5** (FR#8) A test where the protected call originates from a module *outside* the
  `hassette` package asserts the warning attributes the correct app, with framework frames
  skipped — using the `__name__`-based check (verified not to depend on filesystem path).
- **AC#6** (FR#9, FR#10) Two checks: (a) a parametrized test iterates the canonical
  protected-method list and confirms each method — primaries and two-hop delegates alike — emits
  `HassetteForgottenAwaitWarning` (one assertion, no per-method warning-type split) when its handle
  is dropped un-awaited; (b) a **completeness test** enumerates every public (non-`_`) method on
  Bus/Scheduler/Api, asserts each registration/scheduling/side-effect method is in the canonical
  list (catching a future un-protected addition), and asserts the documented exclusions
  (`emit`, `get_*`) are *not* in it.
- **AC#7** (FR#11) A test calls a protected method through each sync facade
  (`bus.sync`/`scheduler.sync`/`api.sync`) and asserts the listener/job actually registers
  (the handle passes `asyncio.iscoroutine` and `run_sync` drives it to completion).
- **AC#8** (FR#5, annotation guard) A CI fixture asserts each protected method's return annotation
  resolves to `collections.abc.Coroutine` (`get_type_hints(...).__origin__`), failing the build if
  a future edit changes the annotation to `Awaitable`/a concrete type and silently kills the
  static layer.
- **AC#9** (FR#11, regen) After regenerating the sync facades from source, `git diff` shows the
  three `sync.py` files still contain `run_sync`-wrapped registration methods (not bare
  passthrough delegates), and the schema/codegen freshness checks pass.
- **AC#10** (FR#1, RecordingApi) The two `RecordingApi` parity tests still discover all six
  converted api write methods and continue to assert `RecordingApi` parity (they are *not*
  vacuously passing).
- **AC#11** (FR#13) Tests on representative entities — a no-param method (`LightEntity.turn_on`),
  a with-params method (`HumidifierEntity.set_humidity`), and `BaseEntity.toggle` — assert: a forgotten
  `await` emits `HassetteForgottenAwaitWarning` attributed to the caller; awaiting returns/acts as
  today; and the entity sync facade (`entity.sync.turn_on()`) still registers. A regen check
  (mirroring AC#9) confirms regenerated `models/entities/*.py` use `def -> Coroutine[...]` and the
  codegen freshness gate passes.

## Key Constraints

- **The return type annotation must stay `Coroutine[Any, Any, T]`.** This is honest, not a type
  lie: `RegistrationHandle` subclasses `collections.abc.Coroutine`, so the annotation is the
  accurate supertype (Pyright accepts the return with no `# type: ignore`, and `await` yields the
  exact `T` — verified 2026-06-11). It is the *supertype* on purpose: a plain `def` annotated
  `-> Coroutine[Any, Any, T]` still triggers `reportUnusedCoroutine` — for simple, overloaded, and
  `None`-returning methods — but `-> Awaitable[T]` and `-> RegistrationHandle[T]` do **not**.
  Narrowing the annotation to the concrete handle type *feels* more precise but silently kills the
  static layer; the public contract is type-identical to the `async def` it replaces. This is the
  load-bearing typing decision, guarded by AC#8, and each converted signature carries an inline
  comment naming the constraint.
- **The handle must satisfy `asyncio.iscoroutine()`.** `task_bucket.run_sync` passes its argument
  to `asyncio.run_coroutine_threadsafe`, which rejects non-coroutine awaitables. The handle
  subclasses `collections.abc.Coroutine` (implementing `send`/`throw`/`__await__`, inheriting/
  delegating `close`) so `asyncio.iscoroutine(handle)` is `True` and `run_sync` needs no change.
- **Attribution must use module-name checking, not a path match.** In a real install Hassette
  lives in site-packages and the dev-tree path does not exist; on Windows, path separators differ.
  Walk to the first frame whose `f_globals["__name__"]` is not under the `hassette` package. The
  existing `utils/source_capture.py` currently uses banned path-fragment matching (missing
  `hassette/api/`, forward-slash-only) and must be corrected to the module-name check so attribution
  is consistent across telemetry and the warning.
- **Stack capture must be eager, shallow, and not duplicated — and it must *move*, not be reused
  in place.** Today `capture_registration_source()` is called *inside* `_on_internal` (bus.py:352)
  and `schedule` (scheduler.py:380) — i.e. in the async body, which runs *after* the `await`
  boundary, when the user's frame is already gone. The capture must move up into the new plain-`def`
  public method (where the user frame is still on the stack), be removed from the internal coroutine,
  and be threaded down to `guard_await` as `source_location`. "Reuse" is the wrong mental model: a
  single capture relocates to the call site. Bound it with `inspect.stack(limit=…)` /
  `traceback.extract_stack(sys._getframe(n), limit=…)` (a few frames suffice; measured ~12× cheaper
  than the unbounded walk). Add a `limit` to `source_capture.py`'s `inspect.stack()` call.
- **No log-capture tests.** Per the project invariant, assert behavior via `pytest.warns`, not
  `caplog`. Primary reason the mechanism is `warnings.warn`, not the logger.
- **`__del__` must never raise during interpreter shutdown.** Guard all emission and `close()`
  paths.

## Dependencies and Assumptions

- **No new external dependencies.** Uses stdlib `warnings`, `collections.abc.Coroutine`,
  `traceback`/`sys._getframe`, and existing config/enums infrastructure.
- Assumes `pyrightconfig.json` keeps `reportUnusedCoroutine: error` (it does today); AC#8 guards the
  annotation half of that contract.
- Assumes the protected methods' internal implementations remain coroutine-returning
  (`self._subscribe(...)`, `self._add_job(...)`, `self._call_service(...)`) so the handle has a real
  coroutine to delegate to.
- Assumes the sync facades are regenerated from source via the existing codegen
  (`codegen/src/hassette_codegen/sync_facade/`) and that CI's schema/codegen freshness gate covers
  the regenerated files.
- Optional: enabling `logging.captureWarnings(True)` in Hassette's logging setup so the warning also
  surfaces in the app log stream (via the existing `LoggingService`).

## Architecture

### The self-reporting awaitable handle

Introduce `RegistrationHandle[T]` in a new module `src/hassette/core/await_guard.py`, subclassing
`collections.abc.Coroutine[Any, Any, T]`. It:

- Wraps a real coroutine produced by the existing internal method.
- Implements the coroutine protocol: `send`, `throw`, `__await__` (delegating to the inner
  coroutine), and `close` (delegating to `self._coro.close()`). Subclassing
  `collections.abc.Coroutine` makes `asyncio.iscoroutine(handle)` return `True`, so the sync-facade
  `run_sync` path works unchanged (Key Constraint #2).
- **`throw` uses the single-argument form** `def throw(self, exc: BaseException)`, not the ABC's
  three-arg `(typ, val, tb)` signature — the three-arg form is deprecated in Python 3.12+ (PEP 706)
  and fires a `DeprecationWarning` on 3.13.
- **Sets `self._awaited = True` in *every* drive/teardown entry point** — `__await__`, `send`,
  `throw`, *and* `close` — before delegating. All four matter: `send` alone is used by
  `run_coroutine_threadsafe`; `throw` is the *first and only* call when a task is cancelled before
  it runs (rapid reload / startup timeout); `close` is called by `run_sync`'s in-loop error path.
  Omitting any of them produces a **false-positive** `HassetteForgottenAwaitWarning` on a
  legitimate path (verified empirically on 3.13). `close` setting the flag is safe because `__del__`
  checks `if not self._awaited` *before* calling `close`.
- **Exposes `__name__`** (delegating to `self._coro.__name__`). `run_sync`'s error paths log
  `fn.__name__` (`task_bucket.py:241,244`); a bare `collections.abc.Coroutine` subclass lacks it, so
  a registration timeout/error would raise `AttributeError` inside the except handler and mask the
  real error.
- Stores the **pre-captured** `source_location` (passed in from the caller) rather than walking the
  stack itself, avoiding a second `inspect.stack()` on the hot path.
- In `__del__`, if `_awaited` is still `False`: resolve the offending app by walking the captured
  frames to the first non-`hassette` module, emit per the resolved `ForgottenAwaitBehavior`, then
  call `self._coro.close()` to suppress CPython's native double-warning — all guarded (including the
  standard `if warnings is not None` teardown guard) so it never raises during shutdown.

A single helper `guard_await(coro, *, owner, source_location)` centralizes handle construction so
the per-method change is one line and the canonical protected-method list lives at the call sites.

### Converting the protected methods

Every public protected method becomes plain `def -> Coroutine[Any, Any, T]`. There are two
mechanical shapes, applied uniformly across **bus, scheduler, and api**:

**Shape A — true primary (constructs the one handle via `guard_await`).** The handle wraps a private
`async def` that does the registration/side-effect work.

- Methods that *already* delegate to a private async method (bus `on`/`on_state_change`/… →
  `_on_internal`/`_subscribe`) convert directly:

  ```python
  def on_state_change(self, ...) -> Coroutine[Any, Any, Subscription]:
      # Returns a RegistrationHandle, which IS a collections.abc.Coroutine subclass — so this
      # annotation is the honest supertype (no type: ignore needed). It is the Coroutine *supertype*
      # on purpose: Pyright's reportUnusedCoroutine fires only for the Coroutine ABC, so narrowing
      # this to `-> RegistrationHandle` or `-> Awaitable` would silently kill the static layer.
      # AC#8 guards against that. See design/071.
      if immediate and is_glob(entity_id):       # synchronous validation stays at call time
          raise ValueError(...)
      ...
      src = capture_registration_source(limit=…) # eager capture, in the public def (user frame live)
      return guard_await(self._subscribe(...), owner=self.parent, source_location=src)
  ```

- Methods that do their async work **inline** (api `call_service` awaits `ws_send_json` directly;
  `fire_event`, `set_state`; scheduler `add_job`) have **no** private coroutine to wrap yet. Extract
  the body into a private `async def _call_service(...)` first, then the public method becomes the
  one-line `guard_await(self._call_service(...), …)`. This extraction is the only structural change
  beyond the signature flip.

**Shape B — delegate (returns the callee's handle directly, no new `guard_await`).** Delegates do
*synchronous* setup then `return await self.<callee>(...)` — and "synchronous setup" includes
building objects (e.g. `schedule` constructs a `ScheduledJob` before delegating). What makes a method
Shape B is that its *only* `await` is the delegation; it does no inline async work of its own. Each
becomes `def ... -> Coroutine[...]` that does the setup and returns the callee's handle. Delegates:
- api `turn_on` / `turn_off` / `toggle_service` → `call_service`.
- bus `on_homeassistant_restart` / `on_homeassistant_start` / `on_homeassistant_stop`,
  `on_websocket_connected` / `on_websocket_disconnected`, `on_app_running` / `on_app_stopping`,
  `on_hassette_service_failed` / `on_hassette_service_crashed` / `on_hassette_service_started`.
- scheduler `run_in` / `run_once` / `run_every` / `run_minutely` / `run_hourly` / `run_daily` /
  `run_cron` → `schedule`, and `schedule` → `add_job`.

**Multi-level chains are fine.** Some delegates are two-hop: scheduler `run_in → schedule →
add_job`; bus `on_app_running → on_app_state_changed → _subscribe` and `on_hassette_service_failed →
on_hassette_service_status → _subscribe`. Each Shape-B level just returns the downstream handle, so
exactly **one** `guard_await` is constructed — at the true primary (`add_job` for the scheduler,
`on_app_state_changed`/`on_hassette_service_status`/etc. for those bus families). Attribution is
unaffected by chain depth: `capture_registration_source()` at the primary walks past *every*
intervening `hassette.*` frame (the module-name check skips them all) to the user's call site,
whether the user called `run_in`, `schedule`, or `add_job` directly.

```python
def run_in(self, func, delay, ...) -> Coroutine[Any, Any, ScheduledJob]:
    trigger = After(seconds=float(delay))      # synchronous setup, unchanged
    return self.schedule(func, trigger, ...)   # returns the handle threaded up from add_job
```

Returning the callee's handle directly (no `await`, no second `guard_await`) means **delegates emit
the same attributed `HassetteForgottenAwaitWarning` as primaries** — `run_in`/`run_every`/`run_daily`
are among the most-used methods, so a two-tier "primaries get the nice warning, delegates get the
ugly native one" split would undercut the feature. Attribution stays correct: the handle is created
at the true primary, the capture stack is `<primary> → <delegate(s)> → user`, and attribution walks
to the first non-`hassette` frame (the user). Pyright fires `reportUnusedCoroutine` on bare delegate
calls (now `def -> Coroutine[...]`), and the widened codegen path (below) generates their sync
facades. This supersedes the round-1 "keep delegates `async def`" resolution and avoids a two-tier
warning split (delegates and primaries emit the same warning), which is why AC#6 needs only a
single assertion.

### Escalation enum and config

Add `ForgottenAwaitBehavior(StrEnum)` to `src/hassette/types/enums.py` (matching the `RestartType`
`StrEnum` + `auto()` + per-member docstring style): `IGNORE`, `WARN`, `ERROR`. Place the setting on
`AppConfig` (`forgotten_await_behavior: ForgottenAwaitBehavior | None = None`) with a global default
on the root Hassette config; the handle resolves per-app-then-global. Per-app placement is already
precedented (`RestartSpec`) and avoids a future config-schema migration when someone wants `ERROR`
for one app under development and `WARN` for mature ones.

### Warning category

Define `HassetteForgottenAwaitWarning(RuntimeWarning)` in `src/hassette/exceptions.py`.
`RuntimeWarning` base integrates with the existing `filterwarnings` config and `-W error`.

### Codegen and parity-test updates (the de-asyncing blast radius)

De-asyncing the public methods trips several `async`-detecting mechanisms. All must change in the
same wave:

1. **Sync-facade codegen** (`codegen/src/hassette_codegen/sync_facade/ast_utils.py`,
   `generic.py`). `is_wrappable` is a `TypeGuard[ast.AsyncFunctionDef]` gating on
   `isinstance(node, ast.AsyncFunctionDef)` (ast_utils.py:169-180). After conversion the protected
   methods become plain `def` and fall through to `is_delegatable`, generating bare passthrough
   delegates with no `run_sync` — silently dropping every sync registration. Fix: widen
   `is_wrappable` to also match a plain `def` whose return annotation is a `Coroutine[...]` subscript
   (the AST node is `ast.Subscript` with `.value.id == "Coroutine"`, reliably detectable). Companion
   type changes the design must include: `is_wrappable`'s return becomes
   `TypeGuard[ast.FunctionDef | ast.AsyncFunctionDef]` (ast_utils.py:169) and `gen_wrapper`'s param
   becomes `ast.FunctionDef | ast.AsyncFunctionDef` (generic.py:209) — both fields are common to the
   two node types, so only the annotations change. Then regenerate `bus/sync.py`, `scheduler/sync.py`,
   `api/sync.py`.
2. **RecordingApi codegen** (`recording.py:134-137,147-150`) — confirmed, **not conditional**: it
   hard-filters on `isinstance(node, ast.AsyncFunctionDef)`, so the six converted api write methods
   would vanish from `api_methods` and the generated `sync_facade.py` (committed, CI-freshness-gated)
   would silently lose them — a sync `RecordingApi` call would `AttributeError`. Apply the same
   `def -> Coroutine[...]` widening. Cascading annotation-only fixes (Pyright runs on `codegen/` in
   CI): `recording_transform.py:97,171,194` and `recording_imports.py:196` take
   `ast.AsyncFunctionDef` params that must widen to `ast.FunctionDef | ast.AsyncFunctionDef`.
3. **RecordingApi parity tests** (`tests/unit/test_recording_api_protocol_parity.py:28`,
   `test_recording_api_write_parity.py:73`). Both compute `public_async_methods` via
   `inspect.iscoroutinefunction`; the six converted api write methods would vanish and the tests
   would pass vacuously. Fix with **OR semantics** —
   `iscoroutinefunction(m) or (get_type_hints(m).get("return") and get_type_hints(m)["return"].__origin__ is collections.abc.Coroutine)`
   — which is robust across the mixed-async migration state (a pure annotation-only replacement would
   instead miss every still-`async def` method). Verified: no `from __future__ import annotations` in
   `api.py`/`bus.py`/`scheduler.py`, so `get_type_hints` resolves the annotations at runtime. Ships
   in the same commit as the conversion.
4. **Overloaded `call_service`** — Pyright resolves overloaded calls through the `@overload` *stubs*,
   not the implementation. Both stubs (`api.py:442-460`, returning `ServiceResponse` and `None`) must
   also carry `-> Coroutine[Any, Any, ...]`, or `reportUnusedCoroutine` won't fire on bare overloaded
   calls (FR#5/AC#3). For every converted method, all `@overload` stubs and the implementation carry
   the `Coroutine[...]` return annotation.
5. **Imports** — `api.py`, `bus.py`, `scheduler.py` must each add `Coroutine` to their
   `collections.abc` import (none import it today); omission is a hard `ImportError`, not a type
   error.

### Entity-wrapper codegen (the highest-traffic user surface)

The domain entity classes (`models/entities/*.py` — `LightEntity`, `HumidifierEntity`, …) are
**generated** by `codegen/.../pipeline.py` from `templates/entity_wrapper.py.j2`, which emits
`async def {{ method }}(...) -> None: await self.api.call_service(...)` for each domain service. Every
one is a Shape B delegate to `api.call_service`. Protection is delivered by changing the **template**,
not 31 files: emit `def {{ method }}(...) -> Coroutine[Any, Any, None]: return self.api.call_service(...)`
(both the with-params and no-params branches), and add `from collections.abc import Coroutine` (and
`Any`) to the template's imports. Then regenerate. The handle is created at `call_service` (Shape A
primary); attribution walks past the `hassette.models.entities.*` frame to the user.

`BaseEntity.turn_on`/`turn_off`/`toggle` (`models/entities/base.py`) are *hand-written* delegates to
`api.turn_on`/`turn_off`/`toggle_service` — convert them to Shape B `def -> Coroutine[..., None]` by
hand. `BaseEntitySyncFacade` (the small runtime sync facade with `turn_on`/`turn_off`/`toggle`) keeps
working unchanged: it drives the entity method through `run_sync`, and the entity method now returns a
`RegistrationHandle` which `asyncio.iscoroutine` accepts — verify with a test. Domain-specific entity
methods (`set_humidity`, etc.) have no per-entity sync facade today; this design does not add one.

### Source-capture correction

`src/hassette/utils/source_capture.py` uses `INTERNAL_PATH_FRAGMENTS = ("hassette/bus/",
"hassette/scheduler/", "hassette/core/")` — banned by Key Constraint #3, missing `hassette/api/`,
and broken on Windows path separators. Correct `is_internal_frame` to
`frame.f_globals.get("__name__", "").startswith("hassette.")` and add a `limit` to the
`inspect.stack()` call. The handle's attribution reuses this corrected logic.

### Why the wrapper rather than alternatives

The wrapper is the only mechanism that (a) runs without a type checker, (b) catches the assignment
blind spot, and (c) attributes the exact call site. It is CPython's own `CoroWrapper` pattern
(PEP 492) and structurally identical to aiohttp's `ClientResponse.__del__` — a blessed pattern.

## Replacement Targets

No functionality is removed, but several detection mechanisms change shape and must be migrated in
the same wave (not left split between old and new):

- **`is_wrappable` in `sync_facade/ast_utils.py`** — replace the `ast.AsyncFunctionDef`-only gate
  with one that also accepts `def -> Coroutine[...]`. The old gate must not survive alongside the
  new methods, or the generated sync facades silently break.
- **`public_async_methods` discovery in both RecordingApi parity tests** — replace
  `iscoroutinefunction`-only discovery with annotation-aware discovery. The old discovery must be
  replaced, not supplemented, or the tests pass vacuously.
- **`INTERNAL_PATH_FRAGMENTS` path-fragment attribution in `source_capture.py`** — replace with the
  module-name check. The path-fragment approach is being intentionally retired, not kept.

The internal implementation methods (`_subscribe`, `_on_internal`, `_add_job`, `_call_service`, …)
stay `async def` — `_add_job` and `_call_service` are *newly extracted* from the inline-async bodies
of `add_job`/`call_service`/`fire_event`/`set_state` (Shape A), while `_subscribe`/`_on_internal`
already exist. The public methods wrap these coroutines instead of awaiting them inline. No parallel old/new public paths are left behind.

## Convention Examples

### `StrEnum` with `auto()` and per-member docstrings

**Source:** `src/hassette/types/enums.py`

```python
class RestartType(StrEnum):
    """Enumeration for service restart strategies."""

    PERMANENT = auto()
    """The service is permanent and should always be restarted on failure."""

    TRANSIENT = auto()
    """The service is transient — restarts on failure but supports cooldown cycling."""
```

`ForgottenAwaitBehavior` matches this exactly.

### `warnings.warn` with explicit category and stacklevel

**Source:** `src/hassette/core/migration_runner.py:85`

```python
warnings.warn(
    f"auto_vacuum could not be set to INCREMENTAL (got {applied}); ...",
    RuntimeWarning,
    stacklevel=2,
)
```

The new warning uses `HassetteForgottenAwaitWarning` and embeds the captured creation site rather
than relying on `stacklevel` (the real frame is gone by `__del__`).

### Sync-facade codegen gate (the mechanism that must change)

**Source:** `codegen/src/hassette_codegen/sync_facade/ast_utils.py:169-180`

```python
def is_wrappable(node: ast.stmt) -> TypeGuard[ast.AsyncFunctionDef]:
    return (
        isinstance(node, ast.AsyncFunctionDef)
        and not node.name.startswith("_")
        ...
    )
```

This is the exact gate that silently breaks after de-asyncing — the design widens it to also accept
plain `def` methods returning `Coroutine[...]`.

## Alternatives Considered

- **Do nothing / rely on the GC `RuntimeWarning`.** Rejected: late, unattributed, suppressed by any
  lingering reference. The baseline this improves on.
- **Logger instead of `warnings.warn`.** Rejected as primary mechanism: forces log-capture tests
  (violating the invariant) and does not integrate with `-W error`/`pytest.warns`. Still reachable
  via `logging.captureWarnings(True)`.
- **Ship static-docs only; defer/drop the wrapper.** Rejected by the team: with no current users
  there is no value in shipping the free static-docs win separately, and the wrapper is the only
  protection for the no-type-checker population.
- **`hassette check` AST-scan CLI.** Rejected for now (Non-goal): Pyright is strictly better and
  needs no maintained list.
- **Return type `-> Awaitable[T]` or a custom handle type.** Rejected: empirically destroys
  `reportUnusedCoroutine` (only `-> Coroutine[...]` preserves it).
- **Make the handle a true coroutine via `@types.coroutine` generator delegation (Finding 3 opt a)
  / change `run_sync` to accept any awaitable (opt b).** Rejected in favor of subclassing
  `collections.abc.Coroutine`: it satisfies `asyncio.iscoroutine` with no `run_sync` change and
  still gives us a class with `__del__`.
- **Double-wrap thin delegates in `guard_await`.** Rejected: creates two GC handles per call and a
  spurious warning. Instead, delegates become `def` returning the callee's handle directly
  (Architecture, Shape B) — one handle, consistent attributed warning.
- **Sync registration (eliminate the footgun by design, AppDaemon-style).** Off the table —
  contradicts Hassette's committed async-await design.

## Test Strategy

### Existing Tests to Adapt

- **`tests/unit/test_recording_api_protocol_parity.py:28` and `test_recording_api_write_parity.py:73`** —
  `public_async_methods` discovers via `inspect.iscoroutinefunction`; widen to **OR semantics**
  (`iscoroutinefunction(m)` OR return-annotation origin is `collections.abc.Coroutine`), or the six
  converted api write methods vanish and the tests pass vacuously (AC#10). Ships in the conversion
  commit.
- **`tests/integration/test_registration.py:79` and `tests/unit/test_scheduler_resource.py:164`** —
  mock-cleanup helpers guard with `if inspect.iscoroutine(coro): coro.close()`. `inspect.iscoroutine`
  returns **`False`** for a `RegistrationHandle` (it checks the `CO_COROUTINE` code-object flag,
  which a `collections.abc.Coroutine` subclass lacks; only `asyncio.iscoroutine` returns `True`).
  After conversion these guards silently stop closing handles, leaking warning noise into the suite.
  Switch them to `asyncio.iscoroutine` (or `isinstance(coro, collections.abc.Coroutine)`).
- **Bus / scheduler / api registration tests** that already `await` the protected methods: should
  pass unchanged. Survey `tests/` for any remaining `inspect.iscoroutine`/`iscoroutinefunction`
  use on the protected methods and update it.
- **`HassetteHarness`-based integration tests** that register listeners: confirm awaiting the
  handle still yields a registered, routable listener (`db_id` set).
- **Sync-facade tests** (if any) covering `bus.sync`/`scheduler.sync`/`api.sync`: extend to assert
  registration actually happens post-conversion (AC#7).

### New Test Coverage

- **FR#1/FR#2 (AC#1):** drop an un-awaited handle, `gc.collect()`, assert `pytest.warns` with app
  id + file:line.
- **FR#3/FR#4 (AC#2):** await; assert return type + `db_id` + no Hassette warning + no native
  double-warning.
- **FR#5 (AC#3):** Pyright probe fixture — simple, overloaded, and `None`-returning bare calls all
  flagged.
- **FR#5/annotation guard (AC#8):** fixture asserting each protected method's return annotation
  origin is `collections.abc.Coroutine`.
- **FR#6/FR#7 (AC#4):** `IGNORE`/`WARN`/`ERROR` + per-app-over-global precedence.
- **FR#8 (AC#5):** attribution from a non-`hassette` module frame.
- **FR#9/FR#10 (AC#6):** parametrized over the canonical protected-method list, including thin
  delegates.
- **FR#11 (AC#7):** call a protected method through each sync facade; assert the listener/job
  registers (exercises `asyncio.iscoroutine(handle)` + `run_sync`).
- **FR#11/regen (AC#9):** regenerate sync facades; assert `sync.py` files keep `run_sync`-wrapped
  registration methods and codegen freshness passes.
- **FR#13 (AC#11):** representative entity tests — `LightEntity.turn_on` (no params),
  `HumidifierEntity.set_humidity` (with params), `BaseEntity.toggle`: forgotten `await` warns
  (attributed to caller), awaited acts as today, `entity.sync.turn_on()` registers; regen check that
  `models/entities/*.py` use `def -> Coroutine[...]`.
- **Edge — shutdown / double-await / propagated errors / sync-validation-precedes-handle:** unit
  tests on the handle and converted methods in isolation.

All async/GC timing follows the project TDD discipline: write the failing `pytest.warns` test first
(RED), then implement (GREEN).

### Tests to Remove

No tests to remove.

## Documentation Updates

- **`docs/pages/core-concepts/bus/` (and `scheduler/`, `api/`, and the states/entities pages):**
  short admonition that these methods — including entity service methods like `entity.turn_on()` /
  `entity.set_humidity(...)` — must be awaited, and that a forgotten `await` now produces a
  `HassetteForgottenAwaitWarning` naming the app. Follow `voice-guide.md` (system-as-subject).
- **New "forgotten await" troubleshooting entry** (extend `docs/pages/troubleshooting.md` or add a
  short page): symptom ("my handler never fires"), cause (missing `await`), fix, the warning's
  meaning, the assignment blind spot, the lingering-reference / `self.sub = coro()` shutdown-timing
  limitation (FR#12), and the `ERROR`-cannot-crash limitation.
- **Pyright recommendation** (troubleshooting and/or a getting-started note): enable Pyright for the
  earliest signal, with a **copy-paste `pyrightconfig.json` snippet** enabling
  `reportUnusedCoroutine` (and noting `basic` mode already turns it on). State that Pyright catches
  bare/`if`/overload/`None` cases and that the runtime warning covers the `_ = coro()` gap.
- **Configuration docs** (`docs/pages/configuration/`): document `forgotten_await_behavior`
  (`IGNORE`/`WARN`/`ERROR`, default `WARN`, per-app with global default).
- **`AppSync` / sync docs:** note the sync facades carry the same await-safety (calls register
  synchronously; no forgotten-await footgun on the sync path).
- **API reference:** ensure `HassetteForgottenAwaitWarning` and `ForgottenAwaitBehavior` are
  exported and docstringed if in `PUBLIC_MODULES` (`tools/gen_ref_pages.py`).
- **CHANGELOG:** handled by release-please via `feat:`; no manual edit.

This touches user-facing API and config → `design-completeness.md` docs rules apply. No listener
await-state is persisted to the DB, so no monitoring-UI/frontend change is required.

## Impact

### Changed Files

- `src/hassette/bus/bus.py` — convert **all** public registration methods to `def -> Coroutine[...]`:
  primaries (`on`/`on_state_change`/`on_attribute_change`/`on_call_service`/`add_listener` and the
  other `_subscribe`-backed `on_*` methods) as Shape A; delegates (`on_homeassistant_*`,
  `on_websocket_*`, `on_app_*`, `on_hassette_service_*`, etc.) as Shape B returning the callee's
  handle. (Most-used registration surface.)
- `src/hassette/scheduler/scheduler.py` — convert **all** public scheduling methods: `add_job`
  (Shape A primary, owns the `guard_await`), `schedule` and every `run_*` as Shape B returning the
  downstream handle.
- `src/hassette/api/api.py` — convert `call_service` (overloaded, Shape A — extract inline async body
  to a private coroutine), `fire_event`, `set_state` (Shape A); `turn_on`, `turn_off`,
  `toggle_service` (Shape B → `call_service`).
- `src/hassette/core/await_guard.py` (new) — `RegistrationHandle` (Coroutine subclass) + `guard_await`.
- `src/hassette/utils/source_capture.py` — module-name attribution; bounded `inspect.stack()`.
- `src/hassette/types/enums.py` — add `ForgottenAwaitBehavior`.
- `src/hassette/exceptions.py` — add `HassetteForgottenAwaitWarning(RuntimeWarning)`.
- `src/hassette/config/` (`config.py`/`models.py` / `AppConfig`) — add `forgotten_await_behavior`
  (per-app + global default).
- `codegen/src/hassette_codegen/sync_facade/ast_utils.py` (`is_wrappable` widen + `TypeGuard`),
  `generic.py` (`gen_wrapper` param type), `recording.py` (same `def -> Coroutine[...]` widen —
  confirmed required, not conditional), `recording_transform.py` and `recording_imports.py`
  (`ast.AsyncFunctionDef` → `ast.FunctionDef | ast.AsyncFunctionDef` param annotations).
- `src/hassette/bus/sync.py`, `src/hassette/scheduler/sync.py`, `src/hassette/api/sync.py`,
  and the generated `RecordingApi` sync facade — regenerated output.
- `codegen/src/hassette_codegen/templates/entity_wrapper.py.j2` (+ `generators/entities.py` if it
  injects imports/annotations) — emit `def -> Coroutine[Any, Any, None]: return self.api.call_service(...)`
  instead of `async def ... await ...`; add the `Coroutine`/`Any` imports.
- `src/hassette/models/entities/base.py` — convert `BaseEntity.turn_on`/`turn_off`/`toggle` to Shape B
  `def -> Coroutine[..., None]`; verify `BaseEntitySyncFacade` still registers via `run_sync`.
- `src/hassette/models/entities/*.py` (31 generated files) — regenerated output.
- `src/hassette/task_bucket/task_bucket.py` — **no change**, but a verified invariant: `run_sync`
  relies on `asyncio.iscoroutine(handle)` (satisfied) and `fn.__name__` (the handle exposes it).
- Hassette logging setup — optional `logging.captureWarnings(True)`.
- `tests/unit/test_recording_api_protocol_parity.py`, `tests/unit/test_recording_api_write_parity.py`
  — OR-semantics method discovery.
- `tests/integration/test_registration.py`, `tests/unit/test_scheduler_resource.py` — switch
  cleanup guards from `inspect.iscoroutine` to `asyncio.iscoroutine`.
- `tests/` — new test module(s): handle behavior (including the `send`/`throw`/`close` no-false-
  positive paths), parametrized protected set, sync-facade registration, Pyright probe +
  annotation-guard fixtures.
- `docs/pages/...` — per Documentation Updates.

### Behavioral Invariants

- `await <protected method>(...)` returns the same value with the same timing as today;
  `sub.listener.db_id` is a valid int on return.
- Synchronous validation errors still raise at call time / on await, unchanged.
- Internal awaiters (`state_proxy.py`, `app_handler.py`, `service_watcher.py`) keep working.
- **Sync facades keep registering** — `AppSync` users see no behavior change (FR#11, AC#7, AC#9).
- The awaited result remains `asyncio.iscoroutine`-true (handle subclasses
  `collections.abc.Coroutine`); only the unbound method object stops being
  `iscoroutinefunction`-true, and the two consumers that depended on that (parity tests, codegen)
  are migrated in the same wave.
- `RecordingApi` parity remains genuinely enforced (AC#10), not vacuously passing.

### Blast Radius

- Every user app and every internal caller of the protected methods exercises the handle on each
  registration/scheduling/service call. The handle is on the registration hot path (not event
  dispatch); per-call cost is one object construction reusing the already-captured source location —
  no new stack walk for the bus path.
- The codegen change ripples to the three generated `sync.py` facades; CI's codegen-freshness gate
  covers them (AC#9).
- Public method type signatures change from `async def -> T` to `def -> Coroutine[..., T]`:
  source-compatible for all `await`ing callers and for Pyright's unused-coroutine check; observable
  only to code that introspects the method as a coroutine function (parity tests + codegen, both
  migrated).

## Open Questions

None.
