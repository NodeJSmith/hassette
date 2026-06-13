---
task_id: "T03"
title: "Add if_exists resolution to bus registration (durable listeners)"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#9", "FR#10", "AC#1", "AC#2", "AC#3", "AC#4", "AC#7", "AC#9"]
---

## Summary
The core change: thread `if_exists="error" | "skip" | "replace"` through the bus registration
surface and implement the error/skip/replace decision for durable (non-once) listeners. Stores
the existing `Listener` so `skip` can return it and `replace` can cancel it, writes
`cancelled_at` on cancel, and changes `add_listener` to return a `Subscription`. once-listeners
remain exempt in this task — T04 removes the exemption.

## Prompt
Implement `if_exists` for the bus, mirroring `Scheduler._add_job`'s collision block
(the `if existing is not None:` branch at scheduler.py:247; public `add_job` at :174).
See the design's `## Architecture` → "Threading `if_exists`", "Collision resolution",
"Storing the listener", and "Durable cancellation marker".

1. **Options key** — in `src/hassette/bus/options.py`, add to the `Options` TypedDict:
   `if_exists: Literal["error", "skip", "replace"]`. This propagates `if_exists` through
   `**opts: Unpack[Options]` to every event-specific method and into `_on_internal`.

2. **Explicit params** — in `src/hassette/bus/bus.py`, add an explicit
   `if_exists: Literal["error", "skip", "replace"] = "error"` parameter to `on()` (it has an
   explicit signature, no `**opts`), to `_on_internal`, and to `add_listener`. Forward it.
   `_subscribe` already passes `**opts` through, so it carries `if_exists` automatically.
   **Note:** the public `add_listener` (bus.py:183) is a thin wrapper around the private
   `_add_listener` (bus.py:209), and the collision check runs inside `_add_listener` — thread
   `if_exists` through `_add_listener`, not just the public wrapper.

3. **Collision resolution** — reshape `register_and_check_collision` (bus.py:219) into the
   single decision point, renamed to a `_`-prefixed name (e.g. `_resolve_collision`) so the
   sync-facade codegen skips it. It must:
   - compute the natural key and look up the existing `Listener`;
   - no existing → register the key, return None (proceed);
   - existing + `error` → raise `DuplicateListenerError` (current behavior, unchanged);
   - existing + `replace` → cancel/remove the existing listener (route removal + `cancelled_at`
     write — see step 6), then register the new key, return None (proceed);
   - existing + `skip` and `existing.config_matches(new)` → return the existing listener
     (short-circuit, do not register the new one);
   - existing + `skip` and configs differ → raise `ValueError` listing
     `existing.diff_fields(new)`, mirroring scheduler.py:209–213.
   Have it return `Listener | None` (existing on skip short-circuit, None to proceed).
   Rewrite the method's docstring — the current one ("Once-listeners are exempt and are not
   registered") describes behavior this work changes; document the error/skip/replace
   contract instead.

   **Leave the `if listener.options.once: return` once-exemption in place in this task** — it
   stays exactly as today so durable-listener behavior is the only thing changing here. T04
   removes the exemption and adds once-listener tracking. Do not touch once-listener behavior in
   T03.

4. **Storage change** — change `_registered_handler_names: dict[tuple[str, int, str, str], str]`
   (bus.py:144) to `_registered_listeners: dict[tuple[str, int, str, str], Listener]` (value is
   the `Listener`). Update every reference: `on_initialize` clears the map (bus.py:150),
   `remove_listener` (bus.py:251) pops it, and `remove_all_listeners` (bus.py:257) clears it.
   Derive the handler name for `DuplicateListenerError` from
   `listener.identity.handler_name`.

