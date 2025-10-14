AppDaemon Comparison
=====================

AppDaemon
-----------

AppDaemon is a long-running Python process that connects to Home Assistant via WebSocket and REST API.
You develop apps by writing Python classes that subclass ``hass.Hass`` and saving them in a configured directory.
Configuration lives in ``apps.yaml`` and ``appdaemon.yaml``. AppDaemon apps are generally written in an IDE (e.g., VSCode)
which enables linting and autocompletion as well as debugging and stepping through code.

.. rubric:: Key Points

- AppDaemon runs apps in separate threads, so you can write synchronous code without worrying about blocking the main event loop.
- The scheduler offers a variety of helpers for delayed and recurring tasks.
- The event bus exposes entity state changes, service calls, and custom events.
- The Home Assistant API is synchronous and returns raw strings or dicts.
- All access to these features is via methods on ``self`` (the app instance).

Hassette
-----------

Hassette offers similar features but with a different design philosophy. It is async-first, strongly typed, and
built around composition instead of inheritance. Hassette also connects to Home Assistant via WebSocket and REST API,
you write apps as Python classes that inherit from :py:class:`~hassette.core.resources.app.app.App`, and configuration lives in ``hassette.toml``.
Hassette apps are also written in an IDE, offering the same debugging benefits, but is also strongly typed, which enables better autocompletion
and earlier error detection.

.. rubric:: Key Points

- Hassette apps run in the main event loop, so you write async code. A synchronous bridge class is available for simpler use cases.
- The scheduler offers similar helpers but uses a consistent API and returns rich job objects.
- The event bus uses typed events and composable predicates for filtering.
- The Home Assistant API is async and uses Pydantic models for responses.
- Features are accessed via composition: ``self.bus``, ``self.scheduler``, and ``self.api``.

Quick reference table
-----------------------

.. list-table:: Snapshot of common tasks
   :header-rows: 1
   :widths: 20 40 40

   * - Action
     - AppDaemon
     - Hassette
   * - Listen for an entity state change
     - ``self.listen_state(self.on_open, "binary_sensor.door", new="on")``
     - ``self.bus.on_entity("binary_sensor.door", handler=self.on_open, changed_to="on")``
   * - React to an attribute threshold
     - ``self.listen_state(self.on_battery, "sensor.phone", attribute="battery", below=20)``
     - ``self.bus.on_attribute("sensor.phone", "battery", handler=self.on_battery, where=lambda e: (e.payload.data.new_value or 100) < 20)``
   * - Monitor service calls
     - ``self.listen_event(self.on_service, "call_service", domain="light")``
     - ``self.bus.on_call_service(domain="light", handler=self.on_service)``
   * - Schedule something in 60 seconds
     - ``self.run_in(self.turn_off, 60)``
     - ``self.scheduler.run_in(self.turn_off, delay=60)``
   * - Run every morning at 07:30
     - ``self.run_daily(self.morning, time(7, 30, 0))``
     - ``self.scheduler.run_daily(self.morning, start=time(7, 30))``
   * - Call a Home Assistant service
     - ``self.call_service("light/turn_on", entity_id="light.kitchen", brightness=200)``
     - ``await self.api.call_service("light", "turn_on", target={"entity_id": "light.kitchen"}, brightness_pct=80)``
   * - Access app configuration
     - ``self.args["entity"]``
     - ``self.app_config.entity``
   * - Stop a listener
     - ``self.cancel_listen_state(handle)``
     - ``subscription.cancel()``
   * - Stop a scheduled job
     - ``self.cancel_timer(handle)``
     - ``job.cancel()``


Detailed Comparison
--------------------


AppDaemon Configuration
~~~~~~~~~~~~~~~~~~~~~~~~

AppDaemon uses two YAML configuration files: ``appdaemon.yaml`` for global settings and ``apps.yaml`` for app-specific configuration. AppDaemon also supports toml files, though YAML is more common.

- ``appdaemon.yaml`` specifies the app directory, logging, and connection details for Home Assistant.
- ``apps.yaml`` defines each app instance with its module, class, and arguments.

A basic ``appdaemon.yaml`` might look like this:

.. code-block:: yaml

  appdaemon:
    time_zone: America/Chicago
    latitude: 51.725
    longitude: 14.3434
    elevation: 0
    use_dictionary_unpacking: true
    plugins:
      HASS:
        type: hass
        ha_url: http://192.168.1.179:8123
        token: !env_var HOME_ASSISTANT_TOKEN

