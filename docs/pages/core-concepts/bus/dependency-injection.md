# Dependency Injection

Hassette's dependency injection system extracts typed data from events and passes it to handler parameters. Handlers declare what they need via type annotations; Hassette resolves the values before each invocation.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/quick_example.py"
```

`D.StateNew[states.LightState]` extracts the new state and converts it to a typed `LightState`. `D.EntityId` extracts the entity ID as a string. The handler receives clean data with no event parsing.

All annotations live in `hassette.dependencies`, imported as `D`: `from hassette import D`.

## Annotation Reference

### State Extractors

State extractors resolve typed state objects from state change events. `T` is any state class from `hassette.models.states`.

| Annotation | Returns | If missing |
|---|---|---|
| `D.StateNew[T]` | `T` | Handler skipped |
| `D.StateOld[T]` | `T` | Handler skipped |
| `D.MaybeStateNew[T]` | `T \| None` | `None` |
| `D.MaybeStateOld[T]` | `T \| None` | `None` |

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/state_object_extractors.py"
```

When a required extractor finds no value, Hassette skips the handler invocation entirely. `MaybeStateOld` returns `None` on the first event for a new entity with no previous state.

### Identity Extractors

Identity extractors resolve entity IDs and domains from events.

| Annotation | Returns | If missing |
|---|---|---|
| `D.EntityId` | `str` | Handler skipped |
| `D.MaybeEntityId` | `str \| MISSING_VALUE` | Falsy sentinel |
| `D.Domain` | `str` | Handler skipped |
| `D.MaybeDomain` | `str \| MISSING_VALUE` | Falsy sentinel |

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/identity_extractors.py"
```

`MISSING_VALUE` is a falsy sentinel. Testing with `if entity_id:` covers both the present and absent cases.

### Other Extractors

| Annotation | Returns | If missing | Use case |
|---|---|---|---|
| `D.EventData[T]` | `T` | Handler skipped | Typed payload from `Bus.emit` broadcast events |
| `D.EventContext` | `HassContext` | `None` | Home Assistant event context (user ID, parent/origin IDs) |
| `D.TypedStateChangeEvent[T]` | `TypedStateChangeEvent[T]` | Always present | Full event with both old and new states typed |

`D.EventData[T]` pairs with [`Bus.emit`](../apps/index.md). The emitting app sends a dataclass; the receiving handler annotates its parameter with the same type:

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/event_data_extractor.py"
```

## Combining Annotations

Handlers accept multiple DI parameters. Hassette resolves each independently from the same event.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/multiple_dependencies.py"
```

## Union Types

State extractors accept union types for handlers that cover multiple entity domains.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/union_types.py"
```

The [State Registry](../states/state-registry.md) determines the concrete state class from the entity's domain at dispatch time.

## Custom Keyword Arguments

DI composes with `kwargs=` passed at registration. DI-annotated parameters resolve from the event; remaining keyword arguments pass through unchanged from the registration call.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/mixing_kwargs.py"
```

## Handler Signature Restrictions

DI handlers do not support positional-only parameters (those before `/`) or `*args`. Regular parameters and `**kwargs` are both valid. Every DI parameter requires a type annotation. Hassette uses the annotation to determine what to extract.

## See Also

- [Custom Extractors](custom-extractors.md). Writing extractors, accessors, `AnnotationDetails`, and automatic type conversion.
- [Writing Handlers](handlers.md). Raw event and typed event patterns, handler error behavior.
- [State Registry](../states/state-registry.md). Domain-to-model mapping.
- [Type Registry](../states/type-registry.md). Automatic type conversion.
