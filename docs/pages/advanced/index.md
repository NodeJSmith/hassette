# Advanced Concepts

Hassette does a lot under the hood to make building Home Assistant automations easier, safer, and more maintainable. In this section, we’ll explore some of the more advanced features and patterns you can leverage in your apps.

These features are:

- [Dependency injection](dependency-injection.md)
- [Custom states](custom-states.md)
- [The State Registry](state-registry.md)
- [The Type Registry](type-registry.md)

## Dependency Injection

Hassette uses dependency injection to extract and provide event data to your event handlers, handling extraction and type conversion on your behalf. This allows you to write cleaner, more focused event handlers without worrying about the details of data extraction and validation.

There are some built in DI providers for common use cases, but the system is also extensible, allowing you to create your own providers for custom data types or sources.

For example, `StateNew` is a built-in provider that extracts the new state from a state change event and converts it into the appropriate `State` object for your handler. If you want to extract only the `brightness` attribute from a new `LightState` though, there is no built-in provider for that, so you would need to create a custom provider.

This is as simple as using the [`Annotated`][typing.Annotated] type hint to specify a type and an extractor. Hassette does have an [accessor][hassette.event_handling.accessors] module that has built-in extractors, so for this example you could use `get_state_attr_new`. Combining these tools allows you to create powerful, reusable DI providers for your specific needs.

Read more in the [Dependency Injection guide](dependency-injection.md).

## Custom States

Hassette uses Pydantic models to represent Home Assistant [`states`](https://www.home-assistant.io/docs/configuration/state_object/). This allows safe access to state attributes with type checking and validation, reducing the risk of runtime errors and making your automations more robust.

Home Assistant has many built in states, but many many more states that come from integrations and custom components (e.g., [`HACS` third party integrations](https://www.hacs.xyz/)). Hassette will never be able to include every possible state out of the box, which is where custom states come in.

Custom states can be defined as simply as creating a new State class from [`BaseState`][hassette.models.states.base.BaseState] or one if it's subclasses. `BaseState`
uses `__init_subclass__` to automatically register the class with the [State Registry][hassette.core.state_registry.StateRegistry] based on its `domain` attribute. This means that once you have defined the class, it will be used automatically whenever a state with the matching domain is encountered in your automations.

There is a dedicated [Custom States guide](custom-states.md) that goes into more detail on how to define and use custom states in your Hassette apps.

## Registries

There are two registries in Hassette, handling different concerns. The [`StateRegistry`][hassette.core.state_registry.StateRegistry] handles state classes, while the [`TypeRegistry`][hassette.core.type_registry.TypeRegistry] handles type conversions and custom types.

### State Registry

The State Registry contains a map of state domain names to their corresponding State classes. This allows Hassette to automatically use the correct State class whenever it encounters a state with a matching domain in your automations. In the future it will also be able to support additional discriminators, such as combining `domain` and `device_class` to select the appropriate State class for more specific cases.

The State Registry generally does not need to be interacted with directly, as the `__init_subclass__` hook automatically registers new State classes when they are defined.

You can read more about the State Registry in the [State Registry guide](state-registry.md).

### Type Registry

The Type Registry contains a map of custom types to their corresponding type converters. This allows Hassette to automatically convert data to the correct type whenever it encounters a type that has a registered converter in your automations.

The `TypeRegistry` allows for manually registering new type converters, giving you full control over how custom types are handled in your automations. You can also
access the registry directly if needed, which can allow you to convert between types without having to rewrite your type conversion logic.

You can read more about the Type Registry in the [Type Registry guide](type-registry.md).
