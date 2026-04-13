# Advanced

Most Hassette apps work entirely within the Core Concepts: the Bus, Scheduler, API, and States. The pages in this section are for situations where those building blocks are not enough — when you need to teach Hassette about a new Home Assistant domain, control exactly what type a value converts to, or tune logging to isolate a specific service.

You do not need to read all of these. Start with the one that matches your immediate need.

## Topics

**[Custom States](custom-states.md)** — How to define a typed state class for a Home Assistant domain that Hassette does not know about yet. This is the entry point: define the class, and the State Registry picks it up automatically.

**[State Registry](state-registry.md)** — How Hassette maps domains to state model classes and converts raw Home Assistant state dictionaries to typed Pydantic models. Read this if you need to understand or override the mapping, or if you are seeing unexpected state types at runtime.

**[Type Registry](type-registry.md)** — How Hassette converts raw string values from Home Assistant to Python types (`int`, `bool`, `datetime`, custom types, etc.). Read this when the built-in conversions do not cover your case or you need to register a converter for a custom type.

**[Log Level Tuning](log-level-tuning.md)** — How to set log verbosity independently for each Hassette service. Useful for debugging one component without flooding logs with noise from the rest of the system.

## Prerequisites

These pages assume you are comfortable with [Apps](../core-concepts/apps/index.md) and the [Bus](../core-concepts/bus/index.md). Custom States and the State Registry are closely related — if you are reading one, you will likely need the others.

## See Also

- [API Reference](../../reference/index.md) — full auto-generated reference for all public modules, including the event handling annotations (`A`, `C`, `D`, `P`) and state models.
