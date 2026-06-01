# States — Subscribing to State Changes

**Status:** Stub (3 lines), new content needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

Bridge page between Bus and States. Covers state-change-specific subscription patterns. Most predicates and conditions are designed for state changes — this is where they're shown in context.

### H2: Subscribing to State Changes
`on_state_change` and `on_attribute_change` — the two primary state subscription methods. Entity ID patterns (exact, glob, domain wildcard).

### H2: State-Specific DI Annotations
`D.StateNew[T]`, `D.StateOld[T]`, `D.MaybeStateNew[T]`, `D.MaybeStateOld[T]`, `D.TypedStateChangeEvent[T]` — shown in state-change context (links to DI page for full reference).

### H2: The `changed` Parameter
Type is `bool | ComparisonCondition`, not just bool. `True` (default), `False`, or a `ComparisonCondition` (e.g., `C.Increased()`) that compares old vs new values.

### H2: Matching State Values
#### H3: `changed_to` and `changed_from` — simple value matching
#### H3: Predicates for State Changes
`P.StateFrom`, `P.StateTo` — tracking transitions. (No `P.StateFromTo` — combine with `AllOf`.)
#### H3: Numeric Conditions
`C.Increased`, `C.Decreased` — monitoring numeric changes. (No `C.InRange` — use `C.Comparison` for range checks.)

### H2: Combining Predicates
`AllOf` and `AnyOf` composition. Examples specific to state-change scenarios.

### H2: Attribute Changes
`on_attribute_change(entity_id, attr, ...)` — `attr: str` is a required second positional argument. Monitors a specific attribute rather than the state string. Also has attribute-specific predicates: `P.AttrFrom`, `P.AttrTo`, `P.AttrDidChange`, `P.AttrComparison`.

### H2: Common Parameters
`name=` (**required** — omitting raises `ListenerNameRequiredError`), `duration=`, `immediate=` (raises `ValueError` with glob patterns), `on_error=`, `where=` (additional predicates), `once=`, `debounce=`, `throttle=` (mutually exclusive with debounce), `timeout=`, `timeout_disabled=`. Note: `timeout`/`timeout_disabled`/`once`/`debounce`/`throttle` are passed via `**opts: Unpack[Options]`.

### H2: See Also
→ Bus overview (general subscription), → Bus Filtering (service call filtering, complete predicate/condition reference), → DI page (full annotation reference)

## Snippet Inventory

Snippets moving from Bus/Filtering and new:
| Snippet | Status | Notes |
|---|---|---|
| `filtering_simple_start.py` | Move from filtering/ | `changed_to` example |
| `filtering_simple_stop.py` | Move from filtering/ | `changed_to` example |
| `filtering_state_from_to.py` | Move from filtering/ | State transition tracking |
| `filtering_increased_decreased.py` | Move from filtering/ | Numeric conditions |
| `changed_false.py` | Move from filtering/ | `changed=False` example |
| New: attribute change example | New | `on_attribute_change` with predicate |
| New: combined predicates for state | New | `AllOf`/`AnyOf` composition in state context |

## Cross-Links

- **Links to:** Bus overview, Bus Filtering (complete reference), DI page, States overview
- **Linked from:** Bus overview, States overview, Recipes
