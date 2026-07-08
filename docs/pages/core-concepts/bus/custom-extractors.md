# Custom Extractors

The built-in [`D.*`](dependency-injection.md) annotations cover state values, entity IDs, domains, event data, and event context. Custom extractors handle everything else: a specific key from `service_data`, a nested attribute, or a value computed from multiple event fields.

## Accessors (`A`)

[`A`][hassette.event_handling.accessors] (`from hassette import A`) provides accessor functions that target non-standard event fields. Accessors are the simplest form of custom extraction. They work directly as `Annotated` type metadata, with no additional wrapping.

`A.get_attr_new("brightness")` returns a callable that extracts `brightness` from the new state's attributes. `A.get_service_data_key("entity_id")` extracts a key from `service_data` (the dict of parameters passed to a service call). `A.get_path("payload.data.new_state.attributes.geolocation.locality")` traverses a dotted path. It returns [`MISSING_VALUE`](dependency-injection.md#identity-extractors) — a falsy sentinel — if any segment is absent.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/custom_accessors.py"
```

Accessors also compose with predicates. `P.ValueIs(source=A.get_service_data_key("entity_id"), condition="light.living_room")` filters a service call subscription to a specific target entity without any handler logic. The full predicate reference is in [Filtering](filtering.md).

## Writing an Extractor

A custom extractor is a plain callable that receives the raw event and returns a value. [`AnnotationDetails`][hassette.di.AnnotationDetails] wraps that callable and registers it with the DI system.

`AnnotationDetails` is a frozen dataclass with three fields:

| Field | Type | Required | Purpose |
|---|---|---|---|
| `extractor` | `Callable[[T], Any]` | Yes | Extracts the value from the source object |
| `converter` | `Callable[[Any, Any], Any] \| None` | No | Converts the extracted value to the declared type |
| `source_type` | `type[T] \| None` | No | Overrides the default source type for this extractor |

`Annotated[T, AnnotationDetails(...)]` completes the setup. Hassette discovers the `AnnotationDetails` instance in the `Annotated` metadata automatically at registration time — no explicit registration step needed.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/custom_extractor_own.py"
```

`get_friendly_name` receives the raw [`RawStateChangeEvent`][hassette.events.hass.hass.RawStateChangeEvent] and returns a string. The event exposes `event.payload.data.new_state`, `event.payload.data.old_state`, and `event.payload.data.entity_id`. The `Annotated[str, get_friendly_name]` annotation tells the DI system to call that function for `name` on each invocation.

A plain callable in the `Annotated` metadata position is the simplest form — Hassette wraps it in `AnnotationDetails` automatically. The explicit `AnnotationDetails` form above is needed only when adding a type converter or overriding the default `source_type`.

## Adding Type Conversion

`AnnotationDetails.converter` accepts a function with the signature `(value: Any, to_type: type) -> Any`. The DI system calls it after extraction to convert the raw value to the declared type.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/custom_extractor_converter.py"
```

`extract_timestamp` returns an ISO string. `convert_to_datetime` converts that string to a `datetime`. The `LastChanged` type alias bundles both into a reusable annotation. Any handler parameter typed as `LastChanged` receives a `datetime` with no inline parsing.

Hassette converts standard scalar types (`int`, `float`, `bool`, `str`) automatically — no converter needed for those. `AnnotationDetails.converter` handles conversions specific to a single extractor — types the built-in registry doesn't cover. See [State Conversion](../states/conversion.md) for the full type registry.

## See Also

- [Dependency Injection](dependency-injection.md): built-in `D.*` annotations
- [Filtering](filtering.md): composing accessors with predicates
- [State Conversion](../states/conversion.md): domain-to-model mapping, built-in type converters, and custom converters