An app might look like this in ``apps.yaml``:

.. code-block:: yaml

  my_app:
    module: my_app
    class: MyApp
    args:
      entity: light.kitchen
      brightness: 200


This would correspond to a Python file ``my_app.py`` in the directory ``./apps`` with a class ``MyApp`` that subclasses ``Hass``.
Arguments are accessible through the ``self.args`` dictionary, under the ``args`` key. You have access to logging via ``self.log()``, which is a
method that is part of AppDaemon's logging system. Because of the way the logger is implemented, you cannot easily see the location of the log call
in your output, although there are some magic strings you can use to include these.

.. code-block:: python
  :linenos:

    from appdaemon.plugins.hass import Hass

    class MyApp(Hass):
        def initialize(self):
            self.log(f"{self.args=}")
            entity = self.args["args"]["entity"]
            brightness = self.args["args"]["brightness"]
            self.log(f"My configured entity is {entity!r} (type {type(entity)})")
            self.log(f"My configured brightness is {brightness!r} (type {type(brightness)})")

            # 2025-10-13 18:59:04.820599 INFO my_app: self.args={'name': 'my_app', 'config_path': PosixPath('./apps.yaml'), 'module': 'my_app', 'class': 'MyApp', 'args': {'entity': 'light.kitchen', 'brightness': 200}}
            # 2025-10-13 18:40:23.676650 INFO my_app: My configured entity is 'light.kitchen' (type <class 'str'>)
            # 2025-10-13 18:40:23.677422 INFO my_app: My configured brightness is 200 (type <class 'int'>)


Hassette Configuration
~~~~~~~~~~~~~~~~~~~~~~~~

Hassette uses a single ``hassette.toml`` file for all configuration, including global settings and app-specific parameters. Each app gets its own section under the ``[apps]`` table.

A basic ``hassette.toml`` might look like this:

.. code-block:: toml

  [hassette]
  base_url = "http://127.0.0.1:8123"
  api_port = 8123

  [apps.my_app]
  filename = "my_app.py"
  class_name = "MyApp"

  [[apps.my_app.config]]
  entity = "light.kitchen"
  brightness = 200



This would correspond to a Python file ``my_app.py`` in the directory ``/apps/`` with a class ``MyApp`` that subclasses :class:`~hassette.core.resources.app.app.App` or :class:`~hassette.core.resources.app.app.AppSync`.
Because Hassette uses Pydantic models for configuration, you define a subclass of :class:`~hassette.core.resources.app.app_config.AppConfig` to specify expected parameters and their types.
You access configuration via the typed ``self.app_config`` attribute, which offers IDE support and validation at startup. The logger is part of the base class and uses Python's standard logging library, the log format
automatically includes the instance name, method name, and line number. Instance names can be set in the config file or default to ``<ClassName>.<index>``.

.. code-block:: python
  :linenos:

    from pydantic import Field

    from hassette import App, AppConfig


    class MyAppConfig(AppConfig):
        entity: str = Field(..., description="The entity to monitor")
        brightness: int = Field(100, ge=0, le=255, description="Brightness level (0-255)")


    class MyApp(App[MyAppConfig]):
        async def on_initialize(self):
            self.logger.info(f"{self.app_manifest=}")
            self.logger.info(f"{self.app_config=}")
            entity = self.app_config.entity
            self.logger.info("My configured entity is %r (type %s)", entity, type(entity))
            brightness = self.app_config.brightness
            self.logger.info("My configured brightness is %r (type %s)", brightness, type(brightness))


            # 2025-10-13 18:57:45.495 INFO hassette.MyApp.0.on_initialize:13 ─ self.app_manifest=<AppManifest MyApp (MyApp) - enabled=True file=my_app.py>
            # 2025-10-13 18:57:45.495 INFO hassette.MyApp.0.on_initialize:14 ─ self.app_config=MyAppConfig(instance_name='MyApp.0', log_level='INFO', entity='light.kitchen', brightness=200)
            # 2025-10-13 18:57:45.495 INFO hassette.MyApp.0.on_initialize:17 ─ My configured entity is 'light.kitchen' (type <class 'str'>)
            # 2025-10-13 18:57:45.495 INFO hassette.MyApp.0.on_initialize:19 ─ My configured brightness is 200 (type <class 'int'>)


AppDaemon Features
~~~~~~~~~~~~~~~~~~~

AppDaemon apps are able to subscribe to three main types of events: scheduled events (e.g. scheduled jobs), state change events (e.g. entity state changes), and custom events (e.g. service calls or user-defined events). The examples below
are taken from the AppDaemon documentation and illustrate how to use these features.

