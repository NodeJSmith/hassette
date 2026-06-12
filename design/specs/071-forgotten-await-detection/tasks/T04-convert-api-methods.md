---
task_id: "T04"
title: "Convert api fire-and-forget methods to def -> Coroutine"
status: "done"
depends_on: ["T01"]
implements: ["FR#3", "FR#5", "FR#9", "FR#10", "AC#2", "AC#3"]
---

## Summary

Convert the Api fire-and-forget methods from `async def -> T` to `def -> Coroutine[Any, Any, T]`
returning a `RegistrationHandle`. `call_service` (overloaded), `fire_event`, and `set_state` are
Shape A primaries whose inline async bodies are extracted to private coroutines; `turn_on`,
`turn_off`, `toggle_service` are Shape B delegates to `call_service`. The overloaded `call_service`
stubs must also carry `-> Coroutine[...]` so Pyright keeps flagging bare overloaded calls.

## Prompt

Per the design doc's `## Architecture` → "Converting the protected methods", convert the methods in
`src/hassette/api/api.py`.

**Shape A primaries (inline async bodies → extract a private coroutine):**
- `call_service` — does `await self.ws_send_and_wait(...)` / `ws_send_json(...)` inline (api.py:462).
  Extract the body to `async def _call_service(...) -> ServiceResponse | None`, then make the public
  `call_service` a `def` returning `guard_await(self._call_service(...), ...)`. **Both `@overload`
  stubs** (api.py:442-460, returning `ServiceResponse` and `None`) must change their return
  annotations to `-> Coroutine[Any, Any, ServiceResponse]` and `-> Coroutine[Any, Any, None]` — Pyright
  resolves overloaded calls through the stubs, so without this `reportUnusedCoroutine` won't fire on
  bare `call_service` calls (FR#5/AC#3).
- `fire_event` (api.py:420, `-> dict[str, Any]`) and `set_state` — same pattern: extract inline async
  body to a private `_fire_event`/`_set_state`, public method returns `guard_await(...)`.

**Shape B delegates → `call_service`:** `turn_on` (api.py:504), `turn_off` (~520), `toggle_service`
(~535). Each does synchronous setup (`entity_id = str(entity_id)`, debug log) then returns
`self.call_service(...)`'s handle directly:
```python
def turn_on(self, entity_id, domain="homeassistant", **data) -> Coroutine[Any, Any, None]:
    entity_id = str(entity_id)
    self.logger.debug("Turning on entity %s", entity_id)
    return self.call_service(domain=domain, service="turn_on", target={"entity_id": entity_id}, **data)
```

Add `Coroutine` to the imports in `api.py` (it currently has no `collections.abc` import). Capture the
source location in the public `def` of each Shape A primary and pass it to `guard_await`.

Update/add unit tests: awaiting each converted method returns the same value (dict / ServiceResponse /
None); a forgotten `await` on a primary AND a delegate emits `HassetteForgottenAwaitWarning`; awaited
calls emit no warning. Run the affected api test files locally and confirm they pass.

NOTE: do NOT touch data-returning query methods (`get_state`, `get_states`, `get_entity`,
`get_history`) — they are out of scope (fail loudly downstream).

## Focus

- `call_service` overloads at api.py:442-461 (two `@overload async def` stubs + the impl at 462).
  After conversion all three carry `-> Coroutine[...]`. The impl becomes a `def` that wraps
  `self._call_service(...)`.
- `turn_on` returns `None`, `fire_event` returns `dict`, `call_service` returns `ServiceResponse | None`
  — the handle is generic over the real return type; `await` yields it unchanged.
- This task interacts with T05: the six converted api methods (`call_service`, `fire_event`,
  `set_state`, `turn_on`, `turn_off`, `toggle_service`) are exactly the ones the RecordingApi parity
  tests and the RecordingApi codegen discover via `iscoroutinefunction`/`AsyncFunctionDef`. Converting
  them here is what *causes* the T05 breakage — T05 fixes the codegen/tests. Do not attempt the
  codegen/parity fixes here.
- `RecordingApi` (the recording subclass) overrides these methods; its implementations stay
  `async def` and are checked by the parity tests (fixed in T05). Do not change `RecordingApi` here.
- Do NOT change the `Coroutine[...]` annotation to the concrete return type or `Awaitable`.

## Verify

- [ ] FR#3: `await self.api.call_service(...)` returns `ServiceResponse | None` as today; `fire_event` returns its dict; `turn_on` returns `None` — all unchanged.
- [ ] FR#5: bare calls to `call_service` (both overloads — `ServiceResponse` and `None`), `fire_event`, `set_state`, and `turn_on` are each flagged by Pyright `reportUnusedCoroutine` (run `uv run pyright` on probe calls).
- [ ] FR#9: `call_service`, `fire_event`, `set_state`, `turn_on`, `turn_off`, `toggle_service` are all converted to `def -> Coroutine[...]`; no protected api method remains `async def`; data-returning query methods are untouched.
- [ ] FR#10: a forgotten `await` on `turn_on`/`turn_off`/`toggle_service` (delegates) emits the same `HassetteForgottenAwaitWarning` as `call_service`.
- [ ] AC#2: a test awaits each converted api method, asserts the returned value type, and asserts no `HassetteForgottenAwaitWarning` (nor native inner-coroutine warning) fires.
- [ ] AC#3: the Pyright probe (extended in T06) covers a bare overloaded `call_service` (both overloads) and a bare `None`-returning `turn_on`, and both are flagged.