5. **Caller shaping** — `_on_internal` and `add_listener` call `_resolve_collision`. On a skip
   short-circuit (returns the existing listener), return a `Subscription` wrapping the existing
   listener (`Subscription(existing, lambda: self.remove_listener(existing))`). `add_listener`
   changes its return type from `None` to `Subscription` (FR#10) and returns the new or existing
   subscription — update BOTH the private `_add_listener` return type AND the public wrapper's
   `Coroutine[Any, Any, None]` annotation (bus.py:183) to `Coroutine[Any, Any, Subscription]`. On proceed, register normally and await `bus_service.add_listener`.

6. **Cancel-path telemetry write** — when the bus cancels/removes a listener via
   `Bus.remove_listener`, spawn `BusService.mark_listener_cancelled(listener.db_id)` (added in
   T01) for a listener whose `db_id` is set, mirroring how `Scheduler.cancel_job` (scheduler.py:302–309)
   spawns `mark_job_cancelled` via `self.scheduler_service.task_bucket.spawn(...)`. Spawn on
   `bus_service.task_bucket` — the **service's** bucket, NOT `Bus.task_bucket` — so the write
   survives resource shutdown. This covers `Subscription.cancel` and `replace`'s cancel-old step.

Add unit tests covering durable (non-once) listeners: `skip` idempotent re-registration returns
a subscription and leaves one listener; `skip` with drift raises `ValueError` naming changed
fields; `replace` leaves one routed listener with the same `db_id` and old unrouted; `error`/
default raises `DuplicateListenerError`; `Subscription.cancel()` writes `cancelled_at`;
`add_listener` returns a `Subscription` including the skip-returns-existing case; `if_exists`
reaches a representative `**opts` method (`on_call_service`) and `on()`.

## Focus
- The registration funnel: public methods → `_subscribe` (bus.py:445) → `_on_internal`
  (bus.py:351) → `register_and_check_collision` + `bus_service.add_listener`. `on()` (bus.py:276)
  calls `_on_internal` directly. `add_listener` (bus.py:183) → `_add_listener` (bus.py:209) is a
  separate funnel that also runs the collision check. Keep `if_exists` flowing through all of these.
- `BusService.add_listener` (bus_service.py:114) returns the `db_id` (int) and sets it on the
  listener via `mark_registered`. After `replace`, the new listener upserts onto the SAME
  natural-key row, so its `db_id` equals the replaced listener's — this is correct (row-id
  preservation, AC#3). The `cancelled_at` written when cancelling the old listener is cleared by
  the new listener's upsert (`cancelled_at = NULL`, added in T01).
- **Non-atomic replace:** cancel-old happens before the awaited register-new. The unique natural
  key forbids two live listeners under one key, so cancel-first ordering is forced. If
  register-new fails, the app is left with no listener — log at the cancel and register steps so
  the gap is observable. This matches the scheduler; do not over-engineer a rollback.
- `Subscription` (listeners.py:451) wraps `(listener, unsubscribe)`; `cancel()` calls
  `unsubscribe`. The skip-return subscription's unsubscribe must remove the existing listener.
- Keep `_resolve_collision` underscore-prefixed — `sync_facade/ast_utils.py` skips `_`-prefixed
  methods, so this keeps it off the generated facade.
- Do NOT regenerate `bus/sync.py` here — that is T05, after all signature changes (T03 + T04)
  are done.
- The once-exemption stays in this task; once-listener collision tests belong in T04.

## Verify
- [ ] FR#1: `if_exists` accepted (default `"error"`) on `on()`, `add_listener`, and the
      `**opts` methods (verified via `on_call_service`).
- [ ] FR#2: `if_exists="error"` (and omission) raises `DuplicateListenerError` on a same-key
      clash — unchanged behavior.
- [ ] FR#3: `if_exists="skip"` with a matching existing listener returns a subscription and
      registers no second listener.
- [ ] FR#4: `if_exists="skip"` with a differing config raises `ValueError` whose message lists
      the changed fields (from `diff_fields`).
- [ ] FR#5: `if_exists="replace"` cancels the existing listener and registers the new one on the
      same natural-key row, returning a subscription to the new listener.
- [ ] FR#9: cancelling a listener via `Bus.remove_listener` (Subscription.cancel and replace's
      cancel-old) spawns `mark_listener_cancelled`, setting `cancelled_at`.
- [ ] FR#10: `add_listener` returns a `Subscription`, returning the existing listener's
      subscription on `if_exists="skip"`.
- [ ] AC#1: two identical `skip` calls return a subscription both times and leave exactly one
      registered listener.
- [ ] AC#2: `skip` after a same-key-but-different registration raises `ValueError` listing the
      changed fields.
- [ ] AC#3: `replace` leaves exactly one routed listener (the new one) with an unchanged
      `db_id`; the old listener is unrouted and `cancelled_at` is cleared after re-registration.
- [ ] AC#4: `error`/default under an existing key raises `DuplicateListenerError`.
- [ ] AC#7: `Subscription.cancel()` without re-registration sets `cancelled_at` on the row.
- [ ] AC#9: `add_listener` returns a `Subscription`, including the skip-returns-existing case.
