# Custom State Classes

Hassette's dynamic state registry allows you to define custom state classes for domains that aren't included in the core framework. This is useful for:

- Custom integrations and components in your Home Assistant instance
- Third-party integrations not yet supported by Hassette
- Specialized state handling with custom attributes or methods

## Basic Custom State Class

To create a custom state class, inherit from one of the base state classes and define a `domain` field with a `Literal` type:

```python
--8<-- "pages/advanced/snippets/custom-states/basic_custom_state.py"
```

That's it! The state class notifies the registry upon creation and is immediately available for use.

## Choosing a Base Class

Hassette provides several base classes to inherit from, depending on your entity's state value type:

### StringBaseState
For entities with string state values (most common):

```python
--8<-- "pages/advanced/snippets/custom-states/string_base_state.py"
```

### NumericBaseState
For entities with numeric state values - stored as `Decimal` internally (supports int, float, Decimal):

```python
--8<-- "pages/advanced/snippets/custom-states/numeric_base_state.py"
```

### BoolBaseState
For entities with boolean state values (`True`/`False`, automatically converts `"on"`/`"off"`):

```python
--8<-- "pages/advanced/snippets/custom-states/bool_base_state.py"
```

### DateTimeBaseState
For entities with datetime state values (supports `ZonedDateTime`, `PlainDateTime`, `Date`):

```python
--8<-- "pages/advanced/snippets/custom-states/datetime_base_state.py"
```

### TimeBaseState
For entities with time-only state values:

```python
--8<-- "pages/advanced/snippets/custom-states/time_base_state.py"
```

### Define your own
For entities with state values that don't fit the predefined base classes, you can inherit directly from BaseState and provide the type parameter for the state value and `value_type` class variable:

```python
--8<-- "pages/advanced/snippets/custom-states/define_your_own.py"
```

The `value_type` class variable is used by Hassette to validate state values at runtime. It should include all acceptable types for the state value, including `None` if the state can be unset.

## Adding Custom Attributes

You can define custom attributes specific to your domain by creating an attributes class:

```python
--8<-- "pages/advanced/snippets/custom-states/adding_custom_attributes.py"
```

## Using Custom States in Apps

Once defined, custom state classes work seamlessly with Hassette's APIs:

### Via get_states()

```python
from hassette import App
from .my_states import RedditState

class MyApp(App):
    async def on_initialize(self):
        # Get all reddit entities
        reddit_states = self.states[RedditState]

        for entity_id, state in reddit_states:
            print(f"{entity_id}: {state.value}")
            if state.attributes.karma:
                print(f"  Karma: {state.attributes.karma}")
```

### With Dependency Injection

```python
--8<-- "pages/advanced/snippets/state-registry/basic_custom_state_usage.py"
```

### Direct API Access

```python
reddit_state = await self.api.get_state("reddit.my_account")
assert isinstance(reddit_state, RedditState)
if reddit_state.attributes.subreddit:
    print(f"Subreddit: {reddit_state.attributes.subreddit}")
```

## Runtime vs Type-Time Access

For known domains (defined in Hassette or in the `.pyi` stub), you can use property-style access:

```python
# Known domains (autocomplete works)
for entity_id, light in self.states.light:
    print(light.attributes.brightness)
```

For custom domains, use `states[<class>]` for full type checking:

```python
# Custom domains (use states[<class>] for typing)
custom_states = self.states[MyCustomState]
for entity_id, state in custom_states:
    print(state.value)
```

# Works at runtime but static analysis sees BaseState
```
for entity_id, state in self.states.my_custom_domain:
    print(state.value)  # state is typed as BaseState
```

## Complete Example

Here's a complete example with a custom integration:

```python
--8<-- "pages/advanced/snippets/custom-states/complete_example.py"
```

## Best Practices

1. **One domain per state class** - Each state class should handle exactly one domain
2. **Use Literal for domain** - Always use `Literal["domain_name"]` to enable auto-registration
3. **Choose the right base class** - Match the base class to your entity's state value type
4. **Document your attributes** - Add docstrings to custom attribute classes
5. **Use typing** - Leverage type hints throughout for better IDE support and type checking

## Troubleshooting

### State class not registering

If your custom state class isn't being recognized:

1. **Check the domain field** - Ensure you have `domain: Literal["your_domain"]`
2. **Ensure that you are calling `__init_subclass__`** - If you override `__init_subclass__`, make sure to call `super().__init_subclass__()`
3. **Check for errors** - Look for registration errors in debug logs

### Type hints not working

If IDE autocomplete isn't working:

1. **Use `states[<class>]`** - For custom domains, use `self.states[CustomState]`

### State conversion fails

If state conversion is failing:

1. **Check the base class** - Ensure it matches your entity's state value type
2. **Validate attributes** - Make sure custom attributes use proper Pydantic field types
3. **Check Home Assistant data** - Verify the actual state data structure from Home Assistant
