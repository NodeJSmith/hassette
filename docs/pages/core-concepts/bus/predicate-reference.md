# Predicate, Condition & Accessor Reference

[`P`][predicates], [`C`][conditions], and [`A`][accessors] are available as top-level imports:

```python
from hassette import P, C, A
```

This page is a lookup reference. For explanations of how predicates, conditions, and accessors compose, see [Filtering](filtering.md).

[predicates]: filtering.md
[conditions]: filtering.md
[accessors]: filtering.md

## Predicates (`P`)

A predicate accepts an event and returns `bool`. Pass predicates to `where=` on any bus subscription, or compose them with other predicates.

### Logic Combinators

Works with: any event type.

| Predicate | Signature | Description |
|---|---|---|
| `P.AllOf` | `AllOf(predicates: tuple[Predicate, ...])` | Returns `True` when all contained predicates return `True`. |
| `P.AnyOf` | `AnyOf(predicates: tuple[Predicate, ...])` | Returns `True` when at least one contained predicate returns `True`. |
| `P.Not` | `Not(predicate: Predicate)` | Negates the result of the wrapped predicate. |
| `P.Guard` | `Guard(fn: Predicate[EventT])` | Wraps any callable as a typed predicate for use in combinators. |

`AllOf` and `AnyOf` each have a classmethod `ensure_iterable(where)` that wraps a single predicate or sequence into the combinator.

### Value / Field Matching

Works with: any event type.

| Predicate | Signature | Description |
|---|---|---|
| `P.ValueIs` | `ValueIs(source: Callable, condition: ChangeType = ANY_VALUE)` | Extracts a value via `source`, then tests it against `condition`. When `condition` is `ANY_VALUE`, always returns `True`. |
| `P.DidChange` | `DidChange(source: Callable[..., tuple[Any, Any]])` | Returns `True` when the two values returned by `source` differ. |
| `P.IsPresent` | `IsPresent(source: Callable)` | Returns `True` when the value extracted by `source` is not `MISSING_VALUE`. |
| `P.IsMissing` | `IsMissing(source: Callable)` | Returns `True` when the value extracted by `source` is `MISSING_VALUE`. |

`condition` accepts a literal value, a `C.*` condition instance, a glob string, or any callable `(value) -> bool`.

### Entity / Domain / Service Matching

Works with: `HassEvent`, [`CallServiceEvent`][hassette.events.hass.hass.CallServiceEvent].

| Predicate | Signature | Description |
|---|---|---|
| `P.DomainMatches` | `DomainMatches(domain: str)` | Returns `True` when the event domain matches `domain`. Glob patterns are auto-detected. |
| `P.EntityMatches` | `EntityMatches(entity_id: str)` | Returns `True` when the event `entity_id` matches. Glob patterns are auto-detected. |
| `P.ServiceMatches` | `ServiceMatches(service: str)` | Returns `True` when the called service matches. Glob patterns are auto-detected. |
| `P.ServiceDataWhere` | `ServiceDataWhere(spec: Mapping[str, ChangeType], auto_glob: bool = True)` | Returns `True` when each key in `spec` satisfies its condition against the event's `service_data`. |

`ServiceDataWhere.from_kwargs(*, auto_glob=True, **spec)` is an ergonomic constructor for literal keyword arguments:

```python
P.ServiceDataWhere.from_kwargs(entity_id="light.*", brightness=200)
```

When `auto_glob=True` (the default), bare glob strings in `spec` values are automatically wrapped in `C.Glob`.

### State Change Predicates

Works with: [`RawStateChangeEvent`][hassette.events.hass.hass.RawStateChangeEvent].

| Predicate | Signature | Description |
|---|---|---|
| `P.StateFrom` | `StateFrom(condition: ChangeType)` | Returns `True` when the old state value satisfies `condition`. |
| `P.StateTo` | `StateTo(condition: ChangeType)` | Returns `True` when the new state value satisfies `condition`. |
| `P.StateComparison` | `StateComparison(condition: ComparisonCondition)` | Returns `True` when `condition(old_state_value, new_state_value)` is `True`. Accepts `C.Increased`, `C.Decreased`, or any two-argument callable. |
| `P.StateDidChange` | `StateDidChange()` | Returns `True` when the state string changed. |
| `P.AttrFrom` | `AttrFrom(attr_name: str, condition: ChangeType)` | Returns `True` when the named attribute's old value satisfies `condition`. |
| `P.AttrTo` | `AttrTo(attr_name: str, condition: ChangeType)` | Returns `True` when the named attribute's new value satisfies `condition`. |
| `P.AttrComparison` | `AttrComparison(attr_name: str, condition: ComparisonCondition)` | Returns `True` when `condition(old_attr, new_attr)` is `True` for the named attribute. |
| `P.AttrDidChange` | `AttrDidChange(attr_name: str)` | Returns `True` when the named attribute changed. When `old_state` is `None`, returns `True` if the attribute is present on the new state. |

