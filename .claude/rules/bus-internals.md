---
paths:
  - "src/hassette/bus/**"
---

# Bus — Internals

## Listener structure

The internal `Listener` dataclass composes four sub-structs:

- `ListenerIdentity` — ownership/telemetry fields
- `ListenerOptions` — behavioral timing parameters
- `HandlerInvoker` — handler invocation, dispatch, rate limiting
- `EntityWatch` — the entity a listener tracks (from `on_state_change`/`on_attribute_change`), plus its duration hold and timer lifecycle

## Deliveries

A `Delivery` (`src/hassette/bus/delivery.py`) is one event reaching one listener: listener, event, topic, and whether the event was built from the cached state. It's created where an event reaches a listener (`BusService._match_listeners`, `DurationHoldManager.immediate_fire_task`, a hold's recheck or cancel listener), and every later step takes it rather than a separate event and synthetic flag. `Delivery.invoke` runs the handler through the executor; `Delivery.drop(reason)` records a near-miss through the listener's reporter, read at drop time.

## Registration

Registration is synchronous with the DB — `sub.listener.db_id` is a valid integer as soon as the awaited registration call returns.

`name=` is required on `on_state_change`, `on_attribute_change`, `on_call_service`, and `on` — omitting it raises `ListenerNameRequiredError` at call time. `wait_for` is the exception: its `name` is optional and auto-generated when omitted.

## `wait_for`

`wait_for(topic, *, where=None, timeout, name=None) -> AnyEvent` suspends the caller until a matching event is dispatched and returns that event directly — no handler, no `Subscription` to manage. It only matches events dispatched after the call is awaited (pre-existing state never resolves it), raises `asyncio.TimeoutError` on expiry and `CancelledError` on shutdown/cancellation, and composes with `call_service` via the arm-before-fire pattern documented in `docs/pages/core-concepts/bus/methods.md`.

## Parameter injection

`HandlerInvoker.create()` builds a `ParameterInjector` from the handler's actual signature (`get_typed_signature`) and injects only the parameters the handler declares.