Schedule callbacks
^^^^^^^^^^^^^^^^^^^

Schedule callbacks are expected to have a signature of ``def my_callback(self, **kwargs) -> None:``. The ``kwargs`` dictionary can contain arbitrary data you pass when scheduling the callback, and also includes the internal ``__thread_id`` value.

.. .. note::

..    You do need to be careful about calling methods too quickly upon startup. While writing this documentation I found that calling ``self.run_once(self.run_daily_callback, "now")`` in ``initialize()`` sometimes caused the callback to fail due to the internal states not being fully initialized yet. The error looked like this:

..    .. code-block:: text

..       2025-10-13 19:26:37.041852 WARNING nightlight: Entity light.office_light_1 not found in the default namespace
..       2025-10-13 19:26:37.042573 ERROR nightlight: =====  NightLight.run_daily_callback for nightlight  ======================
..       2025-10-13 19:26:37.042678 ERROR nightlight: SchedulerCallbackFail: Scheduled callback failed for app 'nightlight'
..       2025-10-13 19:26:37.043156 ERROR nightlight:   DomainException: domain 'homeassistant' does not exist in namespace 'default'
..       2025-10-13 19:26:37.044173 ERROR nightlight:   apps/nightlight.py line 14 in run_daily_callback


.. code-block:: python
  :linenos:

  from appdaemon.plugins.hass import Hass


  # Declare Class
  class NightLight(Hass):
      # function which will be called at startup and reload
      def initialize(self):
          # Schedule a daily callback that will call run_daily_callback() at 7pm every night
          self.run_daily(self.run_daily_callback, "19:00:00")

      # Our callback function will be called by the scheduler every day at 7pm
      def run_daily_callback(self, **kwargs):
          # Call to Home Assistant to turn the porch light on
          self.turn_on("light.porch")


Event callbacks
^^^^^^^^^^^^^^^^^^^

Event callbacks are expected to have a signature of ``def my_callback(self, event_type: str, data: dict[str, Any], **kwargs: Any) -> None:``.

.. code-block:: python
  :linenos:

  from datetime import datetime
  from typing import Any

  from appdaemon.adapi import ADAPI


  class ButtonHandler(ADAPI):
      def initialize(self):
          # Listen for a button press event with a specific entity_id
          self.listen_event(
              self.minimal_callback,
              "call_service",
              service="press",
              entity_id="input_button.test_button",
          )

      def minimal_callback(self, event_type: str, data: dict[str, Any], **kwargs: Any) -> None:
          self.log(f"{event_type=}, {data=}, {kwargs=}")


.. code-block:: text

   2025-10-14 06:49:34.791752 INFO button_handler:
       event_type='call_service',
       data={
           'domain': 'input_button',
           'service': 'press',
           'service_data': {
               'entity_id': 'input_button.test_button'
           },
           'metadata': {
               'origin': 'LOCAL',
               'time_fired': '2025-10-14T11:49:34.784540+00:00',
               'context': {
                   'id': '01K7H8VSY0Y3VK6MTM5V1MBF8C',
                   'parent_id': None,
                   'user_id': 'caa14e06472b499cb00545bb65e56e5a'
               }
           }
       },
       kwargs={
           'service': 'press',
           'entity_id': 'input_button.test_button',
           '__thread_id': 'thread-1'
       }



State change callbacks
^^^^^^^^^^^^^^^^^^^^^^^

State change callbacks are expected to have a signature of ``def my_callback(self, entity: str, attribute: str, old: str, new: str, **kwargs) -> None:``.

.. code-block:: python
  :linenos:

  from appdaemon.plugins.hass import Hass


  class ButtonPressed(Hass):
      def initialize(self):
          self.listen_state(self.button_pressed, "input_button.test_button", arg1=123)

      def button_pressed(self, entity, attribute, old, new, arg1, **kwargs):
          self.log(f"{entity=} {attribute=} {old=} {new=} {arg1=}")

.. code-block:: text

   2025-10-13 19:35:56.976839 INFO button_pressed:
       entity='input_button.test_button',
       attribute='state',
       old='2025-10-14T00:16:04.117097+00:00',
       new='2025-10-14T00:35:58.240005+00:00',
       arg1=123


Api access
^^^^^^^^^^^^

You can get and set entity states using ``self.get_state()`` and ``self.set_state()``. The ``get_state()`` method can return just the state string or a full dictionary with attributes. Attempting to access a non-existent entity will return ``None``, no exception is raised.