No `StateFromTo` predicate exists. For from-to matching, combine `P.StateFrom` and `P.StateTo` inside `P.AllOf`.

## Conditions (`C`)

A condition is a single-value callable `(value) -> bool`. Predicates like `P.ValueIs` accept a condition as their `condition` argument. The `changed_to=` and `changed_from=` subscription helpers also accept conditions directly.

### String Matching

| Condition | Signature | Description |
|---|---|---|
| `C.Glob` | `Glob(pattern: str)` | Returns `True` when the string value matches the glob pattern. |
| `C.StartsWith` | `StartsWith(prefix: str)` | Returns `True` when the string value starts with `prefix`. |
| `C.EndsWith` | `EndsWith(suffix: str)` | Returns `True` when the string value ends with `suffix`. |
| `C.Contains` | `Contains(substring: str)` | Returns `True` when the string value contains `substring`. |
| `C.Regex` | `Regex(pattern: str)` | Returns `True` when the string value matches the compiled regex pattern. |

### Collection Membership

| Condition | Signature | Description |
|---|---|---|
| `C.IsIn` | `IsIn(collection: Sequence[Any])` | Returns `True` when the value is in `collection`. |
| `C.NotIn` | `NotIn(collection: Sequence[Any])` | Returns `True` when the value is not in `collection`. |
| `C.Intersects` | `Intersects(collection: Sequence[Any])` | Returns `True` when the value (itself a sequence) shares at least one element with `collection`. |
| `C.NotIntersects` | `NotIntersects(collection: Sequence[Any])` | Returns `True` when the value (itself a sequence) shares no elements with `collection`. |
| `C.IsOrContains` | `IsOrContains(condition: str)` | Returns `True` when the value equals `condition`, or when the value is a sequence containing it. |

`collection` must be a sequence, not a string. Passing a string raises `ValueError`.

### None / Missing Checks

| Condition | Signature | Description |
|---|---|---|
| `C.IsNone` | `IsNone()` | Returns `True` when the value is `None`. |
| `C.IsNotNone` | `IsNotNone()` | Returns `True` when the value is not `None`. |
| `C.Present` | `Present()` | Returns `True` when the value is not `MISSING_VALUE`. |
| `C.Missing` | `Missing()` | Returns `True` when the value is `MISSING_VALUE`. |

`MISSING_VALUE` and `None` are distinct. `C.IsNone` / `C.IsNotNone` test for Python `None`; `C.Present` / `C.Missing` test for Hassette's sentinel that indicates a field does not exist on the event.

### Numeric Comparison

| Condition | Signature | Description |
|---|---|---|
| `C.Comparison` | `Comparison(op: OPS, value: Any)` | Returns `True` when `extracted_value op value` holds. `op` is one of `">"`, `"<"`, `">="`, `"<="`, `"=="`, `"!="` (or their spelled-out equivalents `"gt"`, `"lt"`, `"ge"`, `"le"`, `"eq"`, `"ne"`). |
| `C.Increased` | `Increased()` | Two-argument condition. Returns `True` when `float(new) > float(old)`. For use with `P.StateComparison` or `P.AttrComparison`. |
| `C.Decreased` | `Decreased()` | Two-argument condition. Returns `True` when `float(new) < float(old)`. For use with `P.StateComparison` or `P.AttrComparison`. |

No `C.InRange` condition exists. For range checks, combine two `C.Comparison` instances inside `P.AllOf`:

```python
P.AllOf((
    P.ValueIs(source=A.get_state_value_new, condition=C.Comparison(">=", 18)),
    P.ValueIs(source=A.get_state_value_new, condition=C.Comparison("<=", 26)),
))
```

## Accessors (`A`)

An accessor is a factory function that returns a callable `(event) -> value`. Predicates like `P.ValueIs`, `P.DidChange`, `P.IsPresent`, and `P.IsMissing` accept an accessor as their `source=` argument. `Bus` helpers use accessors internally. Direct use is needed only when pointing a predicate at a non-standard field.

### State Value

Works with: `RawStateChangeEvent`.

| Accessor | Returns | Description |
|---|---|---|
| `A.get_state_value_old` | `Any \| MISSING_VALUE` | The old state string, or `MISSING_VALUE` when `old_state` is `None`. |
| `A.get_state_value_new` | `Any \| MISSING_VALUE` | The new state string, or `MISSING_VALUE` when `new_state` is `None`. |
| `A.get_state_value_old_new` | `tuple[Any, Any]` | `(old_state_value, new_state_value)` as a tuple. |

