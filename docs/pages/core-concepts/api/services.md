# Calling Services

`self.api` calls any Home Assistant service: turning devices on and off, sending notifications, running scripts, or firing any action a service domain exposes.

## Turning Things On and Off

`turn_on`, `turn_off`, and `toggle_service` cover the most common case. Each accepts an entity ID and dispatches the corresponding `homeassistant.*` service call.

```python
--8<-- "pages/core-concepts/api/snippets/api_helpers.py"
```

All three default to the `homeassistant` domain (`homeassistant.turn_on`, `homeassistant.turn_off`, `homeassistant.toggle`). Home Assistant 2024.x deprecated those generic services in favor of domain-specific ones. `domain="light"` routes the call to `light.turn_on` instead. `turn_on` also accepts `**data` keyword arguments, so light-specific fields like `brightness` and `color_name` pass through to the service call unchanged.

## Generic Service Calls

`call_service(domain, service, target=None, return_response=False, **data)` handles any service. Service data passes through as keyword arguments. `brightness=200` becomes `service_data` on the wire. The `target` parameter accepts an entity ID, area, or device dict for services that support targeting.

```python
--8<-- "pages/core-concepts/api/snippets/api_call_service.py"
```

## Getting a Response

Some services return data. `weather.get_forecasts` returns forecast arrays; `conversation.process` returns a reply. Setting `return_response=True` tells Home Assistant to include the response payload. Without it, `call_service` returns `None`.

```python
--8<-- "pages/core-concepts/api/snippets/api_response.py"
```

## See Also

- [Entities & States](entities.md) for reading state after a service call.
- [`Bus`](../bus/index.md) for subscribing to service calls from other sources via `on_call_service`.
