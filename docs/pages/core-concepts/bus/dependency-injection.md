# Dependency Injection

Hassette's dependency injection system extracts typed data from events and passes it directly to handler parameters. Handlers declare what they need via type annotations; Hassette resolves the rest.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/quick_example.py"
```

`D.StateNew[states.LightState]` extracts the new state and converts it to a typed `LightState`. `D.EntityId` extracts the entity ID as a string. The handler receives clean data with no event parsing.

All annotations live in `hassette.dependencies`, available as `D` from the top-level import: `from hassette import D`.

## Annotation Reference

### State Extractors

Extract typed state objects from state change events. `T` is any state class from `hassette.models.states`.

| Annotation | Returns | If missing |
|---|---|---|
| `D.StateNew[T]` | `T` | Handler not called |
| `D.StateOld[T]` | `T` | Handler not called |
| `D.MaybeStateNew[T]` | `T \| None` | `None` |
| `D.MaybeStateOld[T]` | `T \| None` | `None` |

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/state_object_extractors.py"
```

When a required state is missing, Hassette skips the handler invocation — the exception is caught during resolution, not inside the handler. `MaybeStateOld` is useful for the first event after an entity appears, where there is no previous state.

### Identity Extractors

Extract entity IDs and domains from events.

| Annotation | Returns | If missing |
|---|---|---|
| `D.EntityId` | `str` | Handler not called |
| `D.MaybeEntityId` | `str \| MISSING_VALUE` | Falsy sentinel |
| `D.Domain` | `str` | Handler not called |
| `D.MaybeDomain` | `str \| MISSING_VALUE` | Falsy sentinel |

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/identity_extractors.py"
```

`MISSING_VALUE` is a falsy sentinel. Test with `if entity_id:` rather than `isinstance` checks.

### Other Extractors

| Annotation | Returns | Use case |
|---|---|---|
| `D.EventData[T]` | `T` | Typed payload from [`Bus.emit`](../apps/index.md#broadcasting-events-between-apps) broadcast events |
| `D.EventContext` | `HassContext` | Home Assistant event context (user ID, parent/origin IDs) |
| `D.TypedStateChangeEvent[T]` | `TypedStateChangeEvent[T]` | Full event object with typed states |

`EventData[T]` pairs with `Bus.emit`. The sender emits a dataclass; the receiver declares the type:

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/event_data_extractor.py"
```

## Combining Annotations

Handlers accept multiple DI parameters. Hassette resolves each independently.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/multiple_dependencies.py"
```

## Union Types

State extractors accept union types for handlers that cover multiple entity domains.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/union_types.py"
```

The [State Registry](../states/state-registry.md) determines the correct state class based on the entity's domain.

## Custom Keyword Arguments

DI composes with custom `kwargs` passed at registration time. DI-annotated parameters are resolved from the event; remaining keyword arguments pass through unchanged.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/mixing_kwargs.py"
```

## Handler Signature Restrictions

DI handlers cannot use positional-only parameters (before `/`) or `*args`. Regular parameters and `**kwargs` work fine. All DI parameters require type annotations — Hassette uses the annotation to determine what to extract.

## See Also

- [Custom Extractors](custom-extractors.md) — writing custom extractors, accessors, `AnnotationDetails`, and automatic type conversion
- [Writing Handlers](handlers.md) — raw event and typed event patterns, handler error behavior
- [State Registry](../states/state-registry.md) — domain-to-model mapping
- [Type Registry](../states/type-registry.md) — automatic type conversion
