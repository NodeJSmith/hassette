# Context: Bus Dispatch and Subscription Decomposition

## Problem & Motivation
The three longest methods in the bus dispatch and subscription paths mix multiple concerns into single method bodies, making them risky to edit and hard to read. `_immediate_fire_task` (134 lines) interleaves state validation, duration timers, predicates, and dispatch. `_dispatch` (89 lines) duplicates the duration vs. non-duration branching. `on_state_change` and `on_attribute_change` (75/91 lines) duplicate 30+ lines of predicate construction. This decomposition extracts focused helpers without changing any behavior.

## Visual Artifacts
None.

## Key Decisions
1. Extracted helpers are module-level functions (no `self`) where possible, making them independently testable.
2. `start_remaining_duration_timer` and `start_duration_timer` stay as BusService methods (they need `self` for `_read_entity_state`, `_hold_matches`, `remove_listener`).
3. The two timer helpers are NOT unified into one — they differ in whether `override_duration` is passed and how the callback rechecks state. Premature unification would add a boolean flag that obscures the two use cases.
4. The shared predicate builder (`build_change_preds`) is a module-level function in `bus.py`. The `changed=False` warning log stays in `on_attribute_change` — it's method-specific, not predicate logic.
5. Hold predicates gating (`duration is not None`) stays in the calling methods, not the builder. The builder returns hold predicates unconditionally.

## Constraints & Anti-Patterns
- **Pure refactoring** — no behavioral changes, no API changes, no new parameters, no database changes.
- **No new tests** — existing tests are the behavioral contract. If any test fails, the extraction is wrong; do not modify the test.
- **No underscore prefixes** on new module-level functions (personal project rule).
- **Do NOT use `from __future__ import annotations`**.
- All nested closure variables must become explicit parameters on the extracted helpers — no implicit closure state.

## Design Doc References
- "## Architecture > Phase 1: `_immediate_fire_task` Decomposition" — three helpers to extract
- "## Architecture > Phase 2: `_dispatch` Decomposition" — one helper to extract
- "## Architecture > Phase 3: Predicate Builder Deduplication" — shared `build_change_preds` function
- "## Edge Cases" — behavioral preservation, closure captures, changed=False warning, hold_preds gating
- "## Alternatives Considered" — why timer helpers are not unified

## Convention Examples
None — no convention examples captured during discovery.
