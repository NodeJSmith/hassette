---
task_id: "T03"
title: "Extract shared predicate builder for state/attribute change"
status: "planned"
depends_on: []
implements: ["FR#3", "AC#3", "AC#4", "AC#5"]
---

## Summary
Extract the duplicated predicate-building logic from `on_state_change` and `on_attribute_change` in `bus.py` into a shared module-level function `build_change_preds`. After extraction, each subscription builder should be under 40 lines. All existing tests must pass without modification.

## Prompt
Edit `src/hassette/bus/bus.py` to extract a shared predicate builder:

1. **`build_change_preds(entity_id, *, mode, attr, changed, changed_from, changed_to)`** — module-level function. Returns `tuple[list[Predicate], list[Predicate]]` (preds, hold_preds).

   Signature:
   ```python
   def build_change_preds(
       entity_id: str,
       *,
       mode: Literal["state", "attribute"],
       attr: str | None = None,
       changed: bool | ComparisonCondition,
       changed_from: Any,
       changed_to: Any,
   ) -> tuple[list[Predicate], list[Predicate]]:
   ```

   The function maps `mode` to the correct predicate classes:
   - `mode="state"`: `P.StateDidChange()`, `P.StateComparison(condition=...)`, `P.StateFrom(condition=...)`, `P.StateTo(condition=...)`
   - `mode="attribute"`: `P.AttrDidChange(attr)`, `P.AttrComparison(attr, condition=...)`, `P.AttrFrom(attr, condition=...)`, `P.AttrTo(attr, condition=...)`

   Both modes start with `P.EntityMatches(entity_id)` in both `preds` and `hold_preds`. The `changed_to` predicate is added to both `preds` and `hold_preds` when present.

2. Update `on_state_change` (lines 459–533) to call `build_change_preds(entity_id, mode="state", changed=changed, changed_from=changed_from, changed_to=changed_to)` and pass the results to `_subscribe`.

3. Update `on_attribute_change` (lines 535–625) to call `build_change_preds(entity_id, mode="attribute", attr=attr, changed=changed, changed_from=changed_from, changed_to=changed_to)` and pass the results to `_subscribe`.

**Important:** The `changed=False` warning log in `on_attribute_change` (lines 592–600) must stay in `on_attribute_change` — it is method-specific behavior, not predicate logic. Call `build_change_preds` only after that check.

**Important:** Hold predicates gating (`duration is not None` → pass `hold_preds`, else pass `None`) stays in the calling methods. `build_change_preds` always returns hold_preds; the caller decides whether to use them.

Verify the extraction preserves exact behavior by running:
```
timeout 300 uv run pytest tests/unit/bus/ tests/integration/test_bus.py tests/integration/test_bus_immediate.py tests/integration/test_bus_duration.py -n 2
```

## Focus
- `on_state_change` predicate block: lines 502–516. `on_attribute_change` predicate block: lines 580–607.
- The two blocks are identical except for predicate class names and the `attr` parameter.
- `NOT_PROVIDED` sentinel is used for `changed_from`/`changed_to` defaults — the builder must handle `is not NOT_PROVIDED` checks, not `is not None`.
- Glob validation (reject globs with immediate/duration) is at lines 492–500 (state) and 570–578 (attr). These stay in the calling methods — they are NOT predicate logic.
- No underscore prefix on `build_change_preds`.
- Place the function above the `Bus` class definition in `bus.py`, after imports.

## Verify
- [ ] FR#3: A single `build_change_preds` function serves both `on_state_change` and `on_attribute_change`, parameterized by `mode`
- [ ] AC#3: `on_state_change` and `on_attribute_change` are each under 40 lines, sharing the single filtering function
- [ ] AC#4: All existing bus unit and integration tests pass without modification
- [ ] AC#5: No new parameters, return types, or public API changes are introduced
