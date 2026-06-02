# Dependency Injection

**Status:** Rewrite from blank
**Voice mode:** Reference — tables-first, terse, system-as-subject
**Page type:** Reference (with concept intro)
**Reader's job:** Find the right `D.*` annotation for the data they need from an event.

The existing page is well-structured for its reference job: quick example, then annotation tables grouped by category, then composition patterns. The reader lands here from the Handlers page or from a recipe, looking up "which annotation gives me X?" The tables-first approach is correct.

## What was cut (and where it goes)

Nothing cut. The previous outline was already rewritten as an exemplar and is complete. The JTBD metadata is added, and one structural note below.

## Outline

### H2: (Opening)
One quick example showing a handler with `D.StateNew[T]` and `D.EntityId`. One sentence: "all annotations live in `hassette.dependencies`, available as `D`."

### H2: Annotation Reference
Three tables, each with annotation, return type, and missing-value behavior:
#### H3: State Extractors
`D.StateNew[T]`, `D.StateOld[T]`, `D.MaybeStateNew[T]`, `D.MaybeStateOld[T]`. Snippet showing temperature delta calculation.

#### H3: Identity Extractors
`D.EntityId`, `D.MaybeEntityId`, `D.Domain`, `D.MaybeDomain`. Snippet showing multi-entity routing.

#### H3: Other Extractors
`D.EventData[T]`, `D.EventContext`, `D.TypedStateChangeEvent[T]`. Snippet showing `Bus.emit` usage with `EventData`.

### H2: Combining Annotations
Multiple DI parameters in one handler. Snippet.

### H2: Union Types
State extractors with union types for multi-domain handlers. Snippet. Link to State Registry.

### H2: Custom Keyword Arguments
DI composes with `kwargs=` at registration. Snippet.

### H2: Handler Signature Restrictions
No positional-only params, no `*args`. All DI params need annotations.

### H2: See Also
Custom Extractors, Handlers, State Registry, Type Registry.

## Snippet Inventory

All snippets written and tested (exemplar):
| Snippet | Decision | Notes |
|---|---|---|
| `dependency-injection/quick_example.py` | Keep | Opening example |
| `dependency-injection/state_object_extractors.py` | Keep | Temperature delta |
| `dependency-injection/identity_extractors.py` | Keep | Multi-entity routing |
| `dependency-injection/event_data_extractor.py` | Keep | `Bus.emit` + `EventData` |
| `dependency-injection/multiple_dependencies.py` | Keep | Combining annotations |
| `dependency-injection/union_types.py` | Keep | Union state types |
| `dependency-injection/mixing_kwargs.py` | Keep | DI + custom kwargs |

No new snippets needed.

## Cross-Links

- **Links to:** Custom Extractors, Handlers, State Registry, Type Registry
- **Linked from:** Bus overview, First Automation, Recipes
