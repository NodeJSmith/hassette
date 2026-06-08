# Writing Event Handlers

A handler is an async method that runs when an event matches a subscription.
Hassette supports four handler patterns: no parameters, extracted data via
dependency injection, raw events, and typed events.

## Handler Patterns

### No data needed

A no-parameter handler fires as a side effect. Hassette passes no event data.
This pattern works with all [subscription methods](methods.md).

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_no_data.py"
```

### Extracted data (recommended)

[`D` annotations](dependency-injection.md) tell Hassette which fields to
extract from the event and pass as individual parameters. The handler receives
only the requested data, not the event object.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_extract_data.py"
```

[`D.StateNew[T]`](dependency-injection.md) delivers the new state converted
to type `T`. [`D.EntityId`](dependency-injection.md) delivers the entity ID
string.

The same pattern works with `on_call_service`. `D.EntityId` extracts the
entity the service call targeted.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_service_extract.py"
```

[`D`][hassette.event_handling.dependencies] is `hassette.event_handling.dependencies`, a module of type annotations
that tell Hassette what to extract from each event.
[`states`][hassette.models.states] is `hassette.models.states`, typed state
classes for each Home Assistant domain. The
[Dependency Injection](dependency-injection.md) page covers the full
annotation table, `D.StateOld`, `D.EventContext`, union types, and custom
extractors.

### Raw event

State change events arrive as
[`RawStateChangeEvent`][hassette.events.hass.hass.RawStateChangeEvent].
The state value lives at `event.payload.data.new_state.get("state")`.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_raw_event.py"
```

Raw topic subscriptions via `on()` deliver `Event[Any]` instead. The handler
receives the full event object with `event.topic` and `event.payload`.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_raw_topic.py"
```

### Typed state event

[`D.TypedStateChangeEvent[T]`][hassette.event_handling.dependencies] converts
a raw state change event into a typed version. The new and old state values
are attributes on the payload instead of raw dicts.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_typed_event.py"
```

This pattern works only with `on_state_change` and `on_attribute_change`.
Service call handlers use the [extracted data](#extracted-data-recommended)
pattern with [`D.EntityId`](dependency-injection.md) instead.

## Choosing a Pattern

`D` annotations are the default for most handlers. They deliver only the fields the handler needs. The signature stays readable, and Hassette handles parsing and type conversion.

Raw events deliver the full event structure, which suits event-forwarding or generic logging. Typed state events provide the same structure but with typed state objects instead of raw dicts.

No-parameter handlers work when the event itself does not matter. The subscription filters to the right entity and transition, so the handler just acts.

## Cross-app Communication

Apps can broadcast data to other apps through custom topics.
`Bus.emit(topic, data)` publishes a payload. Other apps subscribe to the same
topic with `on()`. [`D.EventData[T]`](dependency-injection.md) delivers the
payload pre-extracted and typed.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_cross_app.py:sender"
```

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_cross_app.py:receiver"
```

A frozen dataclass works well for `T`. Any type passed as `data` to `emit()`
can be received via `D.EventData[T]`.

## See Also

- [Subscription Methods](methods.md): method reference, parameters, error handling, registration
- [Dependency Injection](dependency-injection.md): full `D.*` annotation table, custom extractors
- [Filtering & Predicates](filtering.md): predicates, conditions, `where=` usage
