# Bus — Filtering & Predicates

**Status:** Exists (255 lines), needs restructuring — most predicate/condition content is state-change-specific and may partially move to States/Subscribing
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: How Filtering Works
Overview: predicates test events, conditions test values. Predicates compose with `&` and `|`.

### H2: Filtering State Changes
**Note:** Heavy overlap with States/Subscribing page. Decision: States/Subscribing covers the common state-change patterns (entity patterns, `changed` param, `changed_to`, `changed_from`, state-specific predicates). This page covers the general filtering mechanism and non-state-change filtering.

Content that stays here:
- How predicates compose (`&`, `|`)
- General event filtering concept

### H2: Filtering Service Calls
Dictionary filtering and predicate filtering for `on_call_service`.

### H2: Advanced Topic Subscriptions
`on()` with custom topic strings and predicates.

### H2: Complete Reference
#### H3: Predicates (`P`)
Full reference table: logic combinators, value/field matching, entity/domain/service matching, state change predicates.
#### H3: Conditions (`C`)
Full reference table: string matching, collection membership, none/missing checks, numeric comparison.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `filtering_simple_start.py` | Review | May move to States/Subscribing |
| `filtering_simple_stop.py` | Review | May move to States/Subscribing |
| `filtering_predicate_lambda.py` | Keep | General predicate example |
| `filtering_predicate_isin.py` | Keep | Collection predicate |
| `filtering_combined_and.py` | Keep | Predicate composition |
| `filtering_combined_or.py` | Keep | Predicate composition |
| `filtering_service_literal.py` | Keep | Service call filtering |
| `filtering_service_callable.py` | Keep | Service call filtering |
| `filtering_service_predicates.py` | Keep | Service predicate |
| `filtering_service_presence.py` | Keep | Service presence check |
| `filtering_service_matches.py` | Keep | ServiceMatches predicate |
| `filtering_state_from_to.py` | Review | May move to States/Subscribing |
| `filtering_increased_decreased.py` | Review | May move to States/Subscribing |
| `filtering_advanced_topics.py` | Keep | Advanced topic subscription |
| `changed_false.py` | Review | May move to States/Subscribing |
| `custom_accessors.py` | Move | → Custom Extractors page |

## Cross-Links

- **Links to:** States/Subscribing (state-specific patterns), Custom Extractors (accessors), Handlers
- **Linked from:** Bus overview, States/Subscribing
