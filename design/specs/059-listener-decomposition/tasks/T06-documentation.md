---
task_id: "T06"
title: "Update documentation for decomposed Listener and registration_task"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#8", "AC#7"]
---

## Summary
Update the bus documentation and CLAUDE.md to reflect the decomposed Listener structure, the new sub-structs, the Bus.on() public API changes, and the registration_task on Subscription. Add docstrings to all new structs.

## Prompt
Read the design doc section "Documentation Updates".

**Step 1: Add docstrings** to each new struct in `src/hassette/bus/listeners.py`:
- `ListenerIdentity` — one-line class docstring explaining it groups ownership and telemetry fields
- `ListenerOptions` — one-line class docstring explaining it groups behavioral timing parameters
- `HandlerInvoker` — one-line class docstring explaining it owns handler invocation, dispatch, and rate limiting
- `DurationConfig` — one-line class docstring explaining it groups duration-hold configuration and owns the timer lifecycle

**Step 2: Update Bus.on() docstring** in `src/hassette/bus/bus.py`:
- Remove references to `is_attribute_listener`, `hold_preds`, `entity_id`, `immediate`, `duration` from the Args section
- Document that these are available through `on_state_change()` and `on_attribute_change()` only
- Add `registration_task` to the Returns description

**Step 3: Update docs site** at `docs/pages/core-concepts/bus/handlers.md`:
- Add `registration_task` to the subscription reference section
- Show example: `await sub.registration_task` for deterministic ordering
- Note that `registration_task` is a completion signal (resolves regardless of DB outcome)

**Step 4: Update CLAUDE.md** Architecture > Bus section:
- Mention that Listener composes ListenerIdentity, ListenerOptions, HandlerInvoker, and DurationConfig
- Update the Subscription description to include `registration_task`

## Focus
- Docstrings should be one line per struct — no multi-paragraph blocks per project convention.
- The docs site page at `docs/pages/core-concepts/bus/handlers.md` needs to exist — verify via Glob before editing.
- `CLAUDE.md` is the project root instructions file. The Bus description is in the Architecture > Core Components section.
- Registration_task documentation should emphasize the completion-signal semantics (not success/failure).

## Verify
- [ ] FR#8: docs/pages/core-concepts/bus/handlers.md documents registration_task with usage example
- [ ] AC#7: Documentation states registration_task is a completion signal that resolves with None; callers check db_id for persistence status
