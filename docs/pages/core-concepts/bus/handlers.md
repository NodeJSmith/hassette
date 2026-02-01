# Writing Event Handlers

Once you've subscribed to an event, you need a handler to process it. Hassette handlers are flexible, supporting dependency injection (DI), custom keyword arguments, and various event patterns.

## Event Model

Every event you receive from the bus is an [`Event`][hassette.events.base.Event] dataclass with two main fields:

- `topic` - a string identifier describing what happened, such as `hass.event.state_changed`.
- `payload` - an untyped object containing event-specific data.

!!! question "Why is the payload untyped?"

    You may be wondering why the event payload is untyped if Hassette is focused on strong typing. The reason for this is to avoid the overhead of converting every
    event payload to a typed object when the majority of payloads will never be used.

    Instead of converting *every* event payload, Hassette converts at the user boundary, such as when using Dependency Injection (DI) or
    accessing states through [DomainStates][hassette.state_manager.state_manager.DomainStates] (e.g. `self.states.light`).


## Dependency Injection

Hassette uses dependency injection (DI) to provide event data to your handlers. The type annotations on your handler parameters tell Hassette what data to extract from the event.

### Basic Patterns

**Option 1: Receive the full event in raw form** (simplest):
This gives you the raw event object, with the state data in untyped dicts.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_raw_event.py"
```

**Option 2: Receive full event with typed state objects** (better):
This gives you typed state objects for easier access to attributes.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_typed_event.py"
```

**Option 3: Extract specific data** (recommended):

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_extract_data.py"
```

**Option 4: No event data needed**:

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_no_data.py"
```

### Passing Custom Arguments

You can pass additional arguments to your handler using `kwargs` when subscribing. These are injected alongside event dependencies.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_custom_args.py"
```

### Available Dependencies

Common dependencies are imported from `hassette.dependencies` (aliased as `D`).

#### State Extractors
- `StateNew[T]` - Extract the new state object, raises if missing
- `StateOld[T]` - Extract the old state object, raises if missing
- `MaybeStateNew[T]` - Extract new state, allows None
- `MaybeStateOld[T]` - Extract old state, allows None

#### Identity Extractors
- `EntityId` - Extract the entity ID
- `Domain` - Extract the domain
- `EventContext` - Extract the Home Assistant event context

For a complete list and advanced usage, see the [Dependency Injection](../../advanced/dependency-injection.md) guide.

### Restrictions

!!! warning "Handler Signature Rules"
    Handlers **cannot** use:

    - Positional-only parameters (parameters before `/`)
    - Variadic positional arguments (`*args`)

    These restrictions ensure unambiguous parameter injection.

## Combining Multiple Dependencies

You can extract multiple pieces of data in a single handler:

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_multiple_dependencies.py"
```
