# Type Registry

Home Assistant sends nearly all values as strings over its WebSocket API. The [`TypeRegistry`][hassette.conversion.type_registry.`TypeRegistry`] converts those strings to typed Python values (`int`, `float`, `bool`, `ZonedDateTime`, `Decimal`, and others) before they reach handler code.

The `TypeRegistry` handles value conversion. The [State Registry](state-registry.md) handles domain-to-class mapping. Most apps never touch the `TypeRegistry` directly because the built-in converters cover all standard HA types.

This page is relevant when a custom state model's `value_type` is a type Hassette does not know how to convert, or when a built-in conversion produces unexpected results.

## How Conversion Works

The registry maps `(from_type, to_type)` pairs to converter functions. When state data arrives and the raw value does not match the expected `value_type`, the registry looks up a matching converter and applies it.

If no registered converter exists for the pair, the registry attempts the target type's constructor as a fallback. A successful constructor call auto-registers the conversion for future use.

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/lookup_example.py"
```

For union types (`value_type = (int, float, str)`), conversion attempts each member type in order. Placing the most specific type first avoids premature matches. `str` matches everything, so `(int, float, str)` is correct and `(str, int, float)` is not.

## Built-in Converters

### Numeric

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

### Boolean

The `str` → `bool` converter maps HA-specific string values:

- `True`: `"on"`, `"true"`, `"yes"`, `"1"`
- `False`: `"off"`, `"false"`, `"no"`, `"0"`

The `bool` to `str` converter produces Python's `"True"` or `"False"`, not HA format.

### DateTime

All datetime conversions use the [`whenever`](https://github.com/ariebovenberg/whenever) library.

**`whenever` types:**

| From | To | Method |
|------|----|--------|
| `str` | `ZonedDateTime` | Parses ISO, plain, or date-only strings (date-only strings assume the system timezone) |
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

## Registering a Custom Converter

### Decorator Registration

`@register_type_converter_fn` registers a converter by reading the `from_type` and `to_type` directly from the function's type annotations. The parameter must be named `value` and the return annotation determines the target type.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/custom_type_converter.py"
```

The decorator also accepts keyword arguments for error handling:

```python
@register_type_converter_fn(
    error_message="'{value}' is not a valid Effect",
    error_types=(ValueError, KeyError),
)
def str_to_effect(value: str) -> Effect: ...
```

`error_message` supports `{value}`, `{from_type}`, and `{to_type}` placeholders. `error_types` controls which exceptions trigger a wrapped [`UnableToConvertValueError`][hassette.exceptions.UnableToConvertValueError]; other exceptions propagate as `RuntimeError`.

### Simple Registration

`register_simple_type_converter` registers an existing callable (a constructor, a method, or a lambda) without wrapping it in a dedicated function.

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/simple_registration.py"
```

When `fn` is omitted, the target type's constructor is used. `error_message` and `error_types` accept the same arguments as the decorator form.

## Common Patterns

### Enum Conversion

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/pattern_enum.py"
```

The decorator infers `str → FanSpeed` from the function signature. The converter is available immediately at module import time.

### Structured Data

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/pattern_structured.py"
```

`json.loads` raises `json.JSONDecodeError` (a `ValueError` subclass), so the default `error_types=(ValueError,)` catches parse failures automatically.

## Error Handling

When a registered converter raises one of its `error_types`, the registry wraps it in `UnableToConvertValueError`. The wrapped exception includes the source value and both types:

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/conversion_error.py"
```

When no converter is registered and the target type's constructor also fails, the registry raises `UnableToConvertValueError`:

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/missing_converter.py"
```

Custom error messages make failures easier to diagnose. The `{value}` placeholder renders the actual value that failed conversion:

```python
--8<-- "pages/core-concepts/states/snippets/type-registry/custom_error_msg.py"
```

??? note "Inspection and debugging"

    `TypeRegistry` exposes methods for listing and inspecting registered converters. These are primarily useful when debugging unexpected conversion behavior.

    **List all registered converters:**

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

    `TypeRegistry.conversion_map` is a dict keyed by `(from_type, to_type)` tuples. Each value is a `TypeConverterEntry` with `func`, `from_type`, `to_type`, `error_types`, and `error_message` fields.

## See Also

- [State Registry](state-registry.md): domain-to-class mapping
- [Custom States](custom-states.md): defining `value_type` on state models
- [Dependency Injection](../bus/dependency-injection.md): type conversion in custom extractors
