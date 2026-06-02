# API — Services

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Call a Home Assistant service from their app — turn on a light, send a notification, trigger an automation.

## What was cut (and where it goes)

- Nothing significant cut. The existing page is already lean. The rewrite restructures to lead with the most common pattern (convenience helpers) before the generic `call_service`, since most readers want to turn something on/off and the convenience helpers are the right answer for that.

## Outline

### H2: (Opening — no heading)
One sentence: the API calls Home Assistant services — any action a service domain exposes (turning devices on/off, sending notifications, running scripts).

### H2: Turning Things On and Off
`turn_on(entity_id)`, `turn_off(entity_id)`, `toggle_service(entity_id)` cover the most common case. Show the simplest snippet first.

Snippet: `turn_on("light.porch")`, `turn_off("switch.fan")`.

Note: these convenience methods call the `homeassistant` domain service by default. For domain-specific service data (e.g., `brightness` for lights), pass `domain="light"` explicitly.

### H2: Generic Service Calls
`call_service(domain, service, target=None, return_response=False, **data)` handles any service. Service data is passed as keyword arguments, not a positional dict. `target` is a separate parameter for entity/area/device targeting.

Snippet: `call_service("notify", "mobile_app", message="Motion detected")` and a light example with `brightness` and `color_temp`.

### H2: Getting a Response
Some services return data (e.g., `weather.get_forecasts`). Pass `return_response=True` to receive a `ServiceResponse` dict. Without it, the return value is `None`.

Snippet: service call with `return_response=True`.

### H2: See Also
- Entities & States (reading state after a service call)
- Bus `on_call_service` (reacting to service calls from other sources)

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `api_call_service.py` | Keep | Generic call_service |
| `api_helpers.py` | Keep | Convenience helpers |
| `api_response.py` | Keep | Service response |

## Cross-Links

- **Links to:** API overview, Entities & States, Bus (on_call_service)
- **Linked from:** API overview, Apps overview, Recipes
