---
task_id: "T15i"
title: "Update system tests for unified schema and async registration"
status: "planned"
depends_on: ["T04", "T11"]
implements: ["AC#1"]
---

## Summary
System tests (`tests/system/`, Docker-backed) reference the deleted `Subscription.registration_task`, the now-always-true `db_id` gate, and register handlers in test apps without `name=` / without awaiting the async API.

## Prompt
**Files (write targets):** `tests/system/conftest.py`, `tests/system/apps/bus_handler_app.py`, and any of `tests/system/test_bus.py` / `tests/system/test_scheduler.py` / `tests/system/test_state_proxy.py` / `tests/system/test_app_lifecycle.py` that fail collection or reference removed symbols.

1. `conftest.py:262` area — simplify the `sub.listener.db_id is not None` gate (synchronous registration makes it always true) and remove any `registration_task` references.
2. `apps/bus_handler_app.py`: add `name=` to listener registrations; `await` the async registration calls (it is an app, so registrations in `on_initialize` are awaited by the app — verify whether this app awaits directly).
3. Update any system test referencing old endpoints/table names to the unified surface.

## Focus
- **Do NOT run the full Docker system suite in this task's gate** — per the HYBRID strategy, `uv run nox -s system` (green) is owned by T16. Here, verify collection/import only: `uv run pytest tests/system/ --collect-only -q`. Note in your output that the full system run is deferred to T16.
- No production-code changes.
- See [[deferred-items]] for the async-everywhere and registration_task context.

## Verify
- [ ] `tests/system/` collects without import/collection errors
- [ ] No references to `registration_task` or the conditional `db_id` gate remain
- [ ] Test apps register with `name=` under the async API
