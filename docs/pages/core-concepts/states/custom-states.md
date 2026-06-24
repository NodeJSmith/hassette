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

[`NumericBaseState`][hassette.models.states.base.NumericBaseState] declares `value_type = (int, float, Decimal, type(None))`. The codec converts the raw state string to a numeric type — whole-number strings become `int`, decimal strings become `float`. `int`, `float`, and `Decimal` inputs pass through directly. Unknown or unavailable states produce `None`.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/numeric_base_state.py"
```

### `BoolBaseState`: `bool` value

[`BoolBaseState`][hassette.models.states.base.BoolBaseState] declares `value_type = (bool, type(None))`. The codec maps `"on"` to `True` and `"off"` to `False` using the registered `str → bool` converter. Unknown or unavailable states produce `None`.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/bool_base_state.py"
```

### `DateTimeBaseState`: `ZonedDateTime`, `PlainDateTime`, or `Date` value

[`DateTimeBaseState`][hassette.models.states.base.DateTimeBaseState] declares a datetime `value_type`. The codec parses the raw state string into a [`whenever`](https://whenever.readthedocs.io/) datetime type (`from whenever import ZonedDateTime` — Hassette's date/time library). The exact type depends on the string format from Home Assistant.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/datetime_base_state.py"
```

### `TimeBaseState`: `Time` value

[`TimeBaseState`][hassette.models.states.base.TimeBaseState] parses the raw state string into a `whenever.Time` value.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/time_base_state.py"
```

### Custom value type: inherit `BaseState` directly

When no built-in base class fits, a class can inherit from `BaseState[T]` directly. The `value_type` class variable declares the accepted types. The codec coerces state values against `value_type` at runtime using `TypeRegistry`.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/define_your_own.py"
```

`value_type` should include `type(None)` when the state can be unset.

## Adding Typed Attributes

Domain-specific attributes beyond `value` belong in an attributes class that inherits from [`AttributesBase`][hassette.models.states.base.AttributesBase] — a Pydantic model subclass where fields map to HA attribute keys by name. The `attributes` field on the state class accepts this class, overriding the default.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/adding_custom_attributes.py"
```

Fields on the attributes class are optional by default when typed with `| None`. Hassette passes through any undeclared attribute keys. They remain accessible via `state.attributes.extras`.

## Using Custom States in Apps

### Via `self.states[CustomStateClass]`

`self.states[RedditState]` returns a [`DomainStates`][hassette.state_manager.state_manager.DomainStates] collection typed to `RedditState`. Iteration yields `(entity_id, state)` pairs where each `state` is a fully converted `RedditState` instance.

```python
--8<-- "pages/core-concepts/states/snippets/custom-states/via_get_states.py"
```

### With Dependency Injection

`D.StateNew[RedditState]` in a handler parameter tells Hassette to convert the incoming event's new state to a `RedditState` before calling the handler. [Dependency Injection](../../core-concepts/bus/dependency-injection.md) covers the full parameter reference.

```python
--8<-- "pages/core-concepts/states/snippets/state-registry/basic_custom_state_usage.py"
```

## Troubleshooting

**Class not registering.** The `domain` field must use `Literal["domain_name"]`, not `str`. A plain `str` annotation gives the registry no value to register at class creation time. If `__init_subclass__` is overridden, it must call `super().__init_subclass__()` so registration still runs.

**Type hints not working.** Property-style access (`self.states.my_domain`) is only available for domains declared in Hassette's `.pyi` stub. Custom domains always use `self.states[CustomStateClass]` for full type checking.

**Conversion fails.** The base class must match the entity's actual value type in Home Assistant. The raw state data is visible via `hassette log --app <key>` or the HA developer tools, which confirms the format before a base class is selected.

## See Also

- [State Conversion](conversion.md): how automatic registration works, domain overrides, and custom value converters
- [Dependency Injection](../bus/dependency-injection.md): injecting typed states into event handlers
