---
task_id: "T14"
title: "Update documentation for new registration and schema"
status: "done"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#3", "FR#5", "AC#6"]
---

## Summary
Update user-facing documentation to reflect the new `name=` requirement, synchronous registration, and removed fields. Update CLAUDE.md project guidance.

> **ASYNC-EVERYWHERE (decided during T04, 2026-05-29):** The public Bus AND Scheduler registration APIs are now `async`. Registration is awaited inline so `db_id`/`listener.db_id`/`job.db_id` is set on return (satisfies AC#7). User code must now write `await self.bus.on_state_change(...)` and `await self.scheduler.run_in(...)`. All docs, snippets, docstrings, and CLAUDE.md examples must show `await`. (Exception: `bus.on_error()` stays sync.) See [[deferred-items]] (orchestration tmpdir) for the full list of snippet files the T04 executor left un-awaited on the bus side.

## Prompt
**Step 1: Update `docs/pages/core-concepts/bus/handlers.md`:**
- Remove `registration_task` and `db_id` from the reference table
- Update registration guidance: "registration is complete when `on_state_change()` returns"
- Add `name=` parameter documentation — required, must be a stable string identifier
- Document `ListenerNameRequiredError` and `DuplicateListenerError`
- Follow the voice guide in `.claude/rules/voice-guide.md`

**Step 2: Update code snippets (async + name=):**
- `docs/pages/core-concepts/bus/snippets/handlers/bus_subscription_patterns.py` — remove `registration_task` patterns (field deleted). Add `name=` to all subscription examples.
- Add `await` to EVERY `self.bus.on_*(...)` call across all doc snippets (the T04 executor updated scheduler snippets but missed the bus side — these currently FAIL `pyright --project docs`). Affected dirs include `recipes/snippets/`, `getting-started/snippets/`, `core-concepts/bus/snippets/`, `migration/snippets/`, `advanced/snippets/`, `web-ui/.../snippets/`, `testing/snippets/`. Also add `name=` where missing. (`on_error` stays sync.)
- Verify the suite passes the docs typecheck: `uv run pyright --project docs`.

**Step 3: Update `docs/pages/core-concepts/internals.md`:**
- Update database section for PRAGMA user_version migration runner
- Document unified `executions` table (replacing two tables)
- Note the delete-recreate migration strategy

**Step 4: Update `CLAUDE.md`:**
- Update "Bus" description: `name=` is required on all DB-registered listeners
- Update "Resource Hierarchy": `BusService.depends_on` and `SchedulerService.depends_on` include `[DatabaseService]`
- Note `Subscription` field changes (no `registration_task`)
- Update registration flow description

**Step 5: Update API reference docstrings:**
- `Bus.on_state_change()`, `Bus.on()`, `Bus.on_attribute_change()`, `Bus.on_call_service()` — document `name` parameter as required AND that the method is now `async` (callers must `await`)
- All convenience methods — document `name` parameter and async usage
- Fix the module-level docstring examples in `src/hassette/bus/bus.py` (top of file), `src/hassette/event_handling/conditions.py`, `src/hassette/event_handling/accessors.py`, and the error template in `src/hassette/exceptions.py` — they show un-awaited `self.bus.on_*(...)` calls and must show `await`.

## Focus
- Follow the voice guide: system-as-subject for concept pages, "you" only in getting-started content.
- All code examples must live in tested snippet files (see doc-rules.md).
- The breaking change (name= required) needs clear migration guidance for existing users.

## Verify
- [ ] FR#3: Documentation states that `name=` is required on all DB-registered listeners
- [ ] FR#5: Documentation states registration is complete when the awaited call returns (the public API is async; `db_id` is set on return), and all examples use `await`
- [ ] AC#6: Error message examples in docs match the `ListenerNameRequiredError` template
