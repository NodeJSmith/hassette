Bus
======

The Bus is Hassette's event system for subscribing to Home Assistant events and Hassette framework events. It provides a clean, typed interface for reacting to state changes, service calls, and other system events.

.. note::

    Unlike AppDaemon, your handler receives a single :class:`~hassette.events.base.Event` object containing all the event data,
    plus any ``*args`` and ``**kwargs`` you specified when subscribing.
    The event object provides everything you need in a structured, typed format.

    .. code-block:: python

         from hassette import StateChangeEvent, states

         async def on_motion(self, event: StateChangeEvent[states.BinarySensorState]) -> None:
              data = event.payload.data
              self.logger.info("%s changed from %s to %s", event.topic, data.old_state.value, data.new_state.value)


    If you have a handler that does not need the event object, you can simply leave the event parameter out, and Hassette will not pass it.


Event model
-----------
Every event you receive from the bus is an :class:`~hassette.events.base.Event` dataclass with two main fields:

``topic``
    A string identifier describing what happened, such as ``hass.event.state_changed`` or
    ``hassette.event.service_status``. This is what the bus uses for routing events to your subscriptions.

.. note::

    Home Assistant events follow the format ``hass.event.<event_type>``, where ``event_type``
    matches the WebSocket event (e.g., ``state_changed``, ``call_service``).

    Hassette framework events use ``hassette.event.<event_type>`` for internal events like
    service lifecycle changes or file watching updates.

``payload``
    A typed wrapper containing the event data. Hassette uses two types of payloads:

    * **Home Assistant payloads** (:mod:`hassette.events.hass.hass`) wrap WebSocket event data.
      Access the actual content via ``event.payload.data``.
    * **Hassette payloads** (:mod:`hassette.events.hassette`) represent framework events
      like service status changes. Content is also available via ``event.payload.data``.

The consistent structure means you can always check ``event.topic`` to understand what happened
and access ``event.payload.data`` for the meaningful content.

.. code-block:: python

   from hassette.events import StateChangeEvent

   async def on_motion(self, event: StateChangeEvent) -> None:
       data = event.payload.data  # type: StateChangePayload
       entity_id = data.entity_id
       old_state = data.old_state  # Full state object with .value, .attributes, etc.
       new_state = data.new_state  # Full state object with .value, .attributes, etc.

       self.logger.info("%s changed from %s to %s",
                       entity_id, old_state.value, new_state.value)

Working with event data
-----------------------
The predicate helpers already narrow event types for you, but here are some tips for working
with event data:

* **State changes**: ``event.payload.data`` contains ``entity_id``, ``old_state``, and ``new_state``.
  State objects (``old_state`` and ``new_state``) are typed Pydantic models inheriting from
  :py:class:`~hassette.models.states.BaseState` with properties like:

  - ``.value`` - the state value (e.g., "on", "off", "25.5")
  - ``.attributes`` - a dict of entity attributes
  - ``.last_changed`` and ``.last_updated`` - timestamps
  - ``.domain`` and ``.entity_id`` - computed properties

* **Service calls**: ``event.payload.data`` is :class:`~hassette.events.hass.hass.CallServicePayload`
  with ``domain``, ``service``, and ``service_data`` fields.


Basic subscriptions
-------------------
These are the most common subscription methods. Each returns a ``Subscription`` handle that
you can store to unsubscribe later.

.. code-block:: python

   # Entity state changes
   self.bus.on_state_change("binary_sensor.motion", handler=self.on_motion, changed_to="on")

   # Attribute changes
   self.bus.on_attribute_change("climate.living_room", "temperature", handler=self.on_temp_change)

   # Service calls
   self.bus.on_call_service(domain="light", service="turn_on", handler=self.on_turn_on)

   # Home Assistant lifecycle events (built-in shortcuts)
   self.bus.on_homeassistant_restart(handler=self.on_restart)

   # Component loaded events
   self.bus.on_component_loaded("hue", handler=self.on_hue_loaded)

   # Service registered events
   self.bus.on_service_registered(domain="notify", handler=self.on_notify_service_added)

Advanced subscriptions
----------------------
For more complex scenarios, you can subscribe to any topic directly:

.. code-block:: python

   # Direct topic subscription
   self.bus.on(topic="hass.event.automation_triggered", handler=self.on_automation)

   # Hassette framework events
   self.bus.on_hassette_service_status(status=ResourceStatus.FAILED, handler=self.on_service_failure)
   self.bus.on_hassette_service_crashed(handler=self.on_any_crash)

Passing arguments to handlers
-----------------------------
You can pass additional arguments to your handlers using ``args`` and ``kwargs``:

.. code-block:: python

   # Pass extra context to the handler
   self.bus.on_state_change(
       "light.bedroom",
       handler=self.on_light_change,
       args=("bedroom",),
       kwargs={"room_type": "sleeping"}
   )

   async def on_light_change(self, event: StateChangeEvent, room_name: str, *, room_type: str):
       self.logger.info("Light in %s (%s) changed", room_name, room_type)

Predicates and filtering
------------------------
Predicates provide fine-grained control over which events trigger your handlers. Use them with
the ``where`` parameter on any subscription method.

