# Predicate, Condition & Accessor Reference

**Status:** Rewrite from blank
**Voice mode:** Reference — tabular, terse, system-as-subject
**Page type:** Reference
**Reader's job:** Look up the exact predicate, condition, or accessor for a filtering task.

This is a pure lookup page. The reader arrives from the Filtering page (or from a recipe) knowing they need a predicate or condition but unsure of the exact name or signature. Every entry needs: name, one-line description, and which event types it works with.

## What was cut (and where it goes)

- **Usage examples and explanations** — these live on the Filtering page. This page has no prose beyond one-sentence descriptions per entry. If a reader needs to learn how predicates work, they go to Filtering first.
- **`StateFromTo`** — does NOT exist. Use separate `P.StateFrom` + `P.StateTo`. Note this explicitly.
- **`C.InRange`** — does NOT exist. Use `C.Comparison` for range checks. Note this explicitly.

## Outline

### H2: Predicates (`P`)
Tables grouped by purpose:

#### H3: Logic Combinators
`P.AllOf`, `P.AnyOf`, `P.Not`, `P.Guard`. Works with: any event.

#### H3: Value / Field Matching
`P.ValueIs`, `P.DidChange`, `P.IsPresent`, `P.IsMissing`. Works with: any event.

#### H3: Entity / Domain / Service Matching
`P.DomainMatches`, `P.EntityMatches`, `P.ServiceMatches`, `P.ServiceDataWhere` (note `from_kwargs` classmethod and `auto_glob` param). Works with: `HassEvent` / `CallServiceEvent`.

#### H3: State Change Predicates
`P.StateFrom`, `P.StateTo`, `P.StateComparison`, `P.StateDidChange`, `P.AttrFrom`, `P.AttrTo`, `P.AttrComparison`, `P.AttrDidChange`. Works with: `RawStateChangeEvent`.

### H2: Conditions (`C`)
Tables grouped by purpose:

#### H3: String Matching
`C.Glob`, `C.StartsWith`, `C.EndsWith`, `C.Contains`, `C.Regex`.

#### H3: Collection Membership
`C.IsIn`, `C.NotIn`, `C.Intersects`, `C.NotIntersects`, `C.IsOrContains`.

#### H3: None / Missing Checks
`C.IsNone`, `C.IsNotNone`, `C.Present`, `C.Missing`.

#### H3: Numeric Comparison
`C.Comparison`, `C.Increased`, `C.Decreased`.

### H2: Accessors (`A`)
Tables grouped by data source:

#### H3: State Value
`get_state_value_new`, `get_state_value_old`, `get_state_value_old_new`.

#### H3: State Object
`get_state_object_old`, `get_state_object_new`.

#### H3: Attribute
`get_attr_old`, `get_attr_new`, `get_attr_old_new`, `get_attrs_old`, `get_attrs_new`, `get_all_attrs_old`, `get_all_attrs_new`.

#### H3: Identity
`get_domain`, `get_entity_id`, `get_context`.

#### H3: Service
`get_service`, `get_service_data`, `get_service_data_key`.

#### H3: Other
`get_path`, `get_all_changes`.

One paragraph at end: how accessors plug into predicates via the `source=` parameter.

## Snippet Inventory

No snippets. Pure reference tables. Usage examples live on Filtering and States/Subscribing pages.

## Cross-Links

- **Links to:** Filtering (concepts and examples), Custom Extractors (writing custom accessors)
- **Linked from:** Filtering, Handlers, Recipes
