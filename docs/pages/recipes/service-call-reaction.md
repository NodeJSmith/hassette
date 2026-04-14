# React to a Service Call

Intercept a Home Assistant service call and run custom logic in response. This recipe mirrors brightness and color temperature from a primary light to an accent light whenever someone turns the primary light on.

## The code

```python
--8<-- "pages/recipes/snippets/service_call_reaction.py"
```

## How it works

- `on_call_service(domain="light", service="turn_on", ...)` subscribes only to `light.turn_on` calls — no other service types reach the handler.
- `P.ServiceDataWhere({"entity_id": ...})` narrows the subscription further, so the handler only fires when the call targets the configured primary light.
- The handler receives a `CallServiceEvent`. `event.payload.data.service_data` is the dict of arguments the caller passed — brightness, color temperature, transitions, and so on.
- The handler forwards whichever parameters were present to `light.turn_on` on the accent light, leaving out keys that were not set in the original call.
- Config fields (`primary_light`, `accent_light`) let you change entity IDs via environment variables (`LIGHT_GROUP_PRIMARY_LIGHT`, `LIGHT_GROUP_ACCENT_LIGHT`) without touching code.

## Variations

**Watch any entity in a group** — replace the exact entity ID in `ServiceDataWhere` with a glob pattern:

```python
where=P.ServiceDataWhere({"entity_id": "light.living_room_*"})
```

**React to turn-off too** — add a second subscription for `service="turn_off"` pointing to its own handler, and call `light.turn_off` on the accent light there.

## See Also

- [Filtering & Advanced Subscriptions](../core-concepts/bus/filtering.md) — full reference for `on_call_service`, `P.ServiceDataWhere`, and `P.ServiceMatches`
- [Bus Overview](../core-concepts/bus/index.md) — subscription options, debounce, throttle, and `once`
