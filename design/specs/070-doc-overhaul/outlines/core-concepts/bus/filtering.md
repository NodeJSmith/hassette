# Bus — Filtering & Predicates

**Status:** Exists (255 lines), needs restructuring — most predicate/condition content is state-change-specific and may partially move to States/Subscribing
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: How Filtering Works
Overview: predicates test events, conditions test values. Predicates compose with `AllOf` and `AnyOf`.

### H2: Filtering State Changes
**Note:** Heavy overlap with States/Subscribing page. Decision: States/Subscribing covers the common state-change patterns (entity patterns, `changed` param, `changed_to`, `changed_from`, state-specific predicates). This page covers the general filtering mechanism and non-state-change filtering.

Content that stays here:
- How predicates compose (`AllOf`, `AnyOf`)
- General event filtering concept

### H2: Filtering Service Calls
Dictionary filtering and predicate filtering for `on_call_service`.

### H2: Advanced Topic Subscriptions
`on()` with custom topic strings and predicates.

### H2: Full Reference
→ Predicate, Condition & Accessor Reference page (`bus/predicate-reference.md`) for the complete P/C/A lookup tables.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `filtering_simple_start.py` | Move → States/Subscribing | State-change-specific |
| `filtering_simple_stop.py` | Move → States/Subscribing | State-change-specific |
| `filtering_predicate_lambda.py` | Keep | General predicate example |
| `filtering_predicate_isin.py` | Keep | Collection predicate |
| `filtering_combined_and.py` | Keep | Predicate composition |
| `filtering_combined_or.py` | Keep | Predicate composition |
| `filtering_service_literal.py` | Keep | Service call filtering |
| `filtering_service_callable.py` | Keep | Service call filtering |
| `filtering_service_predicates.py` | Keep | Service predicate |
| `filtering_service_presence.py` | Keep | Service presence check |
| `filtering_service_matches.py` | Keep | ServiceMatches predicate |
| `filtering_state_from_to.py` | Move → States/Subscribing | State-change-specific |
| `filtering_increased_decreased.py` | Move → States/Subscribing | State-change-specific |
| `filtering_advanced_topics.py` | Keep | Advanced topic subscription |
| `changed_false.py` | Move → States/Subscribing | State-change-specific |
| `custom_accessors.py` | Move | → Custom Extractors page |

## Cross-Links

- **Links to:** Predicate Reference (P/C/A tables), States/Subscribing (state-specific patterns), Custom Extractors (accessors), Handlers
- **Linked from:** Bus overview, States/Subscribing