.. code-block:: python

   from hassette import predicates as P

   # Combine multiple conditions
   self.bus.on_state_change(
      "binary_sensor.front_door",
      handler=self.on_door_open,
      changed_to="on",
      where=[
          P.Not(P.StateFrom("unknown")),  # Ignore transitions from unknown
          P.AttrTo("battery_level", lambda x: x is not None and x > 20)  # Only if battery OK
      ]
   )

   # Use logical operators
   self.bus.on_state_change(
      "media_player.living_room",
      handler=self.on_media_change,
      where=P.StateTo(P.IsIn(["playing", "paused"]))  # state is in ["playing", "paused"]
   )

   # Custom predicates with Guard
   def is_workday(event):
       return datetime.now().weekday() < 5

   self.bus.on_state_change(
       "binary_sensor.motion",
       handler=self.on_workday_motion,
       where=P.Guard(is_workday)
   )

See :mod:`~hassette.core.resources.bus.predicates.predicates` for a full list of built-in predicates.

Debounce and throttle
---------------------
Control the rate of handler invocations to handle noisy sensors or prevent spam:

.. code-block:: python

   # Debounce: only call after 2 seconds of silence
   self.bus.on_state_change(
      "binary_sensor.motion",
      handler=self.on_motion_settled,
      debounce=2.0
   )

   # Throttle: call at most once every 5 seconds
   self.bus.on_state_change(
      "sensor.temperature",
      handler=self.on_temp_log,
      throttle=5.0
   )

   # One-time subscription
   self.bus.on_component_loaded(
       "hue",
       handler=self.on_hue_ready,
       once=True  # Automatically unsubscribe after first call
   )


Matching multiple entities
----------------------------
Use glob patterns in entity IDs to match families of devices without listing them individually.
Hassette automatically expands globs into efficient predicate checks.

.. code-block:: python

   # All light entities
   self.bus.on_state_change("light.*", handler=self.on_any_light, changed=True)

   # Specific prefix
   self.bus.on_state_change("sensor.bedroom_*", handler=self.on_bedroom_sensor)

   # Attribute changes across device families
   self.bus.on_attribute_change("climate.*", "temperature", handler=self.on_temp_change)

   # Service calls affecting multiple entities
   self.bus.on_call_service(
       domain="light",
       service="turn_on",
       where={"entity_id": "light.living_room_*"},  # Glob in service data
       handler=self.on_living_room_lights
   )

.. note::

   For complex patterns that don't fit simple globs, use ``self.bus.on(...)`` with custom
   predicates like ``DomainMatches`` or write a ``Guard`` function.

Service call filtering
----------------------
``on_call_service`` offers powerful filtering options for service data through dictionaries
or explicit predicates.

**Dictionary filtering**

Pass a dictionary to ``where`` to filter on service data keys and values:

.. code-block:: python

   from hassette.const import NOT_PROVIDED

   # Basic literal matching
   self.bus.on_call_service(
       domain="light",
       service="turn_on",
       where={"entity_id": "light.living_room", "brightness": 255},
       handler=self.on_bright_living_room
   )

   # Require key presence (any value)
   self.bus.on_call_service(
       domain="light",
       service="turn_on",
       where={"brightness": NOT_PROVIDED},  # brightness key must exist
       handler=self.on_brightness_set
   )

   # Glob patterns (auto-detected)
   self.bus.on_call_service(
       domain="light",
       where={"entity_id": "light.bedroom_*"},
       handler=self.on_bedroom_lights
   )

   # Callable conditions
   self.bus.on_call_service(
       domain="light",
       service="turn_on",
       where={"brightness": lambda v: v is not None and v > 200},
       handler=self.on_bright_lights
   )

**Explicit predicate filtering**

For complex logic, use predicate classes directly:

.. code-block:: python

    from hassette import predicates as P

   # Multiple conditions with custom logic
   self.bus.on_call_service(
       domain="notify",
       where=P.ServiceDataWhere.from_kwargs(
           message=lambda msg: "urgent" in msg.lower(),
           title=P.Not(P.StartsWith("DEBUG"))
       ),
       handler=self.on_urgent_notification
   )

You can compose conditions to do more advanced filtering as needed.

.. code-block:: python

   from hassette import predicates as P

   # Multiple conditions with custom logic
   self.bus.on_call_service(
       domain="notify",
       where=P.ServiceDataWhere.from_kwargs(
           entity_id=P.IsIn(["sensor.door", "sensor.window"]),
           message=lambda msg: "urgent" in msg.lower(),
           title=P.Not(P.StartsWith("DEBUG"))
       ),
       handler=self.on_urgent_notification
   )


Unsubscribing
-------------
All subscription methods return a ``Subscription`` handle. Call ``unsubscribe()`` to remove
the listener when it's no longer needed.

.. code-block:: python

   # Store the subscription handle
   motion_sub = self.bus.on_state_change("binary_sensor.motion", handler=self.on_motion)

   # Later, remove the subscription
   motion_sub.unsubscribe()

   # Check subscription metadata
   self.logger.info("Subscribed to topic: %s", motion_sub.topic)

The subscription handle also provides access to the underlying listener configuration, which
can be useful for debugging or logging purposes.

.. note::

   Hassette automatically cleans up all subscriptions when an app shuts down, so manual
   unsubscription is typically only needed for conditional or temporary listeners.
