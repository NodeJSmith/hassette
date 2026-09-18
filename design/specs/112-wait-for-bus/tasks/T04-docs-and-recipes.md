---
task_id: "T04"
title: "Add wait_for documentation and composition recipes"
status: "planned"
depends_on: ["T01"]
implements: []
---

## Summary
Add API documentation for `Bus.wait_for()` to the docs site, including two composition recipes: the single-stage arm-before-fire pattern and the two-stage "confirm started, then wait for idle" pattern. Update CLAUDE.md to mention the new method.

## Target Files
- modify: `docs/pages/core-concepts/bus/methods.md`
- modify: `CLAUDE.md`
- read: `src/hassette/bus/bus.py`
- read: `design/specs/112-wait-for-bus/design.md`

## Prompt
Add documentation for `Bus.wait_for()` to `docs/pages/core-concepts/bus/methods.md`.

### Method documentation

Add a section for `wait_for` with:
- Method signature: `async def wait_for(topic, *, where=None, timeout, name=None) -> Event[Any]`
- Parameter descriptions (topic, where, timeout, name)
- Return type: the matching `Event[Any]`
- Exceptions: `asyncio.TimeoutError` on timeout, `CancelledError` on shutdown
- A simple usage example (waiting for a state change)

### Composition recipes

Document two patterns, explicitly narrating why each matters:

**Recipe 1: Single-stage arm-before-fire**
```python
wait_task = asyncio.create_task(
    self.bus.wait_for("state_changed",
        where=P.EntityId("light.kitchen") & P.StateTo("on"),
        timeout=5)
)
await self.api.call_service("light", "turn_on", entity_id="light.kitchen")
event = await wait_task
```
Explain: arm the wait BEFORE the service call so the listener is registered before the event can arrive.

**Recipe 2: Two-stage "confirm started, then wait for idle"**
For media-player-style automations where the device is already `idle` before the action:
1. Wait for the entity to leave `idle` (confirm the action started)
2. Call the service
3. Wait for the entity to return to `idle` (confirm the action finished)

Explain: a single `wait_for(state == idle)` would resolve instantly on the pre-existing state because FR#2 only protects against pre-*registration* state, not against a *different* idle that isn't the one you care about.

Note: the race-free composition primitive is #2286 (`call_and_wait`). The `create_task` pattern has a theoretical race window (documented in design.md Edge Cases).

### CLAUDE.md update

Add `wait_for` to the Bus description in `CLAUDE.md`, mentioning it as a one-shot await primitive for sequential automation logic.

## Focus
- Read the existing `docs/pages/core-concepts/bus/methods.md` to understand the documentation style, heading structure, and code example formatting.
- The two-stage recipe is critical — it addresses the exact production bug (bedtime automation) that motivated issue #528. A reader who only sees Recipe 1 could reproduce the original bug on media-player automations.
- Keep the docs consistent with the design doc's FR#2 semantics: only events arriving *after registration* match, not pre-existing state.

## Verify
(No FR/AC identifiers — documentation task. Verify manually that the docs build and the recipes are accurate.)
