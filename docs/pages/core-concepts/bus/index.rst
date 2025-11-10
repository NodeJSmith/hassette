Bus
===

The event bus connects your apps to Home Assistant and to Hassette itself.
It delivers events such as state changes, service calls, or framework updates to any app that subscribes.

Apps register event handlers through ``self.bus``, which is created automatically at app instantiation.


Overview
--------

You can register handlers for any `Home Assistant event <https://www.home-assistant.io/docs/configuration/events/>`__
or internal Hassette framework event using the event bus.

Handlers can be **async or sync**, functions or methods — no special signature is required.
If your handler needs to receive the event object, name its first (non-``self``) parameter ``event``.
The name, not the type, is what Hassette uses to decide whether to pass it.

Example:

.. code-block:: python

   async def on_motion(self, event):
       self.logger.info("Motion detected from %s", event.payload.data["entity_id"])

If your handler doesn't need the event object, omit the parameter:

.. code-block:: python

   async def on_heartbeat(self) -> None:
       self.logger.info("Heartbeat received")

Handlers can also accept extra ``args`` or ``kwargs`` that you provide when subscribing.


Event Model
-----------

Every event you receive from the bus is an :class:`~hassette.events.base.Event` dataclass with two main fields:

- ``topic`` — a string identifier describing what happened, such as ``hass.event.state_changed``
  or ``hassette.event.service_status``.

- ``payload`` — a typed wrapper containing the event data.

Home Assistant events use the format ``hass.event.<event_type>``
(e.g., ``hass.event.state_changed`` or ``hass.event.call_service``).
Hassette framework events use ``hassette.event.<event_type>`` for internal events like service status changes or file-watching updates.

Example:

.. literalinclude:: working_with_event_data_example.py
   :language: python


Basic Subscriptions
-------------------

These helper methods cover the majority of use cases:

- ``on_state_change`` — listen for entity state changes
- ``on_attribute_change`` — listen for changes to a specific attribute
- ``on_call_service`` — listen for service calls
- ``on`` — subscribe directly to any event topic

Each method returns a :class:`~hassette.bus.listeners.Subscription` handle, which you can keep to unsubscribe later.

.. literalinclude:: basic_subscriptions_example.py
   :language: python
   :lines: 5-21

Unsubscribing:

.. code-block:: python

   sub = self.bus.on_state_change("binary_sensor.motion", handler=self.on_motion)
   sub.unsubscribe()

Hassette automatically cleans up all subscriptions during app shutdown,
so manual unsubscription is only needed for temporary listeners.


Working with Event Data
-----------------------

Each event's ``payload.data`` contains the actual content.

- **State changes** → ``entity_id``, ``old_state``, ``new_state``
  (both state objects are typed Pydantic models inheriting from
  :py:class:`~hassette.models.states.base.BaseState`)

  Common properties:

  - ``.value`` - the state value (e.g., ``"on"``)
  - ``.attributes`` - a Pydantic model of all attributes
  - ``.domain`` and ``.entity_id`` - convenience accessors
  - ``.last_changed`` / ``.last_updated`` - timestamps

- **Service calls** → :class:`~hassette.events.hass.hass.CallServicePayload`
  with ``domain``, ``service``, and ``service_data`` fields.


Advanced Subscriptions
----------------------

For more complex scenarios, subscribe directly to any topic:

.. literalinclude:: advanced_subscriptions_example.py
   :language: python
   :lines: 5-11

Passing Arguments
~~~~~~~~~~~~~~~~~

You can pass additional arguments to your handler using ``args`` and ``kwargs``:

.. literalinclude:: passing_arguments_example.py
   :language: python
   :lines: 5-12

Filtering with Predicates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Predicates provide fine-grained control over which events trigger your handlers.
Use them with the ``where`` parameter.

.. code-block:: python

   from hassette import predicates as P

   self.bus.on_state_change(
       "binary_sensor.front_door",
       handler=self.on_door_open,
       changed_to="on",
       where=[
           P.Not(P.StateFrom("unknown")),
           P.AttrTo("battery_level", lambda x: x and x > 20)
       ]
   )

   # Logical operators
   self.bus.on_state_change(
       "media_player.living_room",
       handler=self.on_media_change,
       where=P.StateTo(P.IsIn(["playing", "paused"]))
   )

   # Custom guard
   def is_workday(event): return datetime.now().weekday() < 5
   self.bus.on_state_change("binary_sensor.motion",
       handler=self.on_workday_motion,
       where=P.Guard(is_workday)
   )

See :mod:`~hassette.bus.predicates` for the full list of built-ins.


Rate Control
------------

To handle noisy sensors or rate-limit handlers, use ``debounce`` or ``throttle``:

.. code-block:: python

   # Debounce: trigger after 2 seconds of silence
   self.bus.on_state_change("binary_sensor.motion", handler=self.on_settled, debounce=2.0)

   # Throttle: call at most once every 5 seconds
   self.bus.on_state_change("sensor.temperature", handler=self.on_temp_log, throttle=5.0)

   # One-time subscription
   self.bus.on_component_loaded("hue", handler=self.on_hue_ready, once=True)


Matching Multiple Entities
--------------------------

Use glob patterns to match multiple entities without listing them individually:

.. code-block:: python

   self.bus.on_state_change("light.*", handler=self.on_any_light)
   self.bus.on_state_change("sensor.bedroom_*", handler=self.on_bedroom_sensor)
   self.bus.on_attribute_change("climate.*", "temperature", handler=self.on_temp_change)
   self.bus.on_call_service(domain="light", service="turn_on",
                            where={"entity_id": "light.living_room_*"},
                            handler=self.on_living_room_lights)

For more complex patterns, use ``self.bus.on(...)`` with predicate-based filters.


Filtering Service Calls
-----------------------

``on_call_service`` supports both dictionary and predicate-based filtering.

**Dictionary filtering**

.. code-block:: python

   from hassette.const import NOT_PROVIDED

   # Literal match
   self.bus.on_call_service(
       domain="light",
       service="turn_on",
       where={"entity_id": "light.living_room", "brightness": 255},
       handler=self.on_bright_living_room,
   )

   # Require key presence (any value)
   self.bus.on_call_service(
       domain="light",
       service="turn_on",
       where={"brightness": NOT_PROVIDED},
       handler=self.on_brightness_set,
   )

   # Glob patterns (auto-detected)
   self.bus.on_call_service(
       domain="light",
       where={"entity_id": "light.bedroom_*"},
       handler=self.on_bedroom_lights,
   )

   # Callable conditions
   self.bus.on_call_service(
       domain="light",
       service="turn_on",
       where={"brightness": lambda v: v and v > 200},
       handler=self.on_bright_lights,
   )

**Predicate filtering**

.. code-block:: python

   from hassette import predicates as P

   self.bus.on_call_service(
       domain="notify",
       where=P.ServiceDataWhere.from_kwargs(
           message=lambda msg: "urgent" in msg.lower(),
           title=P.Not(P.StartsWith("DEBUG")),
       ),
       handler=self.on_urgent_notification,
   )

Predicates can be composed and reused for complex filtering logic.


See Also
--------

- :doc:`../index` — how apps fit into the overall architecture
- :doc:`../apps/index` — how apps fit into the overall architecture
- :doc:`../scheduler/index` — more on scheduling jobs and intervals
- :doc:`../api/index` — more on interacting with Home Assistant's APIs
- :doc:`../configuration/index` — Hassette and app configuration
