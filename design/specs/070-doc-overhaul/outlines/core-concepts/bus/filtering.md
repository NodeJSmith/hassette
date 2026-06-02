# Filtering & Predicates

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Control which events trigger a handler, beyond simple entity matching.

The existing page is organized by API surface (predicates, then conditions, then accessors), mixed with state-change-specific patterns. A reader lands here because their handler fires too often or on the wrong events. They need to learn: what filtering tools exist, and which one solves their problem. Order by the reader's decision flow: simplest filtering first (built-in parameters), then composition, then service-call filtering, then raw topic filtering.

## What was cut (and where it goes)

- **State-change-specific filtering** (`changed_to`, `changed_from`, `changed=False`, `P.StateFrom`/`P.StateTo`, `C.Increased`/`C.Decreased`) — stays on this page. The previous outline proposed moving these to a States/Subscribing page, but that page doesn't exist yet and these patterns are filtering patterns. Readers looking for "how do I filter state changes" will look here. Keep them, but order them as the simplest entry point.
- **Complete P/C/A reference tables** — moved to the Predicate Reference page. This page teaches the concepts and common patterns; the reference page is for lookup.
- **Custom accessors (`A`)** — brief mention with link to Custom Extractors page. The previous page had a full section that duplicated content.

## Outline

### H2: Filtering State Changes
The most common case. Three built-in parameters that handle 80% of state-change filtering without predicates:
- `changed_to` — fire only when the new state matches a value, callable, or condition
- `changed_from` — fire only when the old state matches
- `changed=False` — fire on attribute-only changes too (default is state-value-only)

Snippets: `filtering_simple_start.py`, `filtering_simple_stop.py`, `changed_false.py`.

### H2: Conditions
Conditions are the value-level matchers passed to `changed_to`, `changed_from`, or predicates. Show the most common ones inline:
- `C.IsIn(["on", "home"])` — match from a set
- `C.Comparison(">", 75)` — numeric comparison
- `C.Increased()` / `C.Decreased()` — numeric direction (used with `changed=` or `P.StateComparison`)

Snippets: `filtering_predicate_isin.py`, `filtering_predicate_lambda.py`, `filtering_increased_decreased.py`.

Link to Predicate Reference for the full conditions table.

### H2: Predicates and the `where` Parameter
When built-in parameters aren't enough, `where=` accepts a list of predicates (ANDed). Introduce `P.StateFrom`, `P.StateTo`, `P.AllOf`, `P.AnyOf`.

Snippets: `filtering_state_from_to.py`, `filtering_combined_and.py`, `filtering_combined_or.py`.

### H2: Filtering Service Calls
`on_call_service` filtering with dict-based matching (literal, presence, callable) and predicate-based (`P.ServiceMatches`, `P.ServiceDataWhere`).

Snippets: `filtering_service_literal.py`, `filtering_service_presence.py`, `filtering_service_callable.py`, `filtering_service_predicates.py`, `filtering_service_matches.py`.

### H2: Raw Topic Subscriptions
`on()` with custom topic strings and `where=` predicates. For event types not covered by helper methods.

Snippet: `filtering_advanced_topics.py`.

### H2: Custom Accessors
One paragraph: `A` (accessors) point predicates at non-standard fields. Brief example of `P.ValueIs` with a custom accessor. Link to Custom Extractors page for the full guide.

Snippet: `custom_accessors.py` (brief inline).

### H2: Full Reference
Link to Predicate Reference page for the complete P/C/A lookup tables.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `filtering_simple_start.py` | Keep | `changed_to` basic |
| `filtering_simple_stop.py` | Keep | `changed_from` basic |
| `changed_false.py` | Keep | `changed=False` |
| `filtering_predicate_isin.py` | Keep | Collection condition |
| `filtering_predicate_lambda.py` | Keep | Comparison condition |
| `filtering_increased_decreased.py` | Keep | Numeric direction |
| `filtering_state_from_to.py` | Keep | `P.StateFrom`/`P.StateTo` |
| `filtering_combined_and.py` | Keep | Predicate composition AND |
| `filtering_combined_or.py` | Keep | Predicate composition OR |
| `filtering_service_literal.py` | Keep | Service dict filtering |
| `filtering_service_presence.py` | Keep | Service presence check |
| `filtering_service_callable.py` | Keep | Service callable filter |
| `filtering_service_predicates.py` | Keep | `P.ServiceDataWhere` |
| `filtering_service_matches.py` | Keep | `P.ServiceMatches` |
| `filtering_advanced_topics.py` | Keep | Raw topic subscription |
| `custom_accessors.py` | Keep | Brief accessor example |

No new snippets needed.

## Cross-Links

- **Links to:** Predicate Reference (full tables), Custom Extractors (accessors in depth), Handlers, DI
- **Linked from:** Bus overview, Recipes
