---
task_id: "T04"
title: "Make listener and job registration synchronous"
status: "done"
depends_on: ["T02", "T03"]
implements: ["FR#5", "FR#6", "AC#7"]
---

## Summary
Eliminate the dual-ID architecture. Registration becomes synchronous — the DB INSERT is awaited inline via `database_service.submit()` before the listener or job is routable. Remove the `RegistrationTracker`, `registration_task`, `_listener_id_seq`, `JOB_ID_SEQ`, `mark_registered()`, and all barrier machinery.

## Prompt
**Step 1: Make BusService registration synchronous** — in `core/bus_service.py`:
- `add_listener()`: await `database_service.submit()` inline instead of `self.task_bucket.spawn()`. Return type changes from `asyncio.Task[None]` to `int` (the db_id). Remove `_reg_tracker` calls.
- Add `depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]` following the CommandExecutor pattern.
- Delete `drain_framework_registrations()`.
- Delete `await_registrations_complete()`.

**Step 2: Make SchedulerService registration synchronous** — in `core/scheduler_service.py`:
- `_enqueue_then_register()` collapses — registration awaited before enqueuing to the scheduler heap.
- Add `depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]`.
- Delete `await_registrations_complete()`.

**Step 3: Update Bus internals** — in `bus/bus.py`:
- `_on_internal()` no longer captures a task into `Subscription.registration_task`. The db_id from `bus_service.add_listener()` is set directly on the Listener.

**Step 4: Update Subscription** — in `bus/listeners.py`:
- Remove `registration_task: asyncio.Future[None] | None` field from `Subscription`.
- Remove `_listener_id_seq` (`itertools.count`).
- The Listener's `db_id` field is set at construction time (from the synchronous registration return value), not lazily.

**Step 5: Update ScheduledJob** — in `scheduler/classes.py`:
- Remove `JOB_ID_SEQ`, `db_id` field (use the returned int from registration), `mark_registered()`.

**Step 6: Simplify related code:**
- `bus/invocation.py` — `listener.db_id` read becomes eager (guaranteed set before routable).
- `bus/duration_hold.py` — cancel-listener pre-resolved Future simplified (no registration_task needed).
- `core/registration_tracker.py` — delete the entire file.
- `core/app_lifecycle_service.py` — remove `await_registrations_complete()` barrier calls.
- `core/core.py` — remove `await bus_service.drain_framework_registrations()` block.

**Step 7: Update tests:**
- Update `test_bus_contract.py` — remove `await sub.registration_task`; verify `sub.listener.db_id` is immediately available.
- Update `test_bus_public_private_split.py` — remove `registration_task` assertions.
- Simplify `test_duration_hold.py` — cancel-listener Future tests.
- Update `test_listeners.py` — `Subscription` field assertions for removed fields.
- Delete `test_scheduler_service_barrier.py` — barrier deleted.
- Delete `test_registration_tracker.py` — class deleted.
- Simplify `tests/system/conftest.py:262` — `sub.listener.db_id is not None` is always true.
- Update integration tests that await `registration_task` or call `mark_registered()`.
- Update `test_scheduler_service_*.py` (4 files) that instantiate `RegistrationTracker`.
- Update `test_bus_service_public_accessors.py` that instantiates `RegistrationTracker`.
- New test: verify listener db_id is set before handler is routable (FR#5).

## Focus
- `CommandExecutor.register_listener()` and `register_job()` currently call `wait_for_ready([database_service])` — this guard disappears once `BusService` and `SchedulerService` have `depends_on`. Remove those calls.
- Cancel-listeners bypass DB registration entirely — they should still work without `registration_task`.

## Verify
- [ ] FR#5: Listener db_id is set before the handler becomes routable (test proves ordering)
- [ ] FR#6: No `_listener_id_seq` or `JOB_ID_SEQ` exists; db_id is the only identifier
- [ ] AC#7: `sub.listener.db_id` is a valid integer immediately after `on_state_change()` returns
