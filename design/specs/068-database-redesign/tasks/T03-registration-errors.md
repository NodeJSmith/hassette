---
task_id: "T03"
title: "Add registration error exceptions and name= validation"
status: "planned"
depends_on: ["T01"]
implements: ["FR#3", "FR#20", "AC#6", "AC#14"]
---

## Summary
Add two new exception classes for registration errors and wire the `name=` validation into the Bus subscription methods. This makes `name=` required on all DB-registered listeners, with clear error messages when omitted or duplicated.

## Prompt
**Step 1: Add exceptions** to `src/hassette/exceptions.py`:

`ListenerNameRequiredError(HassetteError)` — raised when `name=` is omitted. Include `handler_method: str` and `topic: str` as instance attributes. Message template from design doc Registration Errors section.

`DuplicateListenerError(HassetteError)` — raised when a second listener with the same `(name, topic)` is registered within the same app instance in the same session. Include `name: str`, `topic: str`, `existing_handler: str`, `duplicate_handler: str` as instance attributes. Message template from design doc.

**Step 2: Wire name= validation into Bus** — in `src/hassette/bus/bus.py`:
- In `_on_internal()` or `_subscribe()`: if the listener is DB-registered (not a cancel-listener) and `name` is None, raise `ListenerNameRequiredError`.
- Update `check_listener_collision` / `_listener_natural_key()`: change the natural key to `(owner_key, instance_index, name, topic)` — drop `handler_name` from the key. Remove the `name or human_description` fallback since `name` is now required. The `DuplicateListenerError` detection stays in-memory.
- Once-listeners are exempt from `DuplicateListenerError` (preserve the existing `check_listener_collision` early return for once-listeners).

**Step 3: Add `name` to the `Options` TypedDict** in `bus/bus.py` so convenience methods (`on_component_loaded`, etc.) can accept `name=`.

**Step 4: Add framework listener names** — add explicit `name=` to registrations in:
- `core/state_proxy.py` — 1 listener (e.g., `name="hassette.state_proxy.on_reconnect"`)
- `core/runtime_query_service.py` — ~6 listeners (e.g., `name="hassette.rqs.on_invocation_completed"`)

**Step 5: Write unit tests:**
- Test: registering without `name=` raises `ListenerNameRequiredError` with correct attributes
- Test: registering two handlers with same name+topic raises `DuplicateListenerError` with both handler names
- Test: same name, different topics — no error (topic is part of key)
- Test: once-listeners with duplicate name+topic — no error (exempt)

## Focus
- Framework services that already provide names (ServiceWatcher 5, AppHandler 1, SessionManager 1) do NOT need changes.
- The `Options` TypedDict at `bus/bus.py:112-128` must gain a `name` field — without it, ~14 convenience methods cannot pass `name=`.
- `_listener_natural_key()` at `bus/bus.py:210-219` currently uses a 5-field key including `handler_name` — must drop `handler_name` and remove the `name or human_description` fallback.
- Cancel-listeners bypass DB registration entirely — they should not require `name=`.

## Verify
- [ ] FR#3: Registering a listener without `name=` raises `ListenerNameRequiredError`
- [ ] FR#20: Registering two different handlers with the same name+topic raises `DuplicateListenerError`
- [ ] AC#6: The error message includes the handler method name and topic
- [ ] AC#14: The error message names both the duplicate name and the topic
