# Calling Services

The API provides methods to invoke Home Assistant services.

!!! warning "Service methods must be awaited"
    `call_service`, `fire_event`, `set_state`, `turn_on`, `turn_off`, and `toggle_service` all return coroutines. Without `await`, the call is never sent and no error is raised. A forgotten `await` produces a [`HassetteForgottenAwaitWarning`][hassette.exceptions.HassetteForgottenAwaitWarning] naming the offending app — see [Forgotten `await`](../../troubleshooting.md#forgotten-await) for diagnosis. To catch this at edit time, [enable Pyright](../../troubleshooting.md#enabling-pyright).

## Basic Service Calls

Use `call_service` for generic service invocations.

```python
--8<-- "pages/core-concepts/api/snippets/api_call_service.py"
```

## Convenience Helpers

Common operations like turning entities on/off have dedicated helpers. They save you from specifying the domain and service name separately — `turn_on("light.porch")` is more readable than `call_service("homeassistant", "turn_on", entity_id="light.porch")` and less error-prone.

```python
--8<-- "pages/core-concepts/api/snippets/api_helpers.py"
```

These methods forward arguments to `call_service` while providing a cleaner syntax.

## Service Responses

Service calls return a response dictionary (if the service provides one).

```python
--8<-- "pages/core-concepts/api/snippets/api_response.py"
```

## See Also

- [Retrieving Entities & States](entities.md) - Get entity and state data
- [Utilities & History](utilities.md) - Templates, history, and advanced features
- [Bus](../bus/index.md) - Subscribe to service call events
