# Dependency Injection

Hassette's dependency injection system extracts typed data from events and passes it to handler parameters. Like FastAPI's `Depends()`, Hassette resolves handler parameters at call time — but instead of a dependency function, type annotations from the `D` module declare what to extract. All annotations live in `hassette.event_handling.dependencies`, imported as `D`: `from hassette import D`.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/quick_example.py"
```

`D.StateNew[states.LightState]` extracts the new state and converts it to a typed [`LightState`][hassette.models.states.light.LightState]. `D.EntityId` extracts the entity ID as a string. The handler receives clean data with no event parsing.

## Annotation Reference

### State Extractors

State extractors resolve typed state objects from state change events. `T` is any state class from `hassette.models.states` — a full list is at [State Conversion](../states/conversion.md).

| Annotation | Returns | If missing |
|---|---|---|
| `D.StateNew[T]` | `T` | Handler skipped |
| `D.StateOld[T]` | `T` | Handler skipped |
| `D.MaybeStateNew[T]` | `T \| None` | `None` |
| `D.MaybeStateOld[T]` | `T \| None` | `None` |

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/state_object_extractors.py"
```

When a required extractor finds no value, Hassette skips the handler invocation and logs the failure at ERROR level — no exception propagates to your app. `MaybeStateOld` returns `None` on the first event for a new entity with no previous state (typically on startup or when an entity first appears).

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

[`MISSING_VALUE`][hassette.const.MISSING_VALUE] is a falsy sentinel from `hassette.const` indicating a field does not exist on the event. It is not `None` — `None` means the field exists with a null value. Testing with `if entity_id:` covers both the present and absent cases. `D.MaybeEntityId` is useful in generic handlers registered via `on()` where the event may not have an `entity_id` field.

### Other Extractors

| Annotation | Returns | If missing | Use case |
|---|---|---|---|
| `D.EventData[T]` | `T` | Handler skipped | Typed payload from `Bus.emit` broadcast events |
| `D.EventContext` | `HassContext` | Handler skipped | Home Assistant event context (user ID, parent/origin IDs) |
| `D.TypedStateChangeEvent[T]` | `TypedStateChangeEvent[T]` | Always present | Full event with both old and new states typed |

`D.EventData[T]` pairs with [`Bus.emit`](../apps/index.md) for cross-app communication — one app sends a typed payload, and other apps subscribe to receive it. The emitting app sends a dataclass; the receiving handler annotates its parameter with the same type:

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

Hassette determines the concrete state class from the entity's domain at dispatch time — see [State Conversion](../states/conversion.md) for details.

## Custom Keyword Arguments

DI composes with `kwargs=` passed at registration. DI-annotated parameters resolve from the event; remaining keyword arguments pass through unchanged from the registration call.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/mixing_kwargs.py"
```

## Handler Signature Restrictions

Any handler with at least one `D.*` annotation is a DI handler. DI handlers do not support positional-only parameters (those before `/`) or `*args`. Regular parameters and `**kwargs` are both valid. Every DI parameter requires a type annotation. Hassette uses the annotation to determine what to extract.

Not all `D.*` annotations work with every subscription method. [Subscription Methods](methods.md) lists the compatible annotations for each method.

## See Also

- [Custom Extractors](custom-extractors.md). Writing extractors, accessors, [`AnnotationDetails`][hassette.event_handling.dependencies.AnnotationDetails], and automatic type conversion.
- [Writing Handlers](handlers.md). Handler signature patterns.
- [Subscription Methods](methods.md). Which `D.*` annotations each method supports.
- [State Conversion](../states/conversion.md). Domain-to-model mapping and automatic type conversion.
