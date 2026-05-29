---
task_id: "T14"
title: "Update documentation for new registration and schema"
status: "planned"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#3", "FR#5", "AC#6"]
---

## Summary
Update user-facing documentation to reflect the new `name=` requirement, synchronous registration, and removed fields. Update CLAUDE.md project guidance.

## Prompt
**Step 1: Update `docs/pages/core-concepts/bus/handlers.md`:**
- Remove `registration_task` and `db_id` from the reference table
- Update registration guidance: "registration is complete when `on_state_change()` returns"
- Add `name=` parameter documentation — required, must be a stable string identifier
- Document `ListenerNameRequiredError` and `DuplicateListenerError`
- Follow the voice guide in `.claude/rules/voice-guide.md`

**Step 2: Update code snippets:**
- `docs/pages/core-concepts/bus/snippets/handlers/bus_subscription_patterns.py` — remove `await sub.registration_task` patterns. Add `name=` to all subscription examples.

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
- `Bus.on_state_change()`, `Bus.on()`, `Bus.on_attribute_change()`, `Bus.on_call_service()` — document `name` parameter as required
- All convenience methods — document `name` parameter

## Focus
- Follow the voice guide: system-as-subject for concept pages, "you" only in getting-started content.
- All code examples must live in tested snippet files (see doc-rules.md).
- The breaking change (name= required) needs clear migration guidance for existing users.

## Verify
- [ ] FR#3: Documentation states that `name=` is required on all DB-registered listeners
- [ ] FR#5: Documentation states registration is complete on return (no async await needed)
- [ ] AC#6: Error message examples in docs match the `ListenerNameRequiredError` template