.. code-block:: python
  :linenos:

  from appdaemon.plugins.hass import Hass


  class StateGetter(Hass):
      def initialize(self):
          office_light_state = self.get_state("light.office_light_1", attribute="all")
          self.log(f"{office_light_state=}")


.. code-block:: text

   2025-10-13 19:38:15.241717 INFO get_state:
       office_light_state={
           'entity_id': 'light.office_light_1',
           'state': 'on',
           'attributes': {
               'min_color_temp_kelvin': 2000,
               'max_color_temp_kelvin': 6535,
               'min_mireds': 153,
               'max_mireds': 500,
               'effect_list': [
                   'blink', 'breathe', 'okay', 'channel_change',
                   'candle', 'fireplace', 'colorloop',
                   'finish_effect', 'stop_effect', 'stop_hue_effect'
               ],
               'supported_color_modes': ['color_temp', 'xy'],
               'effect': None,
               'color_mode': 'xy',
               'brightness': 255,
               'color_temp_kelvin': None,
               'color_temp': None,
               'hs_color': [0.0, 100.0],
               'rgb_color': [255, 0, 0],
               'xy_color': [0.701, 0.299],
               'friendly_name': 'Office Light 1',
               'supported_features': 44
           },
           'last_changed': '2025-10-13T10:40:17.569005+00:00',
           'last_reported': '2025-10-14T00:26:55.317432+00:00',
           'last_updated': '2025-10-14T00:26:55.317432+00:00',
           'context': {
               'id': '01K7G1STAQ2PW83YQDZ7YJ65VY',
               'parent_id': None,
               'user_id': 'a7b56f4dc8ca4a2fa4130263ba7b4b93'
           }
       }



Hassette Features
~~~~~~~~~~~~~~~~~~

Hassette apps have access to the same features, though we refer to them with slightly different terminology. Scheduled events are handled by the scheduler, state change events and custom events are handled by the event bus, and entity state access is provided by the Home Assistant API client. The examples below illustrate how to use these features.


Scheduled Jobs
^^^^^^^^^^^^^^^^^^^

Scheduled jobs do not need to follow a specific signature. They can be either async or sync functions, and can accept arbitrary parameters. The scheduler methods return rich job objects that can be used to manage the scheduled task.

.. code-block:: python
  :linenos:

  from hassette import App


  # Declare Class
  class NightLight(App):
      # function which will be called at startup and reload
      async def on_initialize(self):
          # Schedule a daily callback that will call run_daily_callback() at 7pm every night
          job = self.scheduler.run_daily(self.run_daily_callback, start=(19, 0))
          self.logger.info(f"Scheduled job: {job}")

          # 2025-10-13 19:57:02.670 INFO hassette.NightLight.0.on_initialize:11 ─ Scheduled job: ScheduledJob(name='run_daily_callback', owner=NightLight.0)

      # Our callback function will be called by the scheduler every day at 7pm
      async def run_daily_callback(self, **kwargs):
          # Call to Home Assistant to turn the porch light on
          await self.api.turn_on("light.office_light_1", color_name="red")


Event Handlers
^^^^^^^^^^^^^^^^

Event handlers can also be either async or sync functions, and currently only accept the event object as a parameter. The event bus uses typed events and composable predicates for filtering.
There is some definite room for improvement in the ergonomics of this API, but the example below illustrates how to listen for a specific service call event. Note that the ``Guard`` predicate
is generic, so annotating it with the expected event type enables IDE support and better error detection. In this example, ``data`` is known to be of type ``CallServicePayload``.

.. code-block:: python
  :linenos:

  from hassette.events import CallServiceEvent

  from hassette import App, Guard

  where = Guard["CallServiceEvent"](
      lambda event: event.payload.data.service_data["entity_id"] == "input_button.test_button"
  )


  class ButtonHandler(App):
      async def on_initialize(self):
          # Listen for a button press event with a specific entity_id
          sub = self.bus.on_call_service(service="press", handler=self.minimal_callback, where=where)
          self.logger.info(f"Subscribed: {sub}")

      def minimal_callback(self, event: CallServiceEvent) -> None:
          self.logger.info(f"Button pressed: {event}")

