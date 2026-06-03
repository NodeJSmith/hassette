# Custom Extractors

The built-in [`D.*`](dependency-injection.md) annotations cover state values, entity IDs, domains, event data, and event context. Custom extractors handle everything else: a specific key from `service_data`, a nested attribute, or a value computed from multiple event fields.

## Accessors (`A`)

[`A`][hassette.event_handling.accessors] (`from hassette import A`) provides accessor functions that target non-standard event fields. Accessors are the simplest form of custom extraction. They work directly as `Annotated` type metadata, with no additional wrapping.

`A.get_attr_new("brightness")` returns a callable that extracts `brightness` from the new state's attributes. `A.get_service_data_key("entity_id")` extracts a key from `service_data` on a service call event. `A.get_path("payload.data.new_state.attributes.geolocation.locality")` traverses a dotted path. It returns `MISSING_VALUE` if any segment is absent.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/custom_accessors.py"
```

Accessors also compose with predicates. `P.ValueIs(source=A.get_service_data_key("entity_id"), condition="light.living_room")` filters a service call subscription to a specific target entity without any handler logic. The full predicate reference is in [Filtering](filtering.md).

## Writing an Extractor

A custom extractor is a plain callable that receives the raw event and returns a value. [`AnnotationDetails`][hassette.event_handling.dependencies.AnnotationDetails] wraps that callable and registers it with the DI system.

`AnnotationDetails` is a frozen dataclass with two fields:

| Field | Type | Required | Purpose |
|---|---|---|---|
| `extractor` | `Callable[[T], Any]` | Yes | Extracts the value from the event |
| `converter` | `Callable[[Any, Any], Any] \| None` | No | Converts the extracted value to the declared type |

Placing an `AnnotationDetails` instance inside `Annotated[T, AnnotationDetails(...)]` completes the setup. `extract_from_signature` in `hassette.bus.extraction` scans handler parameters at registration time. It finds `Annotated` types carrying `AnnotationDetails` and builds the resolution plan automatically.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/custom_extractor_own.py"
```

`get_friendly_name` receives the raw [`RawStateChangeEvent`][hassette.events.hass.hass.RawStateChangeEvent] and returns a string. The `Annotated[str, get_friendly_name]` annotation tells the DI system to call that function for `name` on each invocation. A plain callable in the `Annotated` metadata position is shorthand. `extract_from_annotated` wraps it in `AnnotationDetails` automatically.

## How Built-In Extractors Work

??? note "Internals: how `D.StateNew` is defined"

    Every built-in annotation in `D` is an `Annotated` type alias carrying an `AnnotationDetails` instance. `D.StateNew` is defined as:

    ```python
    StateNew: TypeAlias = Annotated[
        StateT,
        AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_new)),
    ]
    ```

    `A.get_state_object_new` is an accessor that reads `event.payload.data.new_state` and converts it via the State Registry. `ensure_present` wraps it to raise [`DependencyResolutionError`][hassette.exceptions.DependencyResolutionError] if the value is missing. A missing value skips the handler rather than passing `None`. The `Annotated` wrapper is what `extract_from_annotated` looks for when scanning the handler signature.

    The `A.get_attr_new` pattern used in custom extractors follows the same structure:

    ```python
    --8<-- "pages/core-concepts/bus/snippets/dependency-injection/custom_extractor_builtin.py"
    ```

    `extract_from_annotated` accepts either a bare callable or a full `AnnotationDetails` instance in the `Annotated` metadata position. Both produce the same resolution behavior. The bare callable form is a convenience shorthand.

## Adding Type Conversion

`AnnotationDetails.converter` accepts a function with the signature `(value: Any, to_type: type) -> Any`. The DI system calls it after extraction to convert the raw value to the declared type.

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/custom_extractor_converter.py"
```

`extract_timestamp` returns an ISO string. `convert_to_datetime` converts that string to a `datetime`. The `LastChanged` type alias bundles both into a reusable annotation. Any handler parameter typed as `LastChanged` receives a `datetime` with no inline parsing.

The [Type Registry](../states/type-registry.md) provides built-in converters for standard scalar types. `AnnotationDetails.converter` handles conversions specific to a single extractor. It covers types the registry does not handle, or conversions that need context from the extractor itself.

## See Also

- [Dependency Injection](dependency-injection.md): built-in `D.*` annotations
- [Filtering](filtering.md): composing accessors with predicates
- [Type Registry](../states/type-registry.md): built-in type converters and how to register custom ones
- [State Registry](../states/state-registry.md): domain-to-model mapping
