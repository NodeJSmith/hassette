# Filtering & Advanced Subscriptions

Hassette provides powerful tools for filtering events, ensuring your handlers only run when necessary.

The filtering system uses three helper modules, imported by alias:

- **`P`** (Predicates) — event matching logic: `from hassette import P`
- **`C`** (Conditions) — value comparison helpers: `from hassette import C`
- **`A`** (Accessors) — field extraction helpers used with `P.ValueIs` for custom sources: `from hassette import A`

`P` and `C` cover most filtering needs. `A` is an advanced tool for cases where you need to point a predicate at a non-standard field — for example, extracting a specific key from service data or a deeply nested attribute value. See [Custom Accessors](#custom-accessors-with-a) below.

## Common State Filtering

For `on_state_change`, the most common way to filter is using the `changed_to`, `changed_from`, or `changed` parameters. These allow you to filter based on the new state value, old state value, or general criteria.

### Simple Value Matching

Pass concrete values to match exact states:

Match when a state becomes a specific value with `changed_to`:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_simple_start.py"
```

Match when a state leaves a specific value with `changed_from`:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_simple_stop.py"
```

### Predicate Matching

For more logic, you can pass **Predicates** or callables directly to these parameters. This is the recommended way to handle most state change logic.

Match against a set of values with `C.IsIn`:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_predicate_isin.py"
```

Use a comparison condition with `C.Comparison`:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_predicate_lambda.py"
```

## The `changed` Parameter

By default, `on_state_change` only fires when the main state value changes. To also fire on attribute-only changes (e.g., brightness changed but the light is still "on"), pass `changed=False`:

```python
# Fire even when only attributes change, not the main state value
self.bus.on_state_change("light.office", handler=self.on_light_change, changed=False)
```

## Advanced Filtering with `where`

If `changed_to/from` aren't enough, or if you are filtering other event types (like service calls), use the `where` parameter.

`where` accepts a list of predicates (logical AND) or a customized predicate structure.

### Combining Predicates

Multiple predicates in a list are treated as logical **AND**.
Use `P.AnyOf` for logical **OR**.

Logical AND:
```python
--8<-- "pages/core-concepts/bus/snippets/filtering_combined_and.py"
```

Logical OR (Using `P.AnyOf`):
```python
--8<-- "pages/core-concepts/bus/snippets/filtering_combined_or.py"
```

## Filtering Service Calls

`on_call_service` supports both specific dictionary matching and predicate-based filtering using `where`.

### Dictionary Filtering

A simple dict passed to `where` matches keys and values in the service data.

Literal match — all keys and values must match exactly:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_literal.py"
```

Key presence — the key must exist, value doesn't matter:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_presence.py"
```

Callable values — custom check per key:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_callable.py"
```

### Predicate Filtering

Use `P.ServiceDataWhere` for structured access to service data fields:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_predicates.py"
```

## Advanced Topic Subscriptions

For scenarios not covered by helper methods, you can subscribe loosely to any event topic using `on`. This method always uses `where` for filtering.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_advanced_topics.py"
```

See the [Complete Reference](#complete-reference) below for the full list.

## More Filtering Patterns

### Tracking State Transitions with `P.StateFrom` / `P.StateTo`

`P.StateFrom` and `P.StateTo` are the recommended way to filter on the previous or next state value inside a `where` clause. They accept any value, callable, or condition object — the same types accepted by `changed_from` and `changed_to`.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_state_from_to.py"
```

### Monitoring Numeric Changes with `C.Increased` / `C.Decreased`

`C.Increased` and `C.Decreased` are comparison conditions that fire when a numeric value goes up or down between events. Pass them to the `changed` parameter on `on_state_change` or `on_attribute_change`, or use them inside `P.StateComparison` / `P.AttrComparison` for more control.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_increased_decreased.py"
```

### Matching Service Names with `P.ServiceMatches`

`P.ServiceMatches` filters raw `call_service` events by their service name (e.g. `"light.turn_on"`). Pair it with `P.ServiceDataWhere` to filter on both name and payload.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_matches.py"
```

## Custom Accessors with `A`

Most filtering uses `P` and `C` directly. `A` is useful when you need `P.ValueIs` to read from a field that isn't covered by the higher-level helpers — for instance, filtering a service call by a specific key inside `service_data`, or checking a deeply nested attribute.

```python
from hassette import A, P

# Only handle turn_on calls targeting a specific entity
entity_match = P.ValueIs(source=A.get_service_data_key("entity_id"), condition="light.living_room")
self.bus.on_call_service("light.turn_on", handler=self.on_living_room_on, where=entity_match)

# Check a nested attribute value using a dotted path
city_match = P.ValueIs(
    source=A.get_path("payload.data.new_state.attributes.geolocation.locality"),
    condition="San Francisco",
)
self.bus.on_state_change("sensor.my_device_location", handler=self.on_location_change, changed_to=city_match)
```

You generally won't need `A` unless you're filtering on data that `on_state_change`/`on_call_service` don't expose directly.

## Complete Reference

Quick lookup tables for every built-in predicate and condition. Import both from `hassette`: `from hassette import P, C`.

### Predicates (`P`)

Predicates are the top-level filters passed to `where`. They receive a full event object.

#### Logic combinators

| Class | Description | Works with |
|---|---|---|
| `P.AllOf(predicates)` | True when all contained predicates match (AND). A list passed to `where` is automatically wrapped in `AllOf`. | Any event |
| `P.AnyOf(predicates)` | True when at least one contained predicate matches (OR). | Any event |
| `P.Not(predicate)` | Negates a predicate. | Any event |
| `P.Guard(fn)` | Wraps any plain callable so it can be used in `AllOf`/`AnyOf` combinators. | Any event |

#### Value / field matching

| Class | Description | Works with |
|---|---|---|
| `P.ValueIs(source, condition)` | Extracts a value with `source` (an accessor from `A`) and tests it against `condition`. | Any event |
| `P.DidChange(source)` | True when the two values returned by `source(event)` differ (expects a `(old, new)` tuple). | Any event |
| `P.IsPresent(source)` | True when the value extracted by `source` is not `MISSING_VALUE`. | Any event |
| `P.IsMissing(source)` | True when the value extracted by `source` is `MISSING_VALUE`. | Any event |

#### Entity / domain / service matching

| Class | Description | Works with |
|---|---|---|
| `P.DomainMatches(domain)` | Matches when the event domain equals `domain`. Supports glob patterns. | `HassEvent` |
| `P.EntityMatches(entity_id)` | Matches when the event entity_id equals `entity_id`. Supports glob patterns. | `HassEvent` |
| `P.ServiceMatches(service)` | Matches when the service name equals `service` (e.g. `"light.turn_on"`). Supports globs. | `call_service` events |
| `P.ServiceDataWhere(spec)` | Matches when all keys in `spec` satisfy their conditions against the service data payload. | `CallServiceEvent` |

#### State change predicates

These are typed for `RawStateChangeEvent` and are only valid on `on_state_change` subscriptions (or raw `call_service` events via `on`).

| Class | Description | Works with |
|---|---|---|
| `P.StateFrom(condition)` | True when the *previous* state satisfies `condition`. Equivalent to `changed_from=condition` but usable in `where`. | `RawStateChangeEvent` |
| `P.StateTo(condition)` | True when the *new* state satisfies `condition`. Equivalent to `changed_to=condition` but usable in `where`. | `RawStateChangeEvent` |
| `P.StateComparison(condition)` | Passes `(old_state, new_state)` to a comparison condition such as `C.Increased()` or `C.Decreased()`. | `RawStateChangeEvent` |
| `P.StateDidChange()` | True when the main state value changed between events. | `RawStateChangeEvent` |
| `P.AttrFrom(attr_name, condition)` | True when the *previous* value of an attribute satisfies `condition`. | `RawStateChangeEvent` |
| `P.AttrTo(attr_name, condition)` | True when the *new* value of an attribute satisfies `condition`. | `RawStateChangeEvent` |
| `P.AttrComparison(attr_name, condition)` | Passes `(old_attr, new_attr)` to a comparison condition. | `RawStateChangeEvent` |
| `P.AttrDidChange(attr_name)` | True when the named attribute changed between events. | `RawStateChangeEvent` |

---

### Conditions (`C`)

Conditions are value-level matchers. Pass them to `changed_to`, `changed_from`, `changed`, or as the `condition` argument to predicates like `P.ValueIs`.

#### String matching

| Class | Description |
|---|---|
| `C.Glob(pattern)` | Matches if the value matches a glob pattern (e.g. `"light.*"`). |
| `C.StartsWith(prefix)` | Matches if the string value starts with `prefix`. |
| `C.EndsWith(suffix)` | Matches if the string value ends with `suffix`. |
| `C.Contains(substring)` | Matches if the string value contains `substring`. |
| `C.Regex(pattern)` | Matches if the string value matches a regex pattern (anchored at start). |

#### Collection membership

| Class | Description |
|---|---|
| `C.IsIn(collection)` | True when the value appears in `collection`. |
| `C.NotIn(collection)` | True when the value does not appear in `collection`. |
| `C.Intersects(collection)` | True when the value (a sequence) shares at least one item with `collection`. |
| `C.NotIntersects(collection)` | True when the value (a sequence) shares no items with `collection`. |
| `C.IsOrContains(item)` | True when the value equals `item`, or when the value is a sequence that contains `item`. |

#### None / missing checks

| Class | Description |
|---|---|
| `C.IsNone()` | True when the value is `None`. |
| `C.IsNotNone()` | True when the value is not `None`. |
| `C.Present()` | True when the value is not the internal `MISSING_VALUE` sentinel. Used for presence checks in state diffs. |
| `C.Missing()` | True when the value is the internal `MISSING_VALUE` sentinel. |

#### Numeric comparison

| Class | Description |
|---|---|
| `C.Comparison(op, value)` | Compares a single value using an operator string (`">"`, `"<"`, `">="`, `"<="`, `"=="`, `"!="` or their named forms). |
| `C.Increased()` | Comparison condition: passes `(old, new)` — true when the numeric value increased. Use with `changed=`, `P.StateComparison`, or `P.AttrComparison`. |
| `C.Decreased()` | Comparison condition: passes `(old, new)` — true when the numeric value decreased. Use with `changed=`, `P.StateComparison`, or `P.AttrComparison`. |

## See Also

- [Writing Handlers](handlers.md) - Extract data with dependency injection
- [States](../states/index.md) - Access current state in predicates
- [Scheduler](../scheduler/index.md) - Combine event-driven and time-based automation
