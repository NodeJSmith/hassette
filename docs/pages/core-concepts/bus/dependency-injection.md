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
| `D.EventData[T]` | `T` | Handler skipped | Typed payload from `Bus.emit` broadcast events, or a custom Home Assistant event's data |
| `D.MessageData[T]` | `T` | Handler skipped | A hass-hassette message's `data`, used with [`on_hassette_message`](methods.md#on_hassette_messagemessage) |
| `D.EventContext` | `HassContext` | Handler skipped | Home Assistant event context (context ID, parent ID, user ID) |
| `D.TypedStateChangeEvent[T]` | `TypedStateChangeEvent[T]` | Always present | Full event with both old and new states typed |

`D.EventData[T]` pairs with [`Bus.emit`](handlers.md#cross-app-communication) for cross-app communication. One app sends a typed payload, and other apps subscribe to receive it. `self.bus.emit(topic, data)` publishes `data` on `topic`. This app emits a `SensorAlert` dataclass when the freezer temperature rises above -10:

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/event_data_extractor.py:sender"
```

The receiving app subscribes to the same topic with `on()`. Its handler annotates the parameter with the payload type:

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/event_data_extractor.py:receiver"
```

Both apps read `ALERT_TOPIC` and `SensorAlert`, so sender and receiver stay in sync. Apps in separate files import both from a [shared module](handlers.md#cross-app-communication).

`D.EventData[T]` also reads custom Home Assistant events, the ones a script or automation fires with an `event:` action. The event's data arrives as JSON, so Hassette validates it into `T` when `T` is a pydantic model or a dataclass. This script fires a `doorbell_pressed` event:

```yaml
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/custom_event_fire.yaml"
```

Hassette publishes each Home Assistant event on the topic `hass.event.<event_type>`, so this one arrives on `hass.event.doorbell_pressed`. The handler receives its data as a `DoorbellPressed`:

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/custom_event_data.py"
```

A converter registered for `dict` to that type in the [type registry](../states/conversion.md#value-conversion) runs instead of this validation. Validation is pydantic's lax mode, so a string `"2"` becomes `2` for an `int` field. Data that fails validation skips the handler, and the logged error names each failing field.

Keys the model doesn't declare are ignored by default, so a misspelled key on a field with a default validates without complaint. `extra="forbid"` in the model's `model_config`, as above, rejects undeclared keys instead. A dataclass gets the same check from `__pydantic_config__ = ConfigDict(extra="forbid")`.

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

Hassette tries each member of the union in order and uses the first one that validates against the entity's domain. See [State Conversion](../states/conversion.md#union-type-support) for details.

## Custom Keyword Arguments

DI composes with `kwargs=` passed at registration. DI-annotated parameters resolve from the event; remaining keyword arguments pass through unchanged from the registration call.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/mixing_kwargs.py"
```

## Handler Signature Restrictions

Bus handlers do not support positional-only parameters (those before `/`) or `*args`, whether or not they use a `D.*` annotation. Registration raises `DependencyInjectionError` for either. Regular parameters and `**kwargs` are both valid. Every DI parameter requires a type annotation. Hassette uses the annotation to determine what to extract.

String annotations, including those from `from __future__ import annotations`, resolve at registration against the module that defines the handler. This holds for handlers wrapped by a decorator, built with `functools.partial`, or written as callable objects. Every annotation must resolve then, including the return annotation. A name imported only under `TYPE_CHECKING` raises `TypeError` at registration, so import it at runtime instead.

Not all `D.*` annotations work with every subscription method. [Subscription Methods](methods.md) lists the compatible annotations for each method.

## See Also

- [Custom Extractors](custom-extractors.md). Writing extractors, accessors, [`AnnotationDetails`][hassette.di.AnnotationDetails], and automatic type conversion.
- [Writing Handlers](handlers.md). Handler signature patterns.
- [Subscription Methods](methods.md). Which `D.*` annotations each method supports.
- [State Conversion](../states/conversion.md). Domain-to-model mapping and automatic type conversion.
