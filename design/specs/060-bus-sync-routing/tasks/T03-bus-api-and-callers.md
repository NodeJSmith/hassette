---
task_id: "T03"
title: "Update Bus public API return types and migrate all callers"
status: "planned"
depends_on: ["T02"]
implements: ["FR#6", "AC#6"]
---

## Summary
Update the Bus public API to reflect the new sync routing contract: `add_listener` and `remove_listener` return `None`, `get_listeners` returns `list[Listener]` directly. Restructure `_on_internal` to capture the DB registration task for `Subscription.registration_task`. Migrate all production-code callers that previously awaited the returned Task.

## Prompt
**1. Modify `src/hassette/bus/bus.py`:**

`add_listener` — returns `None`, retains collision check:
```python
def add_listener(self, listener: Listener) -> None:
    if not listener.options.once:
        natural_key = self._listener_natural_key(listener)
        if natural_key in self._registered_keys:
            raise ValueError(...)
        self._registered_keys.add(natural_key)
    self.bus_service.add_listener(listener)
```

`_on_internal` — calls `bus_service.add_listener` directly to capture the DB task:
```python
# Collision check (same logic as add_listener)
if not listener.options.once:
    natural_key = self._listener_natural_key(listener)
    if natural_key in self._registered_keys:
        raise ValueError(...)
    self._registered_keys.add(natural_key)

def unsubscribe() -> None:
    self.remove_listener(listener)

registration_task = self.bus_service.add_listener(listener)
return Subscription(listener, unsubscribe, registration_task)
```

`remove_listener` — returns `None`, preserves collision-key cleanup:
```python
def remove_listener(self, listener: Listener) -> None:
    self._registered_keys.discard(self._listener_natural_key(listener))
    self.bus_service.remove_listener(listener)
```

`remove_all_listeners` — returns `None`:
```python
def remove_all_listeners(self) -> None:
    self._registered_keys.clear()
    self.bus_service.remove_listeners_by_owner(self.owner_id)
```

`get_listeners` — direct return (no longer async):
```python
def get_listeners(self) -> list[Listener]:
    return self.bus_service.get_listeners_by_owner(self.owner_id)
```

**2. Update `Subscription.registration_task` docstring** in `src/hassette/bus/listeners.py` to state: routing is synchronous, `registration_task` tracks only DB persistence. Include the routing/registration independence contract per design doc `## Architecture > ### Contract documentation (#781)`.

**3. Migrate callers:**

| File | Change |
|---|---|
| `src/hassette/core/core.py:620` | `await self._bus.remove_all_listeners()` → `self._bus.remove_all_listeners()` |
| `src/hassette/test_utils/reset.py:54` | `await bus.remove_all_listeners()` → `bus.remove_all_listeners()` |
| `src/hassette/test_utils/reset.py:96` | `await app_handler.hassette.bus_service.remove_listeners_by_owner("test")` → remove `await` |
| `src/hassette/core/app_lifecycle_service.py:556` | `await inst.bus.get_listeners()` → `inst.bus.get_listeners()` |
| `src/hassette/core/app_lifecycle_service.py:571` | `await router.get_listeners_by_owner(...)` → `router.get_listeners_by_owner(...)` |

Also check `Bus.on_shutdown` for `await self.remove_all_listeners()` — remove the `await`.

Reference: design doc `## Architecture > ### Bus: public API changes`, `### Caller migration`, `### Contract documentation (#781)`.

## Focus
- `bus.py` is ~1112 lines. Key methods: `add_listener` (line 182), `_on_internal` (line 294), `remove_listener` (line 221), `remove_all_listeners` (line 225), `get_listeners` (line 229).
- The collision check is duplicated in `add_listener` and `_on_internal` — this is intentional. Both entry points must guard against duplicates.
- `reset.py` has TWO call sites (lines 54 and 96) — both need `await` removal. The second was missing from the original migration table.
- `app_lifecycle_service.py` has two `await` calls for `get_listeners` / `get_listeners_by_owner` that become sync — both in the reconciliation path.
- The `before_shutdown` method in `core.py` wraps `remove_all_listeners` in `try/except Exception` — this correctly handles synchronous exceptions from the now-sync call.

## Verify
- [ ] FR#6: `_on_internal` passes the DB registration task from `bus_service.add_listener` to `Subscription.registration_task` — callers can await it to know when persistence was attempted. Verify: `grep -n 'registration_task' src/hassette/bus/bus.py` shows the task assignment in `_on_internal`.
- [ ] AC#6: `Subscription.registration_task` docstring states that routing is synchronous and the future resolves regardless of DB success or failure (including `CancelledError` from timeout). Verify: `grep -A5 'registration_task' src/hassette/bus/listeners.py` confirms the updated docstring includes "routing is synchronous" and "resolves regardless".
