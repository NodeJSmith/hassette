Events
======

Subscribe to state changes and services using the Bus.

.. note::

    Unlike AppDaemon, your callable will only receive **one argument**, the event object. The event object
    will have everything you need. For state change events it will include the old and new states, and for
    service calls it will include the service data, etc. More details are provided below.

    .. code-block:: python

         from hassette import StateChangeEvent, states

         async def on_motion(self, event: StateChangeEvent[states.ButtonState]) -> None:
              data = event.payload.data
              self.log.info("%s changed from %s to %s", event.topic, data.old_state_value, data.new_state_value)

Event model
-----------
Every message you receive from the bus is a :class:`hassette.core.events.Event` dataclass. It has two
fields:

``topic``
    A string identifier that describes what happened, such as ``hass.event.state_changed`` or
    ``hassette.event.service_status``. The topic is what the bus uses when you subscribe with helpers
    like ``on_entity`` or ``on_call_service``.

.. note::

    Home Assistant topics will always have the format of ``hass.event.<event_type>``. The event type
    is the same as the ``event_type`` field in the raw WebSocket event payload (e.g.,
    ``state_changed``, ``call_service``, etc).

    Hassette topics use the format ``hassette.event.<event_type>`` for framework-level events.

``payload``
    A typed wrapper around the event data. Hassette uses two flavours of payloads:

    * **Hass payloads** (:mod:`hassette.core.events.hass`) wrap the dictionaries that Home
      Assistant sends over the WebSocket. The actual state, service call arguments, and other
      details live under ``event.payload.data``.
    * **Hassette payloads** (:mod:`hassette.core.events.hassette`) represent framework level events
      such as service lifecycle or websocket status updates. They also expose their contents via
      ``payload.data``, but those values are Hassette dataclasses like
      :class:`hassette.core.events.hassette.ServiceStatusPayload`.

Because of this structure you can always look at ``event.topic`` to decide what happened and reach
for ``event.payload.data`` to access the meaningful content. The payload also carries an
``event_type`` so you can branch on finer-grained variants when several events share a topic.

.. code-block:: python

   from hassette.core.events import StateChangeEvent

   async def on_motion(self, event: StateChangeEvent) -> None:
       data = event.payload.data  # type: StateChangePayload
       self.log.info("%s changed from %s to %s", event.topic, data.old_state_value, data.new_state_value)

Working with payload data
-------------------------
Most predicate helpers already narrow the event type, but you can always inspect the payload
manually. A few practical tips:

* ``event.payload.data`` is where the event-specific fields live.
    * Home Assistant state change events are a dataclass that holds ``entity_id``, ``old_state``, and ``new_state``. ``old_state`` and ``new_state`` are themselves Pydantic models inheriting from :py:class:`~hassette.models.states.BaseState` that represent the full state object, so you can access attributes like ``value`` (which is the state value) and ``attributes`` in a typed manner.
    * Other Home Assistant events have their own payload dataclasses, such as :class:`~hassette.core.events.hass.ServiceCallPayload` for service calls.
* All Hassette event payloads are dataclasses; you still access them through ``payload.data``.
* Payload objects are immutable dataclasses, so copy information out if you need to modify it later.

Subscriptions
-------------
Subscriptions are the main entry point for reacting to bus traffic. Each helper registers a
predicate under the hood and wires your coroutine up to receive matching events. The examples below
show the most common entry points; all of them return a ``Subscription`` handle you can store if
you need to unsubscribe later.
.. code-block:: python

   # Entity state changes
   self.bus.on_entity("binary_sensor.motion", handler=self.on_motion, changed_to="on")

   # Attribute changes
   self.bus.on_attribute("mobile_device.me", "battery_level", handler=self.on_battery)

   # Service calls
   self.bus.on_call_service(domain="light", service="turn_on", handler=self.on_turn_on)

   # Home Assistant restart (via service call)
   self.bus.on_homeassistant_restart(handler=self.on_restart)

Predicates, debounce, throttle
------------------------------
Predicates let you express additional guards beyond the basic entity/service filtering. Combine
them with debouncing or throttling to tame noisy streams without writing boilerplate state.
Every subscription helper accepts ``where`` (a predicate or list of predicates), along with
``once``, ``debounce``, and ``throttle`` keyword arguments for delivery control.

.. code-block:: python

   from hassette.core.bus import predicates as P

   # Door opened events, but ignore noisy transitions from 'unknown'
   self.bus.on_entity(
      "binary_sensor.front_door",
      handler=self.on_open,
      changed_to="on",
      where=P.Not(P.ChangedFrom("unknown")),
      debounce=0.5,
   )

   # Media player changes to either playing or paused (OR logic)
   self.bus.on_entity(
      "media_player.living_room",
      handler=self.on_media_change,
      where=P.AnyOf((P.ChangedTo("playing"), P.ChangedTo("paused"))),
   )

Unsubscribing
-------------
Subscriptions return a ``Subscription`` handle. Call ``unsubscribe()`` on that handle to detach the
listener when it is no longer needed—for example during cleanup or when a conditional workflow
finishes. You can also use the handle to capture metadata such as the topic you subscribed to.

.. code-block:: python

   sub = self.bus.on_entity("light.kitchen", handler=self.on_change)
   # later
   sub.unsubscribe()

Matching many entities ("globs")
---------------------------------
Several helpers support globbing in their entity ID parameter so you can cover families of devices
without enumerating them manually. Behind the scenes Hassette expands the glob into predicate checks
for each incoming event, keeping your own code simple.

.. code-block:: python

   # Any light entity (e.g., light.kitchen, light.bedroom, ...)
   self.bus.on_entity("light.*", handler=self.on_any_light, changed=True)

   # Only your app's lights
   self.bus.on_entity("light.my_*", handler=self.on_my_lights)

   # Attribute changes across many sensors
   self.bus.on_attribute("sensor.env_*", "temperature", handler=self.on_temp_change)

.. note::

   For truly custom patterns (e.g., multiple unrelated prefixes in one subscription), you can
   use ``self.bus.on(...)`` with predicates like ``DomainIs`` or a custom ``Guard``.
