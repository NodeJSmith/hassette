Apps
====

Apps are the core building blocks of automations in Hassette. They encapsulate logic, state, and configuration, and interact with Home Assistant through a rich API.
Apps can be asynchronous or synchronous, depending on your needs. Asynchronous apps are preferred for most use cases, as they can take full advantage of Python's async
capabilities and integrate seamlessly with Hassette's event loop. Synchronous apps are supported for legacy code or libraries that do not support async - these are run
using ``asyncio.to_thread`` to avoid blocking the event loop.

Apps are defined as Python classes that inherit from ``App`` (for async) or ``AppSync`` (for sync) and are configured using a Pydantic model that inherits from ``AppConfig``.

Lifecycle hooks allow you to run code at specific points in the app's lifecycle, such as initialization and shutdown. Apps can subscribe to events on the Home Assistant event bus
and schedule jobs to run at specific times or intervals. They have access to the Home Assistant API for interacting with entities, services, and states. All scheduled jobs
and subscriptions are automatically cleaned up when the app is shut down.

During development, apps are automatically reloaded when their source files change, allowing for rapid iteration without restarting the entire Hassette process. Additionally,
you can use the ``only_app`` decorator to run a single app in isolation for focused testing and debugging, without changing your configuration file. Both of these features are
disabled in production mode for stability (although you can enable them if you wish via configuration options).

Example
-------

.. code-block:: python

   from hassette import App, AppConfig, StateChangeEvent, states
   from pydantic import Field

   class MyAppConfig(AppConfig):
       light: str = Field(..., description="The entity to monitor")

   class MyApp(App[MyAppConfig]):
       async def on_initialize(self):
           self.on_change_listener = self.bus.on_state_change(self.app_config.light, handler=self.on_change)
           self.minutely_logger = self.scheduler.run_minutely(self.log_every_minute)

       async def on_change(self, event: StateChangeEvent[states.LightState]):
           self.logger.info("Entity %s changed: %s", self.app_config.light, event)

        async def log_every_minute(self):
            self.logger.info("One minute passed")

        async def on_shutdown(self):
            # not required, as Hassette will clean up all resources automatically
            # but shown here for demonstration
            self.on_change_listener.cancel()
            self.minutely_logger.cancel()


App Capabilities
----------------
  - ``self.api``: Async Home Assistant API (see :doc:`api`). In sync apps, use ``self.api.sync``.
  - ``self.bus``: Subscribe to events with filters (see :doc:`bus`). Returns ``Subscription``.
  - ``self.scheduler``: Run jobs on intervals or cron (see :doc:`scheduler`). Returns ``ScheduledJob``.
  - ``self.logger``: Individual logger per app instance. Standard lib logger, use it as normal.
  - ``self.app_config``: The parsed config for this app instance, typed as the app's ``AppConfig`` class.
  - ``self.index``: The index of this app instance in the config list, or 0 if only a single instance.
  - ``self.instance_name``: The name of this app instance as set in the config, or ``<ClassName>.[index]`` if not set.
  - ``self.now()``: Get the current time as ``ZonedDateTime``.

Advanced Capabilities
---------------------
    - ``self.hassette``: Access to the core ``Hassette`` instance for advanced use cases.
    - ``self.task_bucket``: Low-level sync/async task management (documentation coming soon).
    - ``self.send_event``: Emit custom events (currently not very ergonomic; will be improved in a future release).
    - ``self.app_manifest``: Class-level ``AppManifest`` with details that ``Hassette`` needs to start the app.
    - ``self.status``: Current status of the app (NOT_STARTED, STARTING, RUNNING, STOPPED, FAILED, CRASHED).
    - ``self.ready_event``: An ``asyncio.Event`` that is set when ``mark_ready`` is called.

     - Note: This is not set automatically and is not necessary for most apps. It can be set manually to signal readiness to other parts of your app or to coordinate between multiple apps.

    - ``self.shutdown_event``: An ``asyncio.Event`` that is set when the app begins shutdown.

     - Note: This is set automatically during shutdown and can be used in your app to check if shutdown is in progress and to clean up resources or exit gracefully.


