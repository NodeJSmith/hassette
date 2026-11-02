# Custom States

Hassette auto-generates typed state classes for standard Home Assistant domains. For custom integrations or third-party add-ons, a custom state class maps an unrecognized domain to a typed Python model. The [State Registry](conversion.md) — Hassette's internal mapping from domain strings to state classes — picks up the class automatically at definition time via `__init_subclass__`.

## Defining a Custom State

A custom state class inherits from one of Hassette's base state classes. The `domain` field takes a `Literal` with the exact domain string from Home Assistant.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/basic_custom_state.py"
```

Registration happens via `__init_subclass__`, so no explicit call is needed. Each class maps to one domain. Assigning the same `Literal` value to two classes overwrites the first registration.

`Literal["my_custom_domain"]` is required. A plain `str` annotation carries no value at class definition time, so the registry cannot extract the domain name automatically.

## Choosing a Base Class

Each base class determines the Python type of `value` on the resulting state object.

### `StringBaseState`: `str` value

[`StringBaseState`][hassette.models.states.base.StringBaseState] is the most common choice. It passes through the raw HA state string with no conversion.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/string_base_state.py"
```

### `NumericBaseState`: numeric value

[`NumericBaseState`][hassette.models.states.base.NumericBaseState] declares `value_type = (int, float, Decimal, type(None))`. The conversion pipeline converts the raw state string to a numeric type — whole-number strings become `int`, decimal strings become `float`. `int`, `float`, and `Decimal` inputs pass through directly. Unknown or unavailable states produce `None`.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/numeric_base_state.py"
```

### `BoolBaseState`: `bool` value

[`BoolBaseState`][hassette.models.states.base.BoolBaseState] declares `value_type = (bool, type(None))`. The conversion pipeline maps `"on"` to `True` and `"off"` to `False` using the registered `str → bool` converter. Unknown or unavailable states produce `None`.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/bool_base_state.py"
```

### `DateTimeBaseState`: `ZonedDateTime` value

[`DateTimeBaseState`][hassette.models.states.base.DateTimeBaseState] declares a datetime `value_type`. The conversion pipeline parses the raw state string into a [`whenever`](https://whenever.readthedocs.io/) datetime type (`from whenever import ZonedDateTime` — Hassette's date/time library). Every string format Home Assistant sends (offset-aware, naive, or date-only) becomes a `ZonedDateTime`; naive and date-only strings assume the configured timezone.

The `value` annotation is `ZonedDateTime | None`. A `None` value means the entity is unknown or unavailable.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/datetime_base_state.py"
```

Direct `model_validate()` calls skip the conversion pipeline, and so does a `BaseEntity` validating its nested state. Those paths accept only `None`, a `ZonedDateTime`, or a string with an IANA timezone, such as `2026-10-01T08:00:00-05:00[America/Chicago]`. Offset-aware, naive, and date-only strings raise `ValidationError` there. [`StateRegistry.try_convert_state()`](conversion.md#the-conversion-pipeline) converts a raw state dict holding those strings.

`PlainDateTime` and `Date` objects fail on every path, including the pipeline. Converting them to `ZonedDateTime` first avoids the failure; `PlainDateTime.assume_tz()` does this for a known timezone.

### `TimeBaseState`: `Time` value

[`TimeBaseState`][hassette.models.states.base.TimeBaseState] parses the raw state string into a `whenever.Time` value.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/time_base_state.py"
```

### Custom value type: inherit `BaseState` directly

When no built-in base class fits, a class can inherit from `BaseState[T]` directly. The `value_type` class variable declares the accepted types. The conversion pipeline coerces state values against `value_type` at runtime using [`TypeRegistry`](conversion.md#value-conversion).

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/define_your_own.py"
```

A state that can be unset (`unknown` or `unavailable`) parameterizes the base class with `| None`, as in `BaseState[MyValueType | None]`, and includes `type(None)` in `value_type`. The generic parameter is what Pydantic validates `value` against; without `| None`, an unavailable entity fails conversion.

## Adding Typed Attributes

Domain-specific attributes beyond `value` belong in an attributes class that inherits from [`AttributesBase`][hassette.models.states.base.AttributesBase] — a Pydantic model subclass where fields map to HA attribute keys by name. The `attributes` field on the state class accepts this class, overriding the default.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/adding_custom_attributes.py"
```

Fields on the attributes class are optional by default when typed with `| None`. Hassette passes through any undeclared attribute keys. They remain accessible via `state.attributes.extras`.

## Using Custom States in Apps

A state class lives in the app file that uses it, or in a module in the apps directory. The snippets below import `RedditState` from `my_states.py`, a module beside the app file that holds the classes from [Adding Typed Attributes](#adding-typed-attributes).

Hassette imports app files as modules of one package named after the apps directory. `from .my_states import RedditState` resolves from any app file beside `my_states.py`. Without that module, the import raises `ModuleNotFoundError`. A single-file app defines the class in the app file and omits the import.

Registration runs when Python imports the defining module. Hassette imports only the app files named in its config, so an app file has to import a separate state module.

### Via `self.states[CustomStateClass]`

`self.states[RedditState]` returns a [`DomainStates`][hassette.state_manager.state_manager.DomainStates] collection typed to `RedditState`. `.items()` yields `(entity_id, state)` pairs where each `state` is a fully converted `RedditState` instance. Iterating the collection directly yields entity IDs, like a dict.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/via_get_states.py"
```

### With Dependency Injection

`D.StateNew[RedditState]` in a handler parameter tells Hassette to convert the incoming event's new state to a `RedditState` before calling the handler. [Dependency Injection](../../core-concepts/bus/dependency-injection.md) covers the full parameter reference.

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/basic_custom_state_usage.py"
```

When `reddit.my_account` changes, the handler logs `karma` from the typed `attributes` field.

## Troubleshooting

**Class not registering.** The `domain` field must use `Literal["domain_name"]`, not `str`. A plain `str` annotation gives the registry no value to register at class creation time. If `__init_subclass__` is overridden, it must call `super().__init_subclass__()` so registration still runs. A class in a module nothing imports never registers, so `self.states.get()` returns a plain `BaseState` for its entities. Importing the module from an app file fixes this, and `self.state_registry.resolve(domain="reddit")` then returns the class.

**Type hints not working.** Property-style access (`self.states.my_domain`) is only available for domains declared in Hassette's `.pyi` stub. Custom domains always use `self.states[CustomStateClass]` for full type checking.

**Conversion fails.** The base class must match the entity's actual value type in Home Assistant. The raw state data is visible via `hassette log --app <key>` or the HA developer tools, which confirms the format before a base class is selected.

## See Also

- [State Conversion](conversion.md): how automatic registration works, domain overrides, and custom value converters
- [Dependency Injection](../bus/dependency-injection.md): injecting typed states into event handlers
