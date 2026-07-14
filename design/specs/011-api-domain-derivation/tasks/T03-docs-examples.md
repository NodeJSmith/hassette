---
task_id: "T03"
title: "Update documentation, snippets, and examples"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#3", "FR#4", "AC#3", "AC#10", "AC#11"]
---

## Summary

Update all docs pages, code snippets, and example apps to reflect the new method signatures: remove `domain=` args that are now auto-derived, rename `toggle_service` references to `toggle`, update parameter tables, remove deprecation admonitions (the default is now correct), and add `**data` documentation for `turn_off`/`toggle`. All snippets are Pyright-checked in CI, so they must have valid type annotations.

## Target Files

- modify: `docs/pages/core-concepts/api/methods.md`
- modify: `docs/pages/core-concepts/api/snippets/api_helpers.py`
- modify: `docs/pages/testing/harness.md`
- modify: `docs/pages/testing/snippets/testing_assert_turn_on_off.py`
- modify: `docs/pages/getting-started/snippets/first_automation_step3.py`
- modify: `docs/pages/getting-started/snippets/first_automation_step4.py`
- modify: `docs/pages/getting-started/first-automation.md`
- modify: `docs/pages/troubleshooting.md`
- read: `docs/pages/migration/snippets/api_hassette_call_service.py`
- read: `docs/pages/recipes/service-call-reaction.md`
- read: `examples/climate_controller.py`
- read: `examples/motion_lights.py`

## Prompt

Update documentation and examples to reflect the new Api signatures. Follow the voice guide in `.claude/rules/voice-guide.md` and doc rules in `.claude/rules/doc-rules.md`.

### 1. `docs/pages/core-concepts/api/methods.md`

**Calling Services warning admonition** (line 198): Change `toggle_service` to `toggle` in the method list.

**`turn_on` section** (line 217):
- Update parameter table: change `domain` type from `str` to `str \| None`, default from `"homeassistant"` to `None`. Add description: "Service domain. Derived from entity_id when omitted."
- Remove the `!!! warning "HA 2024.x deprecated..."` admonition (lines 232-235) — the default is now correct.

**`turn_off` section** (line 237):
- Update heading from `turn_off(entity_id, domain)` to `turn_off(entity_id, domain, **data)`.
- Update description: "Shorthand for `call_service(domain, "turn_off", ...)`. Extra keyword arguments pass through as service data."
- Update parameter table: same `domain` changes as `turn_on`. Add `**data` row matching `turn_on`'s.

**`toggle_service` section** (line 250):
- Rename heading from `toggle_service(entity_id, domain)` to `toggle(entity_id, domain, **data)`.
- Update description to match `turn_off`'s new pattern.
- Update parameter table: same changes.

### 2. `docs/pages/core-concepts/api/snippets/api_helpers.py`

Update the snippet file used by the methods.md page:

```python
# --8<-- [start:turn_on]
await self.api.turn_on("light.kitchen", brightness=255, color_name="blue")
# --8<-- [end:turn_on]

# --8<-- [start:turn_off]
await self.api.turn_off("switch.fan")
# --8<-- [end:turn_off]

# --8<-- [start:toggle]
await self.api.toggle("light.bedroom")
# --8<-- [end:toggle]
```

Remove `domain=` from all calls (auto-derived now). Rename `toggle_service` to `toggle`. The `turn_on` call already omits `domain=` — verify and keep as-is if so.

### 3. `docs/pages/testing/harness.md`

Line 201: Change `toggle_service` to `toggle` in the method list describing what the api_recorder captures.

### 4. `docs/pages/testing/snippets/testing_assert_turn_on_off.py`

Remove `domain="light"` from the assertion examples — domain is now auto-derived:

```python
harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")
harness.api_recorder.assert_called("turn_off", entity_id="light.kitchen")
```

### 5. `docs/pages/getting-started/snippets/first_automation_step3.py`

Remove `domain="light"` from the `turn_on` call (line 19):
```python
await self.api.turn_on("light.porch")
```

### 6. `docs/pages/getting-started/snippets/first_automation_step4.py`

Same change — remove `domain="light"` from `turn_on` call (line 22).

### 7. `docs/pages/getting-started/first-automation.md`

Line 23: Update the prose that explains `domain="light"`. The sentence currently says the `domain="light"` parameter tells HA which service domain to use. Replace with prose explaining that the domain is derived automatically from the entity_id — no need to pass it explicitly.

### 8. `docs/pages/troubleshooting.md`

Line 59: Change `toggle_service()` to `toggle()` in the forgotten-await method list.

### Read-only checks

- `docs/pages/migration/snippets/api_hassette_call_service.py`: Uses `self.api.turn_on("light.kitchen", brightness=200)` — already correct (no `domain=`). No change needed.
- `docs/pages/recipes/service-call-reaction.md`: References `light.turn_on` as a HA service, not a Hassette method. No change needed.
- `examples/climate_controller.py`: Uses `self.api.turn_on(self.app_config.ac_switch)` and `self.api.turn_off(self.app_config.ac_switch)` — already correct (no `domain=`). No change needed.
- `examples/motion_lights.py`: Uses entity `turn_on`/`turn_off` via the entity model. No change needed.

### Verification

Run `prek -a` to verify Pyright still passes on all snippet files. The CI type-checks snippets, so any type error in updated snippets will be caught.

## Focus

- Snippets are Pyright-checked in CI. Remove `domain=` args cleanly — don't leave trailing commas or empty parameter lists.
- The `first-automation.md` prose (line 23) is the most visible user-facing text. Rewrite it to explain the new auto-derivation behavior clearly, following the voice guide (system-as-subject for concept pages, no "you" except in getting-started procedure steps).
- The `testing_assert_turn_on_off.py` snippet is included in the testing docs — removing `domain=` from the assertion example matches the new behavior where apps don't pass `domain=` and the recorder captures the derived domain.
- Don't touch migration snippets that show the old AppDaemon way — those are historical comparisons.
- The `harness.md` reference at line 201 is in prose, not a code block — update the method name string in the text.

## Verify

- [ ] FR#1: Doc examples show `turn_on("light.kitchen")` without `domain=` arg
- [ ] FR#3: No `toggle_service` references remain in any docs page or snippet — `grep -r "toggle_service" docs/` returns nothing in active content
- [ ] FR#4: `turn_off` and `toggle` docs show `**data` parameter in their signatures and parameter tables
- [ ] AC#3: `toggle_service` does not appear in any docs page method list or heading
- [ ] AC#10: `prek -a` passes cleanly (includes snippet type checking)
- [ ] AC#11: All doc snippets type-check via Pyright
