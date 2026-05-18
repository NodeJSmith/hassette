---
task_id: "T02"
title: "Split Bus.on() into public and private APIs"
status: "planned"
depends_on: ["T01"]
implements: ["FR#7", "FR#8", "FR#11", "AC#6", "AC#7", "AC#11"]
---

## Summary
Split `Bus.on()` into a clean public method and a private `_on_internal()` that carries the full parameter set. Update `on_state_change()` and `on_attribute_change()` to build DurationConfig and call `_on_internal()`. Add `registration_task` to Subscription. Fix the hold_preds in-place mutation. Update Bus consumer paths (_listener_natural_key, add_listener collision detection) to read from sub-structs.

## Prompt
Read the design doc sections "Bus.on() / _on_internal() split", "Subscription with registration_task", "Bus consumer updates", and "Fixes included".

**Step 1: Add registration_task to Subscription** in `src/hassette/bus/listeners.py`:
- Add `registration_task: asyncio.Future[None] | None = None` field
- This is a completion signal, not a success signal (resolves with None regardless of DB outcome)

**Step 2: Split Bus.on()** in `src/hassette/bus/bus.py`:

`Bus.on()` (public) keeps: `topic`, `handler`, `where`, `kwargs`, `once`, `debounce`, `throttle`, `timeout`, `timeout_disabled`, `name`, `on_error`. No `is_attribute_listener`, `hold_preds`, `entity_id`, `immediate`, `duration`, `priority`. Delegates to `_on_internal()` with `duration_config=None`.

`Bus._on_internal()` (private) adds: `duration_config: DurationConfig | None`, `entity_id: str | None`, `is_attribute_listener: bool`, `hold_preds: list[Predicate] | None`. This is where Listener.create() is called, source location captured, Subscription constructed. Capture the return of `self.add_listener(listener)` as the registration_task and pass to Subscription.

**Step 3: Update on_state_change() and on_attribute_change()** to build DurationConfig when `duration` is provided, then call `_on_internal()`. The `entity_id`, `is_attribute_listener`, and `hold_preds` parameters flow through `_on_internal()`, not through the public `on()`.

**Step 4: Fix hold_preds mutation** in `Bus._subscribe()` at line 362-363. Replace `hold_preds.append(normalized_where)` with `hold_preds = [*hold_preds, normalized_where]`.

**Step 5: Update Bus consumer paths:**
- `Bus._listener_natural_key()`: `listener.app_key` → `listener.identity.app_key`, `listener.instance_index` → `listener.identity.instance_index`, `listener.handler_name` → `listener.identity.handler_name`, `listener.name` → `listener.identity.name`
- `Bus.add_listener()` collision path: `listener.once` → `listener.options.once`, `listener.handler_name` → `listener.identity.handler_name`

**Step 6: Update Options TypedDict** — remove `name` if it's now an explicit parameter on `_on_internal()`. Keep `once`, `debounce`, `throttle`, `timeout`, `timeout_disabled`, `on_error`.

**Step 7: Write tests:**
- Test `Bus.on()` public signature does not accept `is_attribute_listener`, `hold_preds`, `entity_id`
- Test `subscription.registration_task` is a Future and is awaitable
- Test cancel-listener subscriptions get an already-resolved Future (or None)
- Test hold_preds list is not mutated after `_subscribe()`

## Focus
- `bus.py` is 1002 lines. The split adds ~30 lines (new method signature + delegation) but the public on() gets shorter.
- `_subscribe()` is the common tail for on_state_change/on_attribute_change — it normalizes predicates and delegates to on(). After refactor it delegates to _on_internal().
- `priority` stays Bus-level: `_on_internal()` sources it from `self.priority` when constructing ListenerOptions.
- The `source_location` and `registration_source` capture at bus.py:314-316 moves into `_on_internal()` — called before constructing ListenerIdentity.
- `self._error_handler` resolver setup at bus.py:318 moves into `_on_internal()` — set on the invoker via `listener.invoker.set_app_error_handler_resolver(...)` or passed during HandlerInvoker construction.

## Verify
- [ ] FR#7: Bus.on() signature contains no parameters named is_attribute_listener, hold_preds, entity_id, immediate, duration, or priority
- [ ] FR#8: subscription.registration_task is an asyncio.Future[None] that resolves after add_listener completes
- [ ] FR#11: A list passed as hold_preds to _subscribe() is not modified in place after the call returns
- [ ] AC#6: Calling Bus.on(is_attribute_listener=True) raises TypeError (unexpected keyword argument)
- [ ] AC#7: await subscription.registration_task resolves with None; subscription.listener.db_id can be checked for persistence status
- [ ] AC#11: hold_preds list identity (id()) is unchanged after _subscribe() returns
