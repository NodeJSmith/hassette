---
task_id: "T04"
title: "Track once-listeners with fire-time removal callback"
status: "planned"
depends_on: ["T03"]
implements: ["FR#6", "FR#7", "FR#9", "AC#5", "AC#6", "AC#8"]
---

## Summary
Remove the once-listener collision exemption so once-listeners participate in `if_exists` like
durable listeners (Direction A), and add a fire-time removal callback (`BusService` → `Bus`) so
a once-listener's in-memory key is released and its `cancelled_at` written when it fires. Adapt
the framework's own tests and utilities that depend on the old exempt behavior. This is the
breaking-change task.

## Prompt
See the design's `## Architecture` → "Tracking once-listeners and fire-time cleanup".

1. **Remove the exemption** — in the `_resolve_collision` method (from T03), remove the
   `if listener.options.once: return` early-out so once-listeners register their natural key and
   flow through the identical error/skip/replace path.

2. **Removal-callback registry on BusService** — add a per-owner removal-callback registry to
   `src/hassette/core/bus_service.py`, mirroring the scheduler's
   `SchedulerService.register_removal_callback` / `deregister_removal_callback` and the
   invocation in its removal path (the registry methods live on `SchedulerService`,
   `core/scheduler_service.py:122` and `:135`; `Scheduler` registers its `_on_job_removed` at
   `scheduler/scheduler.py:124` and deregisters at `:146`). When `BusService.remove_listener` (bus_service.py:187) removes a
   listener — including the once-fire path in the dispatch `finally` (bus_service.py:350) — it
   invokes the owning `Bus`'s callback. The registry must tolerate a missing/replaced callback
   (no crash if the owning `Bus` has shut down or been re-created during hot-reload), matching
   how the scheduler's registry guards invocation.

3. **Bus registers/deregisters the callback** — in `src/hassette/bus/bus.py`:
   - In `__init__`, register a callback keyed by `self.owner_id` (e.g. `_on_listener_removed`)
     that pops the natural key from `_registered_listeners` and spawns
     `mark_listener_cancelled(listener.db_id)` (T01) when `db_id` is set.
   - In `on_shutdown` (bus.py:154 — which today lacks this), call
     `bus_service.deregister_removal_callback(self.owner_id)`. This is REQUIRED and is currently
     missing; add it.
   `Bus.remove_listener` already pops the key directly, so the callback closes only the once-fire
   path; a redundant pop is a harmless no-op.

4. **Adapt dependent framework tests/utilities** (these break under once-tracking):
   - `src/hassette/test_utils/helpers.py` — `wire_up_app_state_listener` (def at :415, `once=True`
     at :430) registers a once-listener with a deterministic name. Register it with
     `if_exists="replace"` (or make the name unique per call) so repeated wiring no longer raises.
   - `tests/.../test_hot_reload.py` — at least four test methods call the
     `wire_up_app_running_listener` shorthand twice with the same `app_key`+`RUNNING` (lines
     123/141, 159/177, 259/275, 299/316). Confirm they pass once the helper is adapted.
   - `tests/unit/bus/test_t03_registration_errors.py:125`
     (`test_once_listeners_exempt_from_duplicate_error`) asserts the OLD exempt behavior. Update
     it to assert the new collision behavior (FR#6).

Add unit tests: two `once=True` listeners with the same name+topic and default `if_exists` raise
`DuplicateListenerError`; after a once-listener fires, its natural key is released (a new
registration under the same key succeeds) and its row's `cancelled_at` is set.

## Focus
- once-listeners ARE DB-registered under the natural key today (the `ListenerNameRequiredError`
  docstring at bus.py:189–192 confirms name is required "for all DB-registered listeners,
  including once-listeners"). So tracking them in `_registered_listeners` aligns in-memory state
  with the DB's already-one-row-per-key model.
- The once-fire removal happens in `BusService` dispatch's `finally` block (bus_service.py:350)
  → `BusService.remove_listener` (bus_service.py:187), which does NOT currently touch the per-app
  `Bus._registered_listeners` — that is exactly the gap the removal callback closes. Without it,
  a fired once-listener leaves a stale key that blocks future registration.
- Hot-reload re-creates a `Bus` with the same `owner_id`. The registry must handle
  re-registration of the callback (the scheduler's registry silently replaces on re-register) and
  must not crash on a stale once-fire after the owning `Bus` is gone.
- `Bus.owner_id`, `Bus.task_bucket`, and `self.logger` are available on the `Bus` resource.
- Concurrent `skip` during a once-listener's async dispatch can return a subscription to an
  about-to-be-removed listener (the key is still present until the `finally` runs). This is a
  documented edge case (no-op subscription, not corruption) — do not attempt to lock around it.
- This is the breaking change: ship the PR as `feat!` with a `BREAKING CHANGE:` footer (handled
  in the commit/PR, not in code).

## Verify
- [ ] FR#6: two `once=True` listeners with the same name+topic and default `if_exists` collide —
      the second raises `DuplicateListenerError`; the once-exemption in `_resolve_collision` is
      removed.
- [ ] FR#7: when a once-listener fires, its natural key is released from `_registered_listeners`
      (a subsequent registration under the same key succeeds) and `cancelled_at` is written to its
      row; `Bus.on_shutdown` deregisters the removal callback.
- [ ] FR#9: the once-fire removal path spawns `mark_listener_cancelled`, setting `cancelled_at`.
- [ ] AC#5: registering two same-name+topic `once=True` listeners with default `if_exists` raises
      `DuplicateListenerError`.
- [ ] AC#6: after a `once=True` listener fires, registering a new listener under the same
      name+topic succeeds without raising.
- [ ] AC#8: when a `once=True` listener fires, its database row has `cancelled_at` set.
