# React to a Service Call

You have a primary light and an accent light. Whenever someone adjusts the primary through Home Assistant, the accent should mirror the brightness and color temperature automatically. Subscribing to the `light.turn_on` service call lets your app intercept every adjustment the moment it happens. The source does not matter: HA dashboard, voice assistant, or another automation.

## The Code

```python
--8<-- "pages/recipes/snippets/service_call_reaction.py"
```

## Run It

Save the code as `service_call_reaction.py` in your apps directory and register it in `hassette.toml`, setting your own entities in the `.config` block:

```toml
[hassette.apps.light_group]
filename = "service_call_reaction.py"
class_name = "LightGroupApp"

[hassette.apps.light_group.config]
primary_light = "light.living_room_main"
accent_light = "light.living_room_shelf"
```

The section name (`light_group`) is the app key the `hassette` CLI commands below take via `--app`. [App Configuration](../core-concepts/apps/configuration.md) covers registration in full.

## How It Works

The bus (`self.bus`) delivers Home Assistant events — including service calls — to subscribed handlers. Every `App` gets one, alongside `self.api` and `self.app_config`. Handlers are `async def`; Hassette runs the event loop.

`on_call_service(domain="light", service="turn_on")` subscribes to one specific service. Only `light.turn_on` calls reach the handler; all other services are filtered before the event leaves the bus.

`P` is an alias for [`hassette.event_handling.predicates`](../core-concepts/bus/filtering.md), a module of event-filtering functions. `P.ServiceDataWhere({"entity_id": self.app_config.primary_light})` narrows the subscription further — the predicate compares the `entity_id` field in the incoming call's service data against the configured primary light. Calls targeting any other entity are dropped without invoking the handler.

`name=` on the subscription is required — it labels the listener in logs and in `hassette listener` output. Omitting it raises `ListenerNameRequiredError` at registration time.

The handler receives a [`CallServiceEvent`][hassette.events.hass.hass.CallServiceEvent], the Python object Hassette builds from the raw service call. `event.payload.data.service_data` holds the dict the caller passed to `light.turn_on` — for example, if someone set brightness to 200, `service_data` is `{"brightness": 200, "entity_id": "light.living_room_main"}`. That dict contains whatever combination of `brightness`, `color_temp`, `transition`, and other parameters the caller included. The handler checks each key individually and forwards only the ones present. Keys absent from the original call stay out of the accent call. The accent light keeps its existing values for those attributes.

`primary_light` and `accent_light` are environment-backed config fields. Changing which entities the app watches requires no code change. Set a different value in `hassette.toml` or the corresponding environment variable.

## Verify It's Working

Run these from your project directory while Hassette is running. Adjust the primary light from the Home Assistant dashboard, then check the app's log:

```
hassette log --app light_group --since 5m
```

Each adjustment should produce a log line showing the brightness and color temperature the handler observed. To confirm the subscription fired and was counted, check the listener's invocation history:

```
hassette listener --app light_group
```

The listener named `primary_light_on` should show a non-zero invocation count after each adjustment.

## Variations

**Watch any entity in a group.** Replace the exact entity ID with a glob pattern. The handler then fires for any light in the room:

```python
--8<-- "pages/recipes/snippets/service_call_where.py:where"
```

**React to turn-off too.** Add a second subscription for `service="turn_off"` with its own handler, and call `light.turn_off` on the accent light there. The two subscriptions are independent. Each fires only for its own service type.

## See Also

- [Filtering and Advanced Subscriptions](../core-concepts/bus/filtering.md). Full reference for `on_call_service`, `P.ServiceDataWhere`, and `P.ServiceMatches`.
- [`Bus` Overview](../core-concepts/bus/index.md). `Subscription` options, debounce, throttle, and `once`.
