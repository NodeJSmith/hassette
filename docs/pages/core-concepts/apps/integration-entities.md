# Buttons, Switches and Sensors

`self.integration` declares Home Assistant entities that belong to an app instance: buttons that run a handler when pressed, switches whose state the app controls, and sensors whose value the app sets. The [Hassette integration](../../getting-started/home-assistant-integration.md) shows them in Home Assistant, grouped under the instance's device.

```python
--8<-- "pages/core-concepts/apps/snippets/integration_entities.py:declare"
```

Each `add_*` call returns a handle: `IntegrationButton`, `IntegrationSwitch` or `IntegrationSensor`, all importable from `hassette`. The app keeps the handle to set the entity's state later. `Instant` comes from the [`whenever`](https://whenever.readthedocs.io/) library (`from whenever import Instant`), which Hassette uses for times.

!!! warning "Declare entities only in `on_initialize`"
    Hassette commits an instance's declared entities once, after `on_initialize` returns and before the instance is marked running. A later `add_*` call raises `IntegrationDeclarationClosedError`. The committed set replaces the one from the last run, so an entity the app stops declaring is removed, with its state.

    An app whose declarations depend on a lookup, such as a config file or an API call, should let a failed lookup fail `on_initialize`. A failed instance keeps the entities it declared last time. A running instance that skipped some declarations loses them.

## Buttons

A button runs its `on_press` handler each time it is pressed in Home Assistant:

```python
--8<-- "pages/core-concepts/apps/snippets/integration_entities.py:press"
```

Hassette registers `on_press` as a bus listener named `integration.button.<key>`. The handler gets the same execution modes, error handling and telemetry as any other listener, and shows in the app's listeners view. `mode=` takes the bus's [`ExecutionMode`](../bus/execution-modes.md); the default, `single`, drops a press that arrives while the previous one is still running.

## Switches

A switch runs its `on_toggle` handler with the commanded state. `D.SwitchCommand` passes it in as a `bool`:

```python
--8<-- "pages/core-concepts/apps/snippets/integration_entities.py:toggle"
```

The switch's state changes only when the app calls `set()`. Home Assistant shows the old state until then, so the handler calls `set()` first. A handler that refuses a toggle leaves the state alone, and the switch goes back to where it was.

A new switch starts off. `initial=True` starts it on instead. `initial` applies only to a switch with no stored state: changing it later has no effect on an existing switch.

## Sensors

A sensor's device class, unit and state class decide which values `set()` accepts. The rules follow Home Assistant's own:

| Sensor | `set()` accepts |
|---|---|
| A `unit`, a `state_class`, or a numeric device class such as `temperature` | An `int` or `float` |
| `device_class="enum"` with `options=[...]` | One of `options` |
| `device_class="timestamp"` or `"uptime"` | A `whenever` `Instant`, `ZonedDateTime` or `OffsetDateTime`, stored as an `Instant` |
| `device_class="date"` | A `whenever` `Date` |
| Anything else | A `str` |

`set(None)` makes any sensor `unknown`, which is also where a new sensor starts. A value the sensor doesn't accept raises `ValueError` from `set()`, before anything is stored.

```python
--8<-- "pages/core-concepts/apps/snippets/integration_entities.py:sensor"
```

An unknown device class, an enum sensor without `options`, or `options` on any other sensor raises `ValueError` from `add_sensor`.

## State and Attributes

`set(value, attributes=...)` replaces the value and the attributes together, as a Home Assistant state write does. `set(5)` after `set(4, attributes={"x": 1})` leaves no attributes. A `set()` that matches the current state writes nothing, so re-publishing the same value on a timer costs nothing.

```python
--8<-- "pages/core-concepts/apps/snippets/integration_entities.py:enum"
```

Hassette stores each switch's and sensor's state in its database and restores it at the next start, as long as the entity stays declared. During `on_initialize`, a handle reads its restored state, and a `set()` there is held and stored with the commit. After the commit, `set()` stores the state before Home Assistant sees it, and raises if the database write fails.

A restored sensor value that no longer fits a changed declaration, such as a number on a sensor that became an enum, resets to `unknown` with a warning in the log.

After the instance stops, `set()` on its handles raises `IntegrationHandleClosedError`. A task that outlives a reload can't overwrite the state of the instance that replaced it.

## Keys and Entity IDs

The key identifies an entity within its instance. It follows the `instance_name` rule: lowercase letters, digits and `_`, starting with a letter. Each key is used once per instance, across all three platforms. Changing a key makes a new entity and removes the old one.

Home Assistant picks the entity ID from the device and entity names when it first creates the entity. `default_entity_id="sensor.cat_feeder_mode"` suggests one instead. Home Assistant applies it only at creation, so changing it later does nothing, and a rename in Home Assistant wins. An app that replaces an existing helper gets a new entity ID, so automations and dashboards that used the helper need updating.

## Integration Entities or Helpers

[`Api.helpers`](../api/managing-helpers.md) creates `input_button`, `input_boolean` and `input_number` helpers from code. Declared entities differ from helpers in four ways:

- A press while Hassette is down fails in Home Assistant, where a helper would change with nobody listening.
- A switch changes only when the app confirms it with `set()`.
- A sensor is read-only in Home Assistant and carries a unit, device class and state class, so it gets long-term statistics.
- An entity the app stops declaring is removed.

Helpers suit an app that has to work without the Hassette integration installed.

## Synchronous Apps

`AppSync` apps use `self.integration.sync`, which has the same `add_*` methods and a `set(handle, value, attributes=None)` for any switch or sensor handle.

## Testing

`AppTestHarness` presses and toggles declared entities with `simulate_button_press` and `simulate_switch_toggle`. See [Declared Buttons, Switches and Sensors](../../testing/harness.md#declared-buttons-switches-and-sensors).

## Next Steps

- **[Control Apps from Home Assistant](../../getting-started/home-assistant-integration.md)**: install and pair the Hassette integration, which these entities need.
- **[Execution Modes](../bus/execution-modes.md)**: what a press does while the previous handler is still running.
- **[Lifecycle](lifecycle.md)**: where `on_initialize` fits in an app's start.