Lifecycle
---------
All resources, including Apps, follow a clear lifecycle with startup and shutdown hooks. As each app is started, it is transitioned to the STARTING state, the initialization hooks are called in order, and then the app is marked RUNNING.
Apps do not start until all services they depend on are available, which include the Home Assistant API, the event bus, and the scheduler. This ensures that your app can rely on these services being available in your initialization logic.

When the App is shutting down (including when being reloaded), the ``shutdown_event`` is set, the shutdown hooks are called in order, the ``cleanup`` method is called to clean up resources, and then the app is marked STOPPED. If an
unhandled exception occurs during startup or shutdown, the app is marked as FAILED, but the ``cleanup`` method is still called to ensure resources are cleaned up.

- Initialization
   - Hook into startup with ``on_initialize``, ``before_initialize``, or ``after_initialize`` (``on_initialize_sync``, etc. for sync apps).
   - All resources and services are available in these hooks.
   - When your application is starting up the ``@final`` method ``initialize`` is called, which in turn calls these hooks in order:

    1. ``before_initialize`` - This runs prior to the app's own ``on_initialize``.
    2. ``on_initialize`` - This is where you should put most of your initialization logic, such as subscriptions and scheduled jobs.
    3. ``after_initialize`` - This runs after the app's own ``on_initialize``.

   - You never need to call ``super()`` in these methods, as they are hooks, not overrides.

- Shutdown
   - Hook into shutdown with ``on_shutdown``, ``before_shutdown``, or ``after_shutdown`` (``on_shutdown_sync``, etc. for sync apps).
   - When your application is shutting down the ``@final`` method ``shutdown`` is called, which in turn calls these hooks in order:

    1. ``before_shutdown``
    2. ``on_shutdown``
    3. ``after_shutdown``

   - After these hooks are called, the ``cleanup`` method is called to clean up resources.

    - This will cancel all subscriptions and scheduled jobs automatically, as well as cancelling all tasks in your app's task bucket.

   - If you set up your own resources (e.g. open files, network connections), clean them up in ``on_shutdown`` or ``after_shutdown``.
   - Generally speaking you will not need to do any cleanup, as the framework handles it for you.

.. warning::

    You cannot override ``initialize``, ``shutdown``, or ``cleanup`` directly; use the hooks instead. If you attempt to do so, a ``CannotOverrideFinalError`` will be raised.

.. note::

    ``Hassette`` performs a pre-check prior to spinning up all services to ensure that all apps can be imported. This will catch import/syntax/name errors early,
    along with errors caused by overriding final methods.


AppConfig Class
-------------------------
Every app *should* define a Pydantic model that inherits from ``AppConfig`` to represent its configuration. This model is used to parse and validate the configuration provided in the TOML file.

The base AppConfig class includes two fields by default:

 - ``instance_name: str | None``: Optional name for the instance, used in logging.
 - ``log_level: str | None``: Optional log level override, defaults to the global app level or the hassette log level.

.. code-block:: python

   from hassette import App, AppConfig
   from pydantic import Field

   class PresenceConfig(AppConfig):
       motion_sensor: str = Field(...)
       lights: list[str] = Field(default_factory=list)

   class Presence(App[PresenceConfig]):
       async def on_initialize(self):
           self.bus.on_state_change(self.app_config.motion_sensor, handler=self.on_motion, changed_to="on")

       async def on_motion(self, event):
           for light in self.app_config.lights:
               await self.api.turn_on(light)

Configuration (TOML)
--------------------

.. code-block:: toml

   ## App Manifest section
   [apps.presence]
   filename = "presence.py"
   class_name = "Presence"

   ## App Config section
   [[apps.presence.config]]
   instance_name = "upstairs"
   motion_sensor = "binary_sensor.upstairs_motion"
   lights = ["light.bedroom", "light.hallway"]

   [[apps.presence.config]]
   instance_name = "downstairs"
   motion_sensor = "binary_sensor.downstairs_motion"
   lights = ["light.living_room", "light.kitchen"]
   log_level = "DEBUG" # Override log level for this instance only


See also
--------
- :doc:`configuration` for TOML structure and app_dir import rules
- :doc:`bus` for subscription patterns and predicates
- :doc:`api` for service calls, templates, and history
- :doc:`scheduler` for job scheduling and management
