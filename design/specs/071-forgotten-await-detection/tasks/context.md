# Context: Forgotten-await Detection for User Apps

## Problem & Motivation

Hassette's registration and fire-and-forget methods (`bus.on_*`, `scheduler.run_*`/`schedule`/
`add_job`, `api.call_service`/`fire_event`/`set_state`/`turn_on`/`turn_off`/`toggle_service`) are
`async`. When a user forgets `await`, the coroutine is created and immediately dropped — the listener
never registers, the job never schedules, the service never fires, and **there is no error**. The
only built-in signal is a GC-timed `RuntimeWarning` that fires later, names no app, and is suppressed
by any lingering reference. For a framework whose whole value is "register a handler and it runs,"
this is the highest-impact silent footgun. Pyright's `reportUnusedCoroutine` (already `error` in
`pyrightconfig.json`) catches this *for users who run a type checker* — but many Home Assistant
hobbyists run none. The runtime wrapper is the only protection for them, and the only thing that
catches the `_ = coro()` assignment blind spot that Pyright treats as "used."

## Visual Artifacts

None.

## Key Decisions

1. **Three-layer defense in depth**, cheapest→strongest: (a) Pyright static layer (free, already
   configured — docs recommend it); (b) the runtime self-reporting wrapper (the load-bearing
   feature); (c) an `IGNORE`/`WARN`/`ERROR` escalation enum (default `WARN`).
2. **`RegistrationHandle[T]` subclasses `collections.abc.Coroutine[Any, Any, T]`** and implements the
   full protocol (`send`/`throw`/`close`/`__await__`). Because it genuinely *is* a `Coroutine`,
   `asyncio.iscoroutine(handle)` is `True` (so the sync-facade `run_sync` path needs no change), and
   the `-> Coroutine[Any, Any, T]` annotation on the converted methods is **honest, not a type lie**.
3. **Public methods convert from `async def -> T` to `def -> Coroutine[Any, Any, T]`** returning the
   handle. The annotation stays `Coroutine[...]` (the supertype) deliberately: Pyright's
   `reportUnusedCoroutine` fires only for the `Coroutine` ABC, so narrowing to `RegistrationHandle`
   or `Awaitable` would silently kill the static layer. Empirically verified (2026-06-11) to fire for
   simple, overloaded, and `None`-returning methods.
4. **Two conversion shapes.** Shape A (true primaries): wrap a private `async def` via
   `guard_await(...)`; bus `on_*` already delegate to `_subscribe`/`_on_internal`, while
   `add_job`/`call_service`/`fire_event`/`set_state` do inline async work and must have their body
   extracted to a private `_x` coroutine first. Shape B (delegates): become `def` returning the
   callee's handle directly — no `await`, no second `guard_await` — so delegates emit the **same**
   attributed warning as primaries (no two-tier split). Multi-level chains (`run_in → schedule →
   add_job`; `on_app_running → on_app_state_changed → _subscribe`) collapse to one handle at the
   primary.
5. **Attribution by module name, not filesystem path.** Walk the captured stack to the first frame
   whose `__name__` is not under the `hassette` package. This works from site-packages and on any OS,
   and skips *all* intervening `hassette.*` delegate frames regardless of chain depth. The existing
   `utils/source_capture.py` uses banned path-fragment matching and must be corrected.
6. **`warnings.warn(HassetteForgottenAwaitWarning(RuntimeWarning))`, not the logger.** Integrates
   with `-W error`/`pytest.warns`/the project's `filterwarnings`, and satisfies the "No Log Capture
   Tests" invariant (assert via `pytest.warns`, not `caplog`).
7. **De-asyncing has a codegen blast radius.** The sync-facade codegen gates on
   `ast.AsyncFunctionDef`; it must widen to also match `def -> Coroutine[...]`, regenerate three sync
   facades + the RecordingApi facade, and two parity tests that discover methods via
   `iscoroutinefunction` must switch to OR-semantics. This is mandatory, same-wave work.
8. **`hassette check` AST-scan CLI is a Non-goal** — Pyright is strictly better; documented as a
   future possibility only.

## Constraints & Anti-Patterns

- **Do NOT** annotate the converted methods as `-> Awaitable[T]` or `-> RegistrationHandle[T]` — both
  silently kill Pyright's `reportUnusedCoroutine`. The annotation MUST be `Coroutine[Any, Any, T]`.
- **Do NOT** use `caplog`/log-capture to test the warning — use `pytest.warns(HassetteForgottenAwaitWarning)`.
- **Do NOT** attribute by filesystem path (`"hassette/bus/"`) — use the `__name__` module check.
- **Do NOT** double-wrap delegates in `guard_await` — Shape B returns the callee's handle directly.
- **Do NOT** let `__del__` raise during interpreter shutdown — guard all emission/`close()` paths
  (including the `if warnings is not None` teardown guard).
- **Set `_awaited = True` in ALL of `__await__`, `send`, `throw`, AND `close`** — each is a legitimate
  drive/teardown entry point; omitting any produces a false-positive warning on cancellation,
  threadsafe scheduling, or the sync error path.
- **`throw` uses the single-arg form** `throw(self, exc: BaseException)` (PEP 706; the 3-arg ABC form
  is deprecated in 3.12+).
- **The handle must expose `__name__`** (delegating to the inner coroutine) — `run_sync` logs it.
- Do NOT build the `hassette check` CLI (Non-goal). Do NOT add a deterministic sweep / hard-crash on
  forgotten await (Non-goal — `__del__` can't crash the process).
- Synchronous validation (glob `ValueError`, `ListenerNameRequiredError`, `DuplicateListenerError`)
  must run at call time in the public `def`, before the handle is constructed.

## Design Doc References

- `## Architecture` — the handle, the two conversion shapes (A/B), the enum/config, the codegen +
  parity-test updates, and the source-capture correction. The authoritative implementation guide.
- `## Functional Requirements` (FR#1–12) and `## Acceptance Criteria` (AC#1–10) — what each task must
  satisfy and verify.
- `## Edge Cases` — double native warning, shutdown, cancellation/`close` false positives, validation
  ordering.
- `## Key Constraints` — the `Coroutine` annotation rule, module-name attribution, eager/shallow
  capture, no-log-capture, `__del__` shutdown guard.
- `## Test Strategy` — existing tests to adapt (parity tests, `inspect.iscoroutine` guards), new
  coverage mapped to FR/AC, the Pyright probe + annotation-guard fixtures.
- `## Impact` → `### Changed Files` / `### Behavioral Invariants` — the full file surface and the
  invariants that must keep passing.

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

`ForgottenAwaitBehavior` follows this exactly: `StrEnum`, `auto()` members, a docstring per member.

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

### Public registration method delegating to a private async method (Shape A)

**Source:** `src/hassette/bus/bus.py` (`on` → `_on_internal`)

```python
async def on(self, *, topic: str, handler, ..., name=None) -> Subscription:
    ...
    return await self._on_internal(topic=topic, handler=handler, ..., name=name, duration_config=None)
```

Converts to: `def on(...) -> Coroutine[Any, Any, Subscription]: ...validate...; return
guard_await(self._on_internal(...), owner=self.parent, source_location=src)`.
