Apps
====

Build automations as classes with strong typing and a clear lifecycle.

App Anatomy
-----------
- ``App[AppConfig]``: async-first apps implement ``async def initialize(self)``.
- ``AppSync[AppConfig]``: synchronous apps implement ``def initialize_sync(self)``.
- ``AppConfig``: Pydantic-based config model for typed ``self.app_config``.

When to use which:

- Prefer ``App`` for most automations; the API is async-first.
- Use ``AppSync`` only when your logic must be synchronous (e.g., legacy libs) and call ``self.api.sync``.

Lifecycle
---------
- Initialize (``initialize`` or ``initialize_sync``): set up subscriptions, schedules, and any initial state.
- Teardown (``shutdown`` or ``shutdown_sync``): unsubscribe or cancel jobs if you kept references (optional; Hassette cleans up on shutdown).

.. note::

    You should always call ``await super().initialize()`` and ``super().shutdown()`` (or their sync counterparts) if you override these methods. These will set the state
    of your app to "running"/"stopped" and perform necessary internal setup/teardown.

    You'll generally want to call them *after* your own setup in ``initialize`` and *after* your own teardown in ``shutdown``.

.. warning::

    You should not override ``__init__``, as this is managed by the framework. Use ``initialize`` for setup.

.. code-block:: python

   class WithCleanup(App[AppConfig]):
       async def initialize(self):
           await super().initialize()
           self.sub = self.bus.on_entity("light.kitchen", handler=self.on_change)
           self.job = self.scheduler.run_every(self.tick, interval=60)

       async def on_change(self, event):
           ...

       async def tick(self):
           ...

       # Optional: if you keep references, you can clean up explicitly
       async def shutdown(self):  # if you add a custom shutdown path
           self.sub.unsubscribe()
           self.job.cancel()
           await super().shutdown()

.. code-block:: python

   from hassette import App, AppSync, AppConfig, StateChangeEvent, states

   class MyConfig(AppConfig):
       entity_id: str

   class LightsOn(App[MyConfig]):
       async def initialize(self):
           self.logger.info("Starting LightsOn for %s", self.app_config.entity_id)
           self.bus.on_entity(self.app_config.entity_id, handler=self.on_change)
           await super().initialize()

       async def on_change(self, event: StateChangeEvent[states.LightState]):
           if event.payload.data.new_state_value == "off":
               await self.api.turn_on(self.app_config.entity_id)

   class LightsOnSync(AppSync[MyConfig]):
       def initialize_sync(self):
           self.bus.on_entity(self.app_config.entity_id, handler=self.on_change)
           super().initialize_sync()

       def on_change(self, event: StateChangeEvent[states.LightState]):
           if event.payload.data.new_state_value == "off":
               self.api.sync.turn_on(self.app_config.entity_id)

Configuration (AppConfig)
-------------------------
Define a Pydantic config for validation and editor help.

.. code-block:: python

   from hassette import App, AppConfig
   from pydantic import Field, SettingsConfigDict

   class PresenceConfig(AppConfig):
       model_config = SettingsConfigDict(env_prefix="PRESENCE_")
       motion_sensor: str = Field(...)
       lights: list[str] = Field(default_factory=list)

   class Presence(App[PresenceConfig]):
       async def initialize(self):
           self.bus.on_entity(self.app_config.motion_sensor, handler=self.on_motion, changed_to="on")
           await super().initialize()

       async def on_motion(self, event):
           for light in self.app_config.lights:
               await self.api.turn_on(light)

Multiple instances
------------------
Use a single config object for one instance, or list-of-tables for many:

.. code-block:: toml

   [apps.presence]
   filename = "presence.py"
   class_name = "Presence"

   # One instance
   config = { motion_sensor = "binary_sensor.hall", lights = ["light.entry"] }

   # Or many instances
   [[apps.presence.config]]
   name = "upstairs"
   motion_sensor = "binary_sensor.upstairs_motion"
   lights = ["light.bedroom", "light.hallway"]

   [[apps.presence.config]]
   name = "downstairs"
   motion_sensor = "binary_sensor.downstairs_motion"
   lights = ["light.living_room", "light.kitchen"]

Core Services in Apps
---------------------
- ``self.api``: Async Home Assistant API. In sync apps, use ``self.api.sync``.
- ``self.bus``: Subscribe to events with filters (see :doc:`events`). Returns ``Subscription``.
- ``self.scheduler``: Run jobs on intervals or cron (see :doc:`scheduler`). Returns job handles.
- ``self.logger``: Structured logging per app. Use levels: debug/info/warning/error.
- ``self.hassette``: Access the orchestrator (advanced usage: e.g., run blocking call via ``run_sync``).

.. note::

    ``on_entity`` and ``on_attribute`` accept glob patterns in the entity ID, e.g. ``"light.*"`` or ``"light.my_*"``.

.. code-block:: python

    # React to any light entity
    self.bus.on_entity("light.*", handler=self.on_any_light)

Examples
--------
Subscribing with filters and scheduling work:

.. code-block:: python

   class BatteryWatcher(App[AppConfig]):
       async def initialize(self):
           # Debounce noisy updates and act only when below threshold
           self.bus.on_attribute(
               "sensor.phone_battery",
               "battery_level",
               handler=self.on_battery,
               predicate=lambda e: (e.payload.data.new_value or 100) < 20,
               debounce=2.0,
           )
           # Daily health check
           self.scheduler.run_cron(self.report, hour=8)

       async def on_battery(self, event: StateChangeEvent[states.SensorState]):
           await self.api.notify("mobile_app_me", message="Battery low")

       async def report(self):
           states = await self.api.get_states()
           self.logger.info("Currently tracking %d states", len(states))

See also
--------
- :doc:`configuration` for TOML structure and app_dir import rules
- :doc:`events` for subscription patterns and predicates
- :doc:`api` for service calls, templates, and history
