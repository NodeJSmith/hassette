# Subscribing to State Changes

The [Bus](../bus/index.md) delivers `state_changed` events to handlers each time Home Assistant reports an entity update. `on_state_change` and `on_attribute_change` are the two subscription methods for reacting to entity state. Both are async and return a [`Subscription`][hassette.bus.listeners.Subscription] handle.

## Basic Subscription

`on_state_change` accepts an entity ID, a `handler=`, and a required `name=`. The `name=` parameter identifies the listener in logs and the telemetry database. Omitting it raises [`ListenerNameRequiredError`][hassette.exceptions.ListenerNameRequiredError] at registration time.

```python
--8<-- "pages/core-concepts/states/snippets/state_basic_subscribe.py"
```

Entity IDs accept glob patterns. `"light.*"` matches any entity in the `light` domain. `"sensor.bedroom_*"` matches any sensor with a `bedroom_` prefix. Glob patterns work the same as on the [Bus](../bus/index.md#matching-multiple-entities) overview.

## Receiving Typed State

[Dependency injection](../bus/dependency-injection.md) extracts typed state objects from events and passes them as handler parameters. The handler receives converted objects directly, without event dictionary parsing.

```python
--8<-- "pages/core-concepts/states/snippets/state_typed_di.py"
```

Four annotations extract typed state from events. `T` is any class from [`hassette.models.states`](index.md), imported as `states`.

| Annotation | Returns | When the value is absent |
|---|---|---|
| `D.StateNew[T]` | `T` | Handler is skipped |
| `D.StateOld[T]` | `T` | Handler is skipped |
| `D.MaybeStateNew[T]` | `T \| None` | `None` |
| `D.MaybeStateOld[T]` | `T \| None` | `None` |

`D.StateOld` is absent on the very first event for an entity, when no previous state exists. `D.MaybeStateOld` returns `None` in that case rather than skipping the handler.

`D.TypedStateChangeEvent[T]` delivers the full event with both old and new states typed. The [Dependency Injection](../bus/dependency-injection.md) page covers the full annotation reference.

## Filtering State Changes

### `changed_to` and `changed_from`

`changed_to` restricts the handler to events where the new state matches a value. `changed_from` restricts to events where the previous state matches.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_simple_start.py"
```

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_simple_stop.py"
```

Both parameters accept a plain value, a callable, or a condition object from [`C`](../bus/filtering.md#conditions).

### The `changed` Parameter

By default, `on_state_change` fires only when the main state value changes. `changed=False` removes that restriction.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/changed_false.py:changed_false"
```

A light remaining `"on"` while its brightness shifts produces no event by default. With `changed=False`, that attribute update reaches the handler.

`changed` also accepts a [`ComparisonCondition`](../bus/filtering.md#numeric-direction-cincreased-and-cdecreased). `C.Increased()` fires only when the state value moves upward between events.

### Predicates

[`P.StateFrom`][hassette.event_handling.predicates.StateFrom] and [`P.StateTo`][hassette.event_handling.predicates.StateTo] compose inside `where=` for transition matching. A list passed to `where=` applies all predicates as logical AND.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_state_from_to.py"
```

The handler fires only when the light moves from an off-like state into `"on"`. Both predicates must match. The [Filtering & Predicates](../bus/filtering.md) page covers `P.AnyOf`, `P.Not`, and the complete predicate table.

### Numeric Conditions

`C.Increased` and `C.Decreased` fire when a numeric value moves in a particular direction.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_increased_decreased.py"
```

`changed=C.Increased()` applies directly on `on_state_change`. `P.StateComparison` and `P.AttrComparison` accept the same conditions as the `condition` argument for attribute-level direction tests.

## Attribute Changes

`on_attribute_change` takes `entity_id` and `attr` as its first two positional arguments. `attr` is the attribute name string, such as `"volume_level"` or `"brightness"`.

```python
--8<-- "pages/core-concepts/states/snippets/state_attribute_change.py"
```

Attribute-specific predicates compose inside `where=` the same way state predicates do: [`P.AttrFrom`][hassette.event_handling.predicates.AttrFrom], [`P.AttrTo`][hassette.event_handling.predicates.AttrTo], [`P.AttrDidChange`][hassette.event_handling.predicates.AttrDidChange], and [`P.AttrComparison`][hassette.event_handling.predicates.AttrComparison].

## Subscription Options

Both `on_state_change` and `on_attribute_change` accept these parameters beyond `entity_id`, `handler=`, and `name=`.

| Parameter | Purpose |
|---|---|
| `name=` | Required. Identifies the listener in logs and the telemetry DB. |
| `changed_to=` | Fires only when the new state matches this value. |
| `changed_from=` | Fires only when the previous state matches this value. |
| `changed=` | `True` (default) fires on value changes. `False` fires on every event. A `ComparisonCondition` compares old vs new. |
| `where=` | Predicate or list of predicates for fine-grained filtering. |
| `duration=` | Fires only after the state has held the new value for N seconds. Raises `ValueError` with glob patterns. |
| `immediate=` | When combined with `duration=`, fires at registration if the entity already meets the condition. Raises `ValueError` with glob patterns. |
| `debounce=` | Waits N seconds of quiet before firing. Resets on each new event. |
| `throttle=` | Fires at most once per N seconds. Events during the cooldown are dropped. |
| `once=` | Unsubscribes after the first fire. |
| `on_error=` | Callback invoked when the handler raises an exception. |

`duration=` and `immediate=` work together for restart-resilient hold patterns:

```python
--8<-- "pages/core-concepts/states/snippets/state_duration.py:duration"
```

`timeout=` and `timeout_disabled=` are also available via `**opts`. The [Writing Handlers](../bus/handlers.md) page covers timeouts and error behavior in detail.

## See Also

- [Bus](../bus/index.md): subscription lifecycle, glob patterns, and `Subscription` handles
- [Filtering & Predicates](../bus/filtering.md): complete `P`, `C`, and `A` reference
- [Dependency Injection](../bus/dependency-injection.md): full `D.*` annotation reference
- [States](index.md): reading state without subscribing, `self.states`, and domain access
