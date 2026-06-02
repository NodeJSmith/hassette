# Bus — Predicate, Condition & Accessor Reference

**Status:** New page (split from bus/filtering.md "Complete Reference" section)
**Voice mode:** Reference — tabular, terse, system-as-subject

## Outline

### H2: Predicates (`P`)
Full reference table. Include: `AllOf`, `AnyOf`, `Not`, `Guard`, `StateFrom`, `StateTo`, `StateDidChange`, `StateComparison`, `AttrFrom`, `AttrTo`, `AttrDidChange`, `AttrComparison`, `DidChange`, `IsPresent`, `IsMissing`, `ValueIs`, `EntityMatches`, `DomainMatches`, `ServiceMatches`, `ServiceDataWhere` (with `from_kwargs` classmethod and `auto_glob` param). Note: `StateFromTo` does NOT exist — use separate `StateFrom` + `StateTo`.

### H2: Conditions (`C`)
Full reference table. Include: `Increased`, `Decreased`, `Comparison` (raw operator), `IsNone`, `IsNotNone`, `Present`, `Missing` (sentinel-based, distinct from `IsNone`), `IsIn`, `NotIn`, `Intersects`, `NotIntersects`, `IsOrContains`, `StartsWith`, `EndsWith`, `Contains`, `Regex`, `Glob`. Note: `InRange` does NOT exist — use `Comparison` for range checks.

### H2: Accessors (`A`)
Full reference table grouped by category: state value (`get_state_value_new`, `get_state_value_old`, `get_state_value_old_new`), state object (`get_state_object_old`, `get_state_object_new`), attribute (`get_attr_old`, `get_attr_new`, `get_attr_old_new`, `get_attrs_old`, `get_attrs_new`, `get_all_attrs_old`, `get_all_attrs_new`), identity (`get_domain`, `get_entity_id`, `get_context`), service (`get_service`, `get_service_data`, `get_service_data_key`), path (`get_path`), diff (`get_all_changes`). How accessors plug into predicates via the `source=` parameter.

## Snippet Inventory

No snippets — pure reference tables. Usage examples live on bus/filtering.md and states/subscribing.md.

## Cross-Links

- **Links to:** Bus/Filtering (concept), States/Subscribing (state-change patterns), Custom Extractors
- **Linked from:** Bus/Filtering, States/Subscribing, Bus/Handlers, Recipes
