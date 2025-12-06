# Custom State Classes

Hassette's dynamic state registry allows you to define custom state classes for domains that aren't included in the core framework. This is useful for:

- Custom integrations and components in your Home Assistant instance
- Third-party integrations not yet supported by Hassette
- Specialized state handling with custom attributes or methods

## Basic Custom State Class

To create a custom state class, inherit from one of the base state classes and define a `domain` field with a `Literal` type:

```python
from typing import Literal
from hassette.models.states.base import StringBaseState

class MyCustomState(StringBaseState):
    """State class for my_custom_domain entities."""

    domain: Literal["my_custom_domain"]
```

That's it! The state class will automatically register itself when the module is imported, and you can use it throughout your app.

## Choosing a Base Class

Hassette provides several base classes to inherit from, depending on your entity's state value type:

### StringBaseState
For entities with string state values (most common):

```python
from hassette.models.states.base import StringBaseState

class LauncherState(StringBaseState):
    domain: Literal["launcher"]
```

### NumericBaseState
For entities with numeric state values - stored as `Decimal` internally (supports int, float, Decimal):

```python
from hassette.models.states.base import NumericBaseState

class CustomSensorState(NumericBaseState):
    domain: Literal["custom_sensor"]
```

### BoolBaseState
For entities with boolean state values (`True`/`False`, automatically converts `"on"`/`"off"`):

```python
from hassette.models.states.base import BoolBaseState

class CustomBinaryState(BoolBaseState):
    domain: Literal["custom_binary"]
```

### DateTimeBaseState
For entities with datetime state values (supports `ZonedDateTime`, `PlainDateTime`, `Date`):

```python
from hassette.models.states.base import DateTimeBaseState

class TimestampState(DateTimeBaseState):
    domain: Literal["timestamp"]
```

### TimeBaseState
For entities with time-only state values:

```python
from hassette.models.states.base import TimeBaseState

class TimeOnlyState(TimeBaseState):
    domain: Literal["time_only"]
```

## Adding Custom Attributes

You can define custom attributes specific to your domain by creating an attributes class:

```python
from typing import Literal
from pydantic import Field
from hassette.models.states.base import StringBaseState, AttributesBase

class RedditAttributes(AttributesBase):
    """Attributes for Reddit entities."""

    subreddit: str | None = Field(default=None)
    post_count: int | None = Field(default=None)
    karma: int | None = Field(default=None)

class RedditState(StringBaseState):
    """State class for reddit domain entities."""

    domain: Literal["reddit"]
    attributes: RedditAttributes  # Override attributes type
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
        reddit_states = self.states.get_states(RedditState)

        for entity_id, state in reddit_states:
            print(f"{entity_id}: {state.value}")
            if state.attributes.karma:
                print(f"  Karma: {state.attributes.karma}")
```

### With Dependency Injection

```python
from hassette import App, dependencies as D
from .my_states import RedditState

class MyApp(App):
    async def on_initialize(self):
        self.bus.on_state_change(
            "reddit.my_account",
            handler=self.on_reddit_change
        )

    async def on_reddit_change(
        self,
        new_state: D.StateNew[RedditState],
        karma: Annotated[int | None, D.AttrNew("karma")]
    ):
        print(f"New karma: {karma}")
```

### Direct API Access

```python
reddit_state = await self.api.get_state("reddit.my_account", RedditState)
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

For custom domains, use `get_states()` for full type safety:

```python
# Custom domains (use get_states for typing)
custom_states = self.states.get_states(MyCustomState)
for entity_id, state in custom_states:
    print(state.value)
```

You can also access custom domains dynamically via property access, but you'll get `BaseState` typing at runtime:

```python
# Works at runtime but loses specific typing
for entity_id, state in self.states.my_custom_domain:
    print(state.value)  # state is typed as BaseState
```

## Complete Example

Here's a complete example with a custom integration:

```python
# my_states.py
from typing import Literal
from pydantic import Field
from hassette.models.states.base import StringBaseState, AttributesBase

class ImageAttributes(AttributesBase):
    """Attributes for image entities."""

    url: str | None = Field(default=None)
    width: int | None = Field(default=None)
    height: int | None = Field(default=None)
    content_type: str | None = Field(default=None)

class ImageState(StringBaseState):
    """State class for image domain."""

    domain: Literal["image"]
    attributes: ImageAttributes


# my_app.py
from hassette import App, dependencies as D
from .my_states import ImageState

class ImageMonitorApp(App):
    async def on_initialize(self):
        # Monitor all image entities
        self.bus.on_state_change(
            entity_id="image.*",  # Glob pattern
            handler=self.on_image_change
        )

    async def on_image_change(
        self,
        new_state: D.StateNew[ImageState],
        entity_id: D.EntityId,
    ):
        attrs = new_state.attributes
        self.logger.info(
            "Image %s updated: %dx%d, %s",
            entity_id,
            attrs.width or 0,
            attrs.height or 0,
            attrs.content_type or "unknown"
        )
```

## Best Practices

1. **One domain per state class** - Each state class should handle exactly one domain
2. **Use Literal for domain** - Always use `Literal["domain_name"]` to enable auto-registration
3. **Choose the right base class** - Match the base class to your entity's state value type
4. **Document your attributes** - Add docstrings to custom attribute classes
5. **Import early** - Ensure your custom state modules are imported before any state conversion happens
6. **Use typing** - Leverage type hints throughout for better IDE support and type checking

## Troubleshooting

### State class not registering

If your custom state class isn't being recognized:

1. **Check the domain field** - Ensure you have `domain: Literal["your_domain"]`
2. **Import the module** - The class must be imported for registration to occur
3. **Check for errors** - Look for registration errors in debug logs

### Type hints not working

If IDE autocomplete isn't working:

1. **Use get_states()** - For custom domains, use `self.states.get_states(CustomState)`
2. **Add to stub file** - For permanent custom domains, you can add them to `hassette/states.pyi`

### State conversion fails

If state conversion is failing:

1. **Check the base class** - Ensure it matches your entity's state value type
2. **Validate attributes** - Make sure custom attributes use proper Pydantic field types
3. **Check Home Assistant data** - Verify the actual state data structure from Home Assistant