.. code-block:: text

   2025-10-13 20:07:26.735 INFO hassette.ButtonHandler.0.minimal_callback:38 ─ Button pressed:
       Event(
           topic='hass.event.call_service',
           payload=HassPayload(
               event_type='call_service',
               data=CallServicePayload(
                   domain='input_button',
                   service='press',
                   service_data={
                       'entity_id': 'input_button.test_button'
                   },
                   service_call_id=None
               ),
               origin='LOCAL',
               time_fired=SystemDateTime(2025-10-13 20:07:26.723688-05:00),
               context={
                   'id': '01K7G440W3J39SFDHJM0Y50P17',
                   'parent_id': None,
                   'user_id': 'caa14e06472b499cb00545bb65e56e5a'
               }
           )
       )



State change handlers
^^^^^^^^^^^^^^^^^^^^^^

State change handlers are the exact same as event handlers, we're only calling them out separately to align with AppDaemon. These can also be either async or sync functions, and currently only accept the event object as a parameter.
The event bus provides helpers for filtering entities and attributes. You can also provide additional predicates using the ``where`` parameter. In this example, we listen for any state change on the specified entity.

Currently the repr of a StateChangeEvent is quite verbose, but it does show the full old and new state objects, which can be useful for debugging. Cleaning this up is on the roadmap.


.. code-block:: python
  :linenos:

  from hassette import App, StateChangeEvent, states


  class ButtonPressed(App):
      async def on_initialize(self):
          # Listen for a button press event with a specific entity_id
          sub = self.bus.on_entity(entity="input_button.test_button", handler=self.button_pressed)
          self.logger.info(f"Subscribed: {sub}")

      def button_pressed(self, event: StateChangeEvent[states.ButtonState]) -> None:
          self.logger.info(f"Button pressed: {event}")


Note, some output has been truncated for brevity.

.. code-block:: text

   2025-10-13 22:52:35.281 INFO hassette.ButtonPressed.0.button_pressed:11 ─ Button pressed:
       Event(
           topic='hass.event.state_changed',
           payload=HassPayload(
               event_type='state_changed',
               data=StateChangePayload(
                   entity_id='input_button.test_button',
                   old_state=InputButtonState(
                       domain='input_button',
                       entity_id='input_button.test_button',
                       last_changed=SystemDateTime(2025-10-13 20:07:26.723887-05:00),
                       ...
                   ),
                   new_state=InputButtonState(
                       domain='input_button',
                       entity_id='input_button.test_button',
                       last_changed=SystemDateTime(2025-10-13 22:52:35.268639-05:00),
                       ...
                   ),
               ),
               origin='LOCAL',
               time_fired=SystemDateTime(2025-10-13 22:52:35.268639-05:00),
               context={
                   'id': '01K7GDJD644YJWJGTRHXBVPQ4P',
                   'user_id': 'caa14e06472b499cb00545bb65e56e5a'
               }
           )
       )



Api access
^^^^^^^^^^^^

Hassette aims to provide a fully typed API client that uses Pydantic models for requests and responses. The client methods are async and return rich objects with attributes. Attempting to access a non-existent entity will raise a ``NotFoundError`` exception.

.. code-block:: python
  :linenos:

  from hassette.models import states

  from hassette import App


  class StateGetter(App):
      async def on_initialize(self):
          office_light_state = await self.api.get_state("light.office_light_1", model=states.LightState)
          self.logger.info(f"{office_light_state=}")


.. code-block:: text

   2025-10-14 06:59:35.645 INFO hassette.StateGetter.0.on_initialize:9 ─ office_light_state=
       LightState(
           domain='light',
           entity_id='light.office_light_1',
           last_changed=SystemDateTime(2025-10-14 05:40:01.31513-05:00),
           last_reported=SystemDateTime(2025-10-14 06:47:57.195556-05:00),
           last_updated=SystemDateTime(2025-10-14 06:47:57.195556-05:00),
           is_unknown=False,
           is_unavailable=False,
           value='on',
           attributes=Attributes(
               friendly_name='Office Light 1',
               device_class=None,
               supported_features=44,
               min_color_temp_kelvin=2000,
               max_color_temp_kelvin=6535,
               min_mireds=153,
               max_mireds=500,
               effect_list=[
                   'blink', 'breathe', 'okay', 'channel_change',
                   'candle', 'fireplace', 'colorloop', 'finish_effect',
                   'stop_effect', 'stop_hue_effect'
               ],
               supported_color_modes=['color_temp', 'xy'],
               effect=None,
               color_mode='xy',
               brightness=255,
               color_temp_kelvin=None,
               hs_color=[0.0, 100.0],
               rgb_color=[255, 0, 0],
               xy_color=[0.701, 0.299]
           )
       )
