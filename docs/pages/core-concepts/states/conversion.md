# State Conversion

Home Assistant sends state data as untyped dicts with string values. Two registries cooperate to produce typed Python objects: the [`StateRegistry`][hassette.conversion.state_registry.StateRegistry] maps domains to state classes, and the [`TypeRegistry`][hassette.conversion.type_registry.TypeRegistry] converts string values to typed Python values. This conversion runs automatically whenever a handler receives state via [dependency injection](../bus/dependency-injection.md) — the mechanism that fills in handler parameters like `D.StateNew[T]` from the event. Most apps benefit from it without touching either registry directly.

The registries become relevant when overriding domain mappings, registering custom converters, or debugging unexpected types.

## The Conversion Pipeline

When state data arrives from Home Assistant, `StateRegistry.try_convert_state()` runs the full pipeline. Dependency injection calls it automatically; direct calls are only needed when converting raw dicts outside a handler, such as in tests or data scripts. Given this raw input:

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/flow_raw_input.py"
```

The pipeline runs four steps:

1. `StateRegistry.resolve(domain="binary_sensor")` looks up the registered class for the domain.
   It returns [`BinarySensorState`][hassette.models.states.binary_sensor.BinarySensorState].

2. The codec normalizes `"unknown"` and `"unavailable"` states to `None` before coercion, then
   reads `value_type` from the resolved class and delegates to `TypeRegistry`.

3. `TypeRegistry` looks up the `(str, bool)` converter and converts `"on"` to `True`.

4. The codec constructs the model from the prepared dict. The result is a fully typed state object:

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/flow_converted_output.py"
```

`StateRegistry` answers "which class?". `TypeRegistry` answers "which type for the value?". The state model handles shape normalization — extracting the domain from `entity_id` and mapping `"unknown"`/`"unavailable"` to sentinel flags — but performs no value coercion. The codec owns type conversion: reading `value_type`, selecting the right converter, and constructing the typed state.

Each state class declares a `value_type` class variable — the type (or tuple of types) the `value` field should hold. The codec reads this and selects the right converter:

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/value_type_example.py"
```

When `resolve` returns `None` for an unregistered domain, `try_convert_state` falls back
to [`BaseState`][hassette.models.states.base.BaseState].

## Domain-to-Class Mapping

### How Registration Works

Any class that inherits from `BaseState` and declares a `domain: Literal["domain_name"]`
field registers itself automatically at class definition time. No explicit call is needed.

`BaseState.__init_subclass__` runs when Python evaluates the class body. It calls
`get_domain()`, which reads the `Literal` type argument from the `domain` annotation,
and records the class under that domain. Classes without a `Literal["..."]` annotation
on `domain` are silently skipped.

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/automatic_registration.py"
```

### Domain Lookup

`StateRegistry.resolve(domain=...)` returns the registered class for a domain, or `None`
when no class is registered.

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/domain_lookup.py"
```

The `None` return is intentional. `try_convert_state` handles the fallback to `BaseState`
when `resolve` returns `None`.

### Overriding a Domain Mapping

A custom class with the same `Literal` domain as a built-in replaces the existing mapping.
Overriding is how custom attributes get typed — for example, a sensor integration that
reports a calibration field not present on the built-in `SensorState`. The override takes
effect at class definition time.

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/domain_override.py"
```

The registry replaces the previous mapping silently and globally — a typo in the `Literal`
domain overrides a built-in with no warning. `STATE_REGISTRY.resolve(domain="sensor")`
confirms which class is registered. All subsequent state events for `sensor` entities
produce `CustomSensorState` instances.

For classes that can't declare a `Literal` domain — built dynamically, or registered conditionally at runtime — [`register_state_converter`][hassette.conversion.register_state_converter] registers a class with the registry explicitly. It is the imperative equivalent of the `Literal`-based auto-registration.

`STATE_REGISTRY` is available as a top-level import for direct access outside an app:
`from hassette import STATE_REGISTRY`.

### Union Type Support

A handler can accept multiple entity types at once with a union annotation. `StateRegistry`
resolves the union by matching each type's domain against the incoming entity's domain.

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/union_type_support.py"
```

For `D.StateNew[states.SensorState | states.BinarySensorState]`, the DI system extracts
the domain from the entity ID, checks each type in the union, and selects the one whose
`Literal` domain matches. When no type matches, conversion falls back to `BaseState`.

## Value Conversion

### How It Works

`TypeRegistry` maps `(from_type, to_type)` pairs to converter functions. When a raw value
does not match the expected `value_type`, the registry looks up a matching converter and
applies it.

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/lookup_example.py"
```

When no registered converter exists, the registry tries the target type's constructor as a
fallback. A successful constructor call does not register the pair — each miss goes through the constructor directly. Custom converters registered via `register_simple_type_converter` or `@register_type_converter_fn` are added normally.

For union `value_type` declarations (`value_type = (int, float, str)`), conversion is attempted in order and the first success wins. `str` succeeds trivially (no conversion needed), so placing it first would always short-circuit before attempting `int` or `float`. The most specific type must come first: `(int, float, str)` is correct; `(str, int, float)` is not.

### Built-in Converters

#### Numeric

