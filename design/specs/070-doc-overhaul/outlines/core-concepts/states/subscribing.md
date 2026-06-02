# Subscribing to State Changes

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** React to entity state changes in a handler — subscribe, filter, and receive typed state data.

## What was cut (and where it goes)

- **Full predicate/condition reference** — stays on Bus Filtering page. This page shows predicates in context (state-change-specific examples) and links to the complete reference.
- **`AllOf`/`AnyOf` composition** — kept but brief. One example combining two predicates for a state transition. The full composition API is on the Bus Filtering page.
- **Common Parameters exhaustive list** — replaced with a focused table of the parameters a reader actually needs when setting up a state subscription. The full `**opts: Unpack[Options]` reference belongs on the Bus page or API reference.

## Outline

### (Opening)
The Bus delivers state change events to handlers. `on_state_change` and `on_attribute_change` are the two subscription methods for reacting to entity state. Both return a `Subscription` handle.

### H2: Basic Subscription
`on_state_change(entity_id, handler=..., name=...)` — simplest case. Entity ID patterns: exact match, glob (`"light.*"`), domain wildcard. `name=` is required (raises `ListenerNameRequiredError` if omitted).

### H2: Receiving Typed State
How the handler gets state data. DI annotations specific to state changes:

- `D.StateNew[T]` / `D.StateOld[T]` — new/old state as a typed model
- `D.MaybeStateNew[T]` / `D.MaybeStateOld[T]` — `None`-safe variants
- `D.TypedStateChangeEvent[T]` — the full event with both states

Link to DI page for the complete annotation reference.

### H2: Filtering State Changes
Ordered from simplest to most powerful:

#### H3: `changed_to` and `changed_from`
Simple value matching — fire only when the state transitions to or from a specific value.

#### H3: The `changed` Parameter
Type is `bool | ComparisonCondition`. `True` (default) fires on any change. `False` fires on every event even without a change. A `ComparisonCondition` like `C.Increased()` compares old vs new.

#### H3: Predicates
`P.StateFrom`, `P.StateTo` for tracking transitions. Combine with `AllOf` for from-to pairs (no `P.StateFromTo`).

#### H3: Numeric Conditions
`C.Increased`, `C.Decreased` for monitoring numeric value changes.

### H2: Attribute Changes
`on_attribute_change(entity_id, attr, ...)` — `attr` is a required second positional argument. Attribute-specific predicates: `P.AttrFrom`, `P.AttrTo`, `P.AttrDidChange`, `P.AttrComparison`.

### H2: Subscription Options
Focused table of the parameters most relevant to state subscriptions:

| Parameter | Purpose |
|---|---|
| `name=` | Required. Identifies the listener in logs and DB. |
| `duration=` | Fire only after the state has been in the new value for N seconds. |
| `immediate=` | Fire immediately on first match, then apply duration. Raises `ValueError` with glob patterns. |
| `debounce=` | Wait N seconds of quiet before firing. |
| `throttle=` | Fire at most once per N seconds. Mutually exclusive with debounce. |
| `once=` | Unsubscribe after the first fire. |
| `on_error=` | Error handler callback. |

Brief note: `timeout=`, `timeout_disabled=` also available via `**opts`.

### H2: See Also
Bus overview, Bus Filtering (complete predicate/condition reference), DI page (full annotation reference), States overview.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| New: basic subscription | Create | H2: Basic Subscription — `on_state_change` with entity ID and handler |
| New: typed state DI | Create | H2: Receiving Typed State — handler with `D.StateNew[SensorState]` |
| `filtering_simple_start.py` | Move from `bus/snippets/filtering/` | H3: changed_to |
| `filtering_simple_stop.py` | Move from `bus/snippets/filtering/` | H3: changed_to |
| `filtering_state_from_to.py` | Move from `bus/snippets/filtering/` | H3: Predicates |
| `filtering_increased_decreased.py` | Move from `bus/snippets/filtering/` | H3: Numeric Conditions |
| `changed_false.py` | Move from `bus/snippets/filtering/` | H3: changed parameter |
| New: attribute change | Create | H2: Attribute Changes — `on_attribute_change` with predicate |
| New: duration example | Create | Subscription Options — `duration=` hold pattern |

## Cross-Links

- **Links to:** Bus overview, Bus Filtering (complete reference), DI page, States overview
- **Linked from:** Bus overview, States overview, Recipes
