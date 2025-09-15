Events
======

Subscribe to state changes and services using the Bus.

Subscriptions
-------------
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
All subscription methods accept ``where`` (a predicate or list of predicates), plus ``once``, ``debounce``, and ``throttle``.

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
Subscriptions return a ``Subscription`` handle. Call ``unsubscribe()`` to remove it.

.. code-block:: python

   sub = self.bus.on_entity("light.kitchen", handler=self.on_change)
   # later
   sub.unsubscribe()

Matching many entities ("globs")
---------------------------------
Both ``on_entity`` and ``on_attribute`` accept glob patterns in the entity ID.

.. code-block:: python

   # Any light entity (e.g., light.kitchen, light.bedroom, ...)
   self.bus.on_entity("light.*", handler=self.on_any_light, changed=True)

   # Only your app's lights
   self.bus.on_entity("light.my_*", handler=self.on_my_lights)

   # Attribute changes across many sensors
   self.bus.on_attribute("sensor.env_*", "temperature", handler=self.on_temp_change)

.. note::

   For truly custom patterns (e.g., multiple unrelated prefixes in one subscription), you can still use ``self.bus.on(...)`` with predicates like ``DomainIs`` or a custom ``Guard``. But simple globs are built into ``on_entity`` and ``on_attribute``.
