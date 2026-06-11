# Filtering & Predicates

Three filtering layers narrow which events reach a handler. Built-in parameters (`changed_to`, `changed_from`, `changed`) cover the common cases directly on `on_state_change` and `on_attribute_change`. Conditions (`C`) express value-level tests: set membership, numeric comparisons, string patterns. Predicates (`P`) handle anything more complex, composing with `where=` on any subscription method.

All three are importable from `hassette`.

```python
from hassette import P, C, A
```

`P` contains predicates for filtering events. `C` contains conditions for matching values. `A` contains accessors for extracting specific fields from events — covered at the [end of this page](#custom-accessors).

## Filtering State Changes

Filters and predicates compare against **raw Home Assistant state strings**, not typed state models. HA reports state values as strings: `"on"`, `"off"`, `"unavailable"`, `"72.5"`. Filtering runs before type conversion for performance. Hassette avoids deserializing every event into a Pydantic model when most events will be filtered out. This means `changed_to="on"` is correct, not `changed_to=True`, even though `LightState.value` is a `bool` after dependency injection delivers it to the handler.

`on_state_change` accepts three built-in parameters that handle the majority of state-change filtering without predicates.

### `changed_to`

`changed_to` restricts the handler to events where the new state matches a value.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_simple_start.py"
```

The handler fires only when `binary_sensor.front_door` transitions to `"on"`. Transitions from `"on"` to anything else are ignored.

### `changed_from`

`changed_from` restricts the handler to events where the previous state matches a value.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_simple_stop.py"
```

The handler fires only when the sensor leaves `"on"`, meaning when motion stops.

### `changed=False`

By default, `on_state_change` fires only when the main state value changes. `changed=False` removes that restriction, allowing the handler to fire on attribute-only changes too.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/changed_false.py:changed_false"
```

A light remaining `"on"` while its brightness shifts from 128 to 255 would normally produce no event. With `changed=False`, that attribute update reaches the handler.

## Conditions

Conditions are value-level matchers. They work as arguments to `changed_to`, `changed_from`, and `changed`, or as the `condition` argument inside predicates.

### Set membership: `C.IsIn`

`C.IsIn` fires when the value appears in a collection.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_predicate_isin.py"
```

The handler runs only when `app_name` becomes `"Home Assistant Lovelace"` or `"Netflix"`.

### Numeric comparison: `C.Comparison`

`C.Comparison` tests a value against a threshold using an operator string.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_predicate_lambda.py"
```

Supported operators: `">"`, `"<"`, `">="`, `"<="`, `"=="`, `"!="`, and their named forms (`"gt"`, `"lt"`, `"ge"`, `"le"`, `"eq"`, `"ne"`).

### Numeric direction: `C.Increased` and `C.Decreased`

`C.Increased` and `C.Decreased` fire when a numeric value moves in a particular direction between events. Both work as arguments to `changed=` on `on_state_change` or `on_attribute_change`, and inside `P.StateComparison` / `P.AttrComparison` for attribute-level direction tests.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_increased_decreased.py"
```

The full conditions table, including string matching, collection membership, and null checks, is on the [Predicate Reference](predicate-reference.md) page.

## Predicates and the `where` Parameter

When built-in parameters are not enough, `where=` accepts a predicate or a list of predicates. A list is treated as logical AND, so all predicates must match.

### `P.StateFrom` and `P.StateTo`

`P.StateFrom` tests the previous state. `P.StateTo` tests the new state. Both accept any value, callable, or condition object. They take the same types as `changed_from` and `changed_to`, but exist as predicate objects so they can be nested inside `P.AnyOf`, `P.AllOf`, or `P.Not` — something the bare `changed_from`/`changed_to` parameters cannot do.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_state_from_to.py"
```

The handler fires only when the light moves from an off-like state into `"on"`. Both predicates must match.

### Logical AND

`P.AttrTo` tests that a specific attribute's new value matches a condition — the attribute equivalent of `P.StateTo`. A list passed to `where=` applies all predicates as logical AND.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_combined_and.py"
```

Both `P.AttrTo` predicates must match. The `changed=False` parameter is also required here, since only attributes change, not the main state value.

### Logical OR: `P.AnyOf`

`P.AnyOf` fires when at least one contained predicate matches.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_combined_or.py"
```

`P.AllOf` is an explicit AND combinator — it does the same thing as passing a list to `where=`, but can be nested inside `P.AnyOf` or `P.Not` where a plain list is not accepted. `P.Not` negates any predicate: `P.Not(P.StateTo("on"))` fires when the new state is anything except `"on"`. All three compose freely.

## Filtering Service Calls

`on_call_service` accepts `domain=` and `service=` for coarse filtering, and `where=` for fine-grained control. `where=` on `on_call_service` also accepts a plain dict, which matches against the service data payload.

### Dict filtering

A dict passed to `where=` matches keys and values in the service data.

**Literal match.** Every key-value pair must match exactly.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_literal.py"
```

**Key presence.** The key must exist, but value does not matter (`ANY_VALUE`).

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_presence.py"
```

**Callable per key.** A function receives the value and returns a bool.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_callable.py"
```

### `P.ServiceDataWhere`

`P.ServiceDataWhere` provides structured access to service data fields. Two forms: the dict form (`P.ServiceDataWhere({"entity_id": "scene.evening"})`) does literal key matching; `P.ServiceDataWhere.from_kwargs` accepts callables and conditions per field.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_predicates.py"
```

### `P.ServiceMatches`

`P.ServiceMatches` filters on the bare service name (e.g., `"turn_on"`); the domain is a separate field, matched by `P.DomainMatches`. `on_call_service` has `domain=` and `service=` built in. When subscribing via `on(topic="hass.event.call_service")` instead — for raw event-level access — those parameters are not available, so `P.DomainMatches` and `P.ServiceMatches` fill that role.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_matches.py"
```

## Raw Topic Subscriptions

`on()` subscribes to any event topic by string. It accepts `where=` predicates but has no built-in `changed_to` / `changed_from` parameters. All filtering goes through predicates.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_advanced_topics.py"
```

`on()` covers event types that the typed helper methods do not expose, including custom internal events, raw Home Assistant events, and any future topic the framework adds.

## Custom Accessors

[`A`](custom-extractors.md) (accessors) point predicates at fields not directly exposed by the helper methods. `P.ValueIs` extracts a value with an accessor, then tests it against a condition.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/custom_accessors.py"
```

`A.get_service_data_key` extracts a specific key from service data. `A.get_path` follows a dot-separated path through the event payload. Most filtering needs are met by `changed_to`, `changed_from`, and the typed predicates. `A` handles the cases they do not reach. The full accessor guide is at [Custom Extractors](custom-extractors.md).

## Full Reference

The complete `P`, `C`, and `A` lookup tables live on [Predicate Reference](predicate-reference.md).

## See Also

- [Writing Handlers](handlers.md). Handler signature patterns and dependency injection.
- [Subscription Methods](methods.md). Method reference, parameters, and registration.
- [Dependency Injection](dependency-injection.md). How `D.*` annotations work alongside predicates.
- [Predicate Reference](predicate-reference.md). Complete `P`, `C`, and `A` tables.
- [Custom Extractors](custom-extractors.md). Accessors for non-standard fields.