| From | To | Notes |
|------|----|----|
| `str` | `int` | Direct parse |
| `str` | `float` | Direct parse |
| `str` | `Decimal` | High-precision parse |
| `float` | `Decimal` | Precision-preserving |
| `Decimal` | `int` | Truncates fractional part |
| `Decimal` | `float` | Precision loss accepted |
| `int` | `float` | Widening conversion |
| `float` | `int` | Truncates fractional part |

#### Boolean

The `str` → `bool` converter maps Home Assistant string values:

- `True`: `"on"`, `"true"`, `"yes"`, `"1"`
- `False`: `"off"`, `"false"`, `"no"`, `"0"`

The `bool` → `str` converter produces Python's `"True"` or `"False"`, not HA format.

#### DateTime

All datetime conversions use the [`whenever`](https://github.com/ariebovenberg/whenever)
library, which ships with Hassette.

**`whenever` types:**

| From | To | Method |
|------|----|--------|
| `str` | `ZonedDateTime` | Parses ISO, plain, or date-only strings (date-only assumes system timezone) |
| `str` | `Date` | `Date.parse_iso` |
| `str` | `Time` | `Time.parse_iso` |
| `str` | `OffsetDateTime` | `OffsetDateTime.parse_iso` |
| `str` | `PlainDateTime` | `PlainDateTime.parse_iso` |
| `ZonedDateTime` | `Instant` | `to_instant()` |
| `ZonedDateTime` | `PlainDateTime` | `to_plain()` |
| `ZonedDateTime` | `str` | `format_iso()` |
| `Time` | `str` | `format_iso()` |

**Stdlib datetime types** (for boundary compatibility):

| From | To | Method |
|------|----|--------|
| `str` | `datetime` | Via `ZonedDateTime` then `py_datetime()` |
| `str` | `time` | Via `Time.parse_iso().py_time()` |
| `str` | `date` | Via `Date.parse_iso().py_date()` |
| `Time` | `time` | `py_time()` |

## Custom Converters

### Decorator Registration

`@register_type_converter_fn` registers a converter by reading `from_type` and `to_type`
from the function's type annotations. The parameter must be named `value`; the return
annotation determines the target type.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/custom_type_converter.py"
```

The decorator accepts keyword arguments for error handling:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `error_message` | `str \| None` | `None` | Message on conversion failure. Supports `{value}`, `{from_type}`, `{to_type}` placeholders. |
| `error_types` | `tuple[type[BaseException], ...]` | `(ValueError,)` | Exceptions that trigger a wrapped `UnableToConvertValueError`. Other exceptions propagate as `RuntimeError`. |

### Simple Registration

`register_simple_type_converter` registers an existing callable (a constructor, a method,
or a lambda) without wrapping it in a dedicated function.

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/simple_registration.py"
```

When `fn` is omitted, the target type's constructor is used. `error_message` and
`error_types` accept the same arguments as the decorator form.

### Common Patterns

#### Enum Conversion

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/pattern_enum.py"
```

The decorator infers `str → FanSpeed` from the function signature. The converter is
available at module import time.

#### Structured Data

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/pattern_structured.py"
```

`json.loads` raises `json.JSONDecodeError` (a `ValueError` subclass), so the default
`error_types=(ValueError,)` catches parse failures automatically.

## Error Handling

### State Conversion Errors

`try_convert_state` raises specific exceptions for distinct failure modes.

#### `InvalidDataForStateConversionError`

Raised when the state data is malformed or missing required fields. For example, the input
is `None` or contains an `event` key instead of a state dict.

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/error_invalid_data.py"
```

#### `InvalidEntityIdError`

Raised when `entity_id` is missing, not a string, or lacks a `.` separator between domain
and entity name.

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/error_invalid_entity_id.py"
```

#### `UnableToConvertStateError`

Raised when the codec fails to construct a state object for both the resolved state class and the
`BaseState` fallback.

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/error_unable_to_convert.py"
```

### Value Conversion Errors

#### `UnableToConvertValueError`

When a registered converter raises one of its `error_types`, the registry wraps it in
`UnableToConvertValueError`:

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/conversion_error.py"
```

When no converter is registered and the target type's constructor also fails:

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/missing_converter.py"
```

Custom error messages with `{value}` make failures easier to diagnose:

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/custom_error_msg.py"
```

## Inspection and Debugging

`TYPE_REGISTRY` and `STATE_REGISTRY` are both available as top-level imports.

**List all registered value converters:**

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/inspect_list.py"
```

Output:

```
--8<-- "pages/core-concepts/states/snippets/type-registry/inspect_list_output.txt"
```

**Check whether a specific converter is registered:**

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/inspect_check.py"
```

`TypeRegistry.conversion_map` is a dict keyed by `(from_type, to_type)` tuples. Each value
is a `TypeConverterEntry` with `func`, `from_type`, `to_type`, `error_types`, and
`error_message` fields.

!!! tip "Unexpected state type at runtime?"
    `STATE_REGISTRY.resolve(domain="the_domain")` confirms which class is registered.
    If a custom class override does not take effect, import order is the likely cause.
    The override class must be imported after the module that defines the original.

## See Also

- [Custom States](custom-states.md): defining state classes for custom integrations
- [Dependency Injection](../bus/dependency-injection.md): how `D.StateNew[T]` uses the registries
- [States Overview](index.md): the `self.states` cache that sits above the registries