### State Object

Works with: `RawStateChangeEvent`.

| Accessor | Returns | Description |
|---|---|---|
| `A.get_state_object_old` | `HassStateDict \| None` | The full old state dict, or `None` when absent. |
| `A.get_state_object_new` | `HassStateDict \| None` | The full new state dict, or `None` when absent. |
| `A.get_state_object_old_new` | `tuple[HassStateDict \| None, HassStateDict \| None]` | Both state objects as a tuple. |

### Attribute

Works with: `RawStateChangeEvent`.

| Accessor | Signature | Returns | Description |
|---|---|---|---|
| `A.get_attr_old` | `get_attr_old(name: str)` | `Any \| MISSING_VALUE` | The named attribute from the old state; `MISSING_VALUE` when absent. |
| `A.get_attr_new` | `get_attr_new(name: str)` | `Any \| MISSING_VALUE` | The named attribute from the new state; `MISSING_VALUE` when absent. |
| `A.get_attr_old_new` | `get_attr_old_new(name: str)` | `tuple[Any, Any]` | `(old_attr, new_attr)` for the named attribute. |
| `A.get_attrs_old` | `get_attrs_old(names: list[str])` | `dict[str, Any]` | A dict of the named attributes from the old state. Missing names map to `MISSING_VALUE`. |
| `A.get_attrs_new` | `get_attrs_new(names: list[str])` | `dict[str, Any]` | A dict of the named attributes from the new state. Missing names map to `MISSING_VALUE`. |
| `A.get_attrs_old_new` | `get_attrs_old_new(names: list[str])` | `tuple[dict, dict]` | Both attribute dicts as a tuple. |
| `A.get_all_attrs_old` | `get_all_attrs_old` | `dict[str, Any] \| MISSING_VALUE` | All attributes from the old state, or `MISSING_VALUE` when `old_state` is `None`. |
| `A.get_all_attrs_new` | `get_all_attrs_new` | `dict[str, Any] \| MISSING_VALUE` | All attributes from the new state, or `MISSING_VALUE` when `new_state` is `None`. |
| `A.get_all_attrs_old_new` | `get_all_attrs_old_new` | `tuple[dict \| MISSING_VALUE, dict \| MISSING_VALUE]` | Both full attribute dicts as a tuple. |

### Identity

Works with: `HassEvent` (any event).

| Accessor | Returns | Description |
|---|---|---|
| `A.get_domain` | `str \| MISSING_VALUE` | The domain portion of the event (e.g., `"light"` from `"light.kitchen"`). |
| `A.get_entity_id` | `str \| MISSING_VALUE` | The `entity_id` from the event payload, or from `service_data` for `CallServiceEvent`. |
| `A.get_context` | `HassContext` | The context dict from the event payload. |

### Service

Works with: `CallServiceEvent`.

| Accessor | Signature | Returns | Description |
|---|---|---|---|
| `A.get_service` | `get_service` | `str \| MISSING_VALUE` | The service name being called. |
| `A.get_service_data` | `get_service_data` | `dict[str, Any] \| MISSING_VALUE` | The full `service_data` dict, or `MISSING_VALUE` when absent. |
| `A.get_service_data_key` | `get_service_data_key(key: str)` | `Any \| MISSING_VALUE` | A specific key from `service_data`; `MISSING_VALUE` when absent. |

### Other

| Accessor | Signature | Returns | Description |
|---|---|---|---|
| `A.get_path` | `get_path(path: str)` | `Any \| MISSING_VALUE` | Extracts a nested value by dot-separated glom path; `MISSING_VALUE` on any access failure. |
| `A.get_all_changes` | `get_all_changes(exclude: Sequence[str] = DEFAULT_EXCLUDE)` | `dict[str, Any]` | A recursive diff between old and new state, mapping changed keys to `(old_value, new_value)`. Excludes `last_reported`, `last_updated`, `last_changed`, and `context` by default. |

`get_path` works with any event type. `get_all_changes` works with `RawStateChangeEvent`.

Single-value accessors work with `P.ValueIs`, `P.IsPresent`, and `P.IsMissing`. Tuple-returning accessors (the `*_old_new` variants) work with `P.DidChange`. For writing custom accessors, see [Custom Extractors](custom-extractors.md).

## See Also

- [Filtering](filtering.md). How predicates, conditions, and accessors compose in practice.
- [Custom Extractors](custom-extractors.md). Writing accessors for non-standard event fields.
