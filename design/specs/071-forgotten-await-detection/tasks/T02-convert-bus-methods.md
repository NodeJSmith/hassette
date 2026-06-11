---
task_id: "T02"
title: "Convert bus registration methods to def -> Coroutine"
status: "planned"
depends_on: ["T01"]
implements: ["FR#3", "FR#5", "FR#9", "FR#10", "AC#2"]
---

## Summary

Convert every public Bus registration method from `async def -> T` to `def -> Coroutine[Any, Any, T]`
returning a `RegistrationHandle` (from T01). Shape A primaries wrap their existing private async
method via `guard_await`; Shape B delegates return the callee's handle directly. Awaiting any of them
behaves exactly as today (`sub.listener.db_id` valid on return). This preserves Pyright's
`reportUnusedCoroutine` and gives every bus method — primary or delegate — the same attributed
runtime warning when a user forgets `await`.

## Prompt

Per the design doc's `## Architecture` → "Converting the protected methods" (Shape A and Shape B),
convert the Bus methods in `src/hassette/bus/bus.py`.

**Shape A primaries** (already delegate to a private `async def` — `_on_internal`/`_subscribe`):
`on`, `on_state_change`, `on_attribute_change`, `on_call_service`,
`on_service_registered`, `on_component_loaded`, `on_hassette_service_status`, `on_app_state_changed`.
Each becomes:
```python
def on_state_change(self, ...) -> Coroutine[Any, Any, Subscription]:
    # Return type is the Coroutine *supertype* (RegistrationHandle IS a collections.abc.Coroutine).
    # Honest annotation, no type: ignore. Narrowing to RegistrationHandle/Awaitable would silence
    # Pyright's reportUnusedCoroutine. AC#8 guards this. See design/071.
    if immediate and is_glob(entity_id):        # synchronous validation STAYS at call time
        raise ValueError(...)
    ...
    # MOVE the capture up here (user frame is live). It returns a 2-tuple — UNPACK it.
    source_location, registration_source = capture_registration_source(limit=...)
    return guard_await(
        self._subscribe(..., source_location=source_location, registration_source=registration_source),
        owner=self.parent,
        source_location=source_location,
    )
```
Move the `capture_registration_source()` call out of `_on_internal` (currently bus.py:352) into the
public methods. The call returns a 2-tuple `(source_location, registration_source)` — unpack it. The
capture has **two separate destinations**: (1) `_on_internal`/`_subscribe` stay `async def` and gain
`source_location`/`registration_source` parameters that populate `ListenerIdentity` on the DB record
(today `_on_internal` captures this itself at bus.py:352-369 — dropping the threading would silently
empty every listener's stored source location); (2) `source_location` is also passed to `guard_await`
for warning attribution.

**Shape A with body extraction — `add_listener` (bus.py:181):** unlike the methods above, it does NOT
delegate to a private async method — it awaits `self.bus_service.add_listener(listener)` inline.
Extract: the `ListenerNameRequiredError` name check stays synchronous in the public `def`;
`register_and_check_collision(listener)` (a registry mutation) and the `await
self.bus_service.add_listener(listener)` move into a new private `async def _add_listener` — a
never-awaited call must not pollute the duplicate-name registry, matching the `on()` path where the
collision check lives in `_on_internal`. The public `def add_listener` then returns
`guard_await(self._add_listener(listener), ...)`.

**Shape B delegates** (synchronous setup then `return await self.<callee>(...)`):
`on_homeassistant_restart`/`on_homeassistant_start`/`on_homeassistant_stop`,
`on_websocket_connected`/`on_websocket_disconnected`, `on_app_running`/`on_app_stopping`,
`on_hassette_service_failed`/`on_hassette_service_crashed`/`on_hassette_service_started`. Each becomes
`def ... -> Coroutine[...]: ...sync setup...; return self.<callee>(...)` — returning the callee's
handle directly (no `await`, no second `guard_await`). Some delegates have no setup at all
(`on_websocket_connected`/`on_websocket_disconnected` are pure `return self.on(...)` delegations) —
that is still Shape B. Two-hop chains
(`on_app_running → on_app_state_changed → _subscribe`) just thread the handle up; the single
`guard_await` lives at the primary.

Add `Coroutine` to the `collections.abc` import in `bus.py`. Keep all synchronous validation
(`ListenerNameRequiredError`, `DuplicateListenerError`, glob `ValueError`s) at call time in the
public `def`, before `guard_await`.

Update/add unit tests: awaiting each method still registers (db_id set, routable); a forgotten
`await` on a primary AND on a delegate emits `HassetteForgottenAwaitWarning`; awaited calls emit no
warning. Run the affected bus test files locally and confirm they pass (CLAUDE.md: run fixed tests
before committing).

## Focus

- Method line anchors (verify by symbol, lines drift): primaries `on` (~255), `on_state_change`
  (~493), `on_attribute_change` (~570), `on_call_service` (~655); delegates `on_homeassistant_*`
  (~803/827/851), `on_app_*` and `on_hassette_service_*` further down; `add_listener` (~181).
- `_on_internal` and `_subscribe` are the private async primitives the bus primaries already call —
  for those, Shape A is a near-mechanical flip plus moving the source capture. The ONE bus method
  needing body extraction is `add_listener` (see the prompt) — it awaits
  `bus_service.add_listener` inline with no private delegate.
- Internal awaiters that must keep working unchanged: `src/hassette/core/state_proxy.py`,
  `src/hassette/core/app_handler.py`, `src/hassette/core/service_watcher.py` all `await self.bus.on(...)`
  / `on_websocket_*` / `on_state_change`. Awaiting the handle is behaviorally identical — verify these
  paths still pass (`AC#7` of the design's invariants).
- The handle is a `collections.abc.Coroutine`, so `await sub` works and `inspect.isawaitable(sub)` is
  true; `inspect.iscoroutinefunction(bus.on_state_change)` becomes `False` (the method is now `def`) —
  that's expected and handled in T05 (codegen/parity tests). Do not "fix" it here.
- The `Coroutine[...]` annotation is load-bearing; do NOT change it to `Subscription` or `Awaitable`.

## Verify

- [ ] FR#3: `await self.bus.on_state_change(...)` (and every converted method) returns the same type as today and `sub.listener.db_id` is a valid int on return.
- [ ] FR#5: a bare (un-awaited) call to a converted bus method is flagged by Pyright's `reportUnusedCoroutine` (run `uv run pyright` on a probe call).
- [ ] FR#9: every public bus registration method listed in the design's FR#9 (primaries + delegates) is converted to `def -> Coroutine[...]` returning a handle; `grep -n "async def" src/hassette/bus/bus.py | grep -v "def _"` shows no public registration method (including `add_listener`) still `async def` (the T06 completeness test is the authoritative gate; this spot-check is illustrative).
- [ ] Listeners registered via converted methods still get a non-empty `ListenerIdentity.source_location` / `registration_source` on the DB record (the `src` threading into `_subscribe`/`_on_internal` works).
- [ ] FR#10: a forgotten `await` on a bus *delegate* (e.g. `on_homeassistant_restart`, `on_app_running`) emits the same `HassetteForgottenAwaitWarning` as a primary.
- [ ] AC#2: a test awaits a converted bus method, asserts the returned `Subscription` type, `db_id` is an int, and no `HassetteForgottenAwaitWarning` (nor native inner-coroutine warning) is emitted.
