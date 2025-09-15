API
===

Async-first API for REST and WebSocket interactions.

.. caution::

    Hassette uses different terminology than Home Assistant and AppDaemon, in an attempt to reduce confusion regarding states and entities.

    A ``state``, such as what is returned by *get_state()*, is an object representing the current status of an entity, including its attributes and metadata.

    A ``state value``, such as what is returned by *get_state_value()*, is the actual value of the state, e.g., ``"on"``, ``"off"``, ``23.5``, etc.

    An ``entity``, such as what is returned by *get_entity()*, is a richer object that includes the state and methods to interact with the entity, such as calling services on it.

.. note::

    Most API methods will return a typed model. For example, ``get_state`` expects an entity ID and a state model type, and returns an instance of that model.

    .. code-block:: python

       from hassette import states
       light_state = await self.api.get_state("light.bedroom", states.LightState)
       brightness = light_state.attributes.brightness  # float | None

    These methods will have a ``raw`` variant that returns untyped data (``dict`` or ``Any``) if you prefer that style.

    .. code-block:: python

       raw_state = await self.api.get_state_raw("light.bedroom")
       brightness = raw_state["attributes"].get("brightness")  # Any


    An exception to this is ``get_state_value``, which does not accept a model and always returns a raw string from Home Assistant. You can use ``get_state_value_typed`` if you want a typed return value.

Main methods
------------
- States: ``get_states()``, ``get_state_raw(entity_id)``, ``get_state(entity_id, StateType)``, ``get_state_value(entity_id)``, ``get_state_value_typed(entity_id, StateModel)``
- Entities: ``get_entity(entity_id, EntityModel)``, ``get_entity_or_none(...)``
- Attributes: ``get_attribute(entity_id, attribute)``
- Services: ``call_service(domain, service, target=..., **data)``, ``turn_on(entity_id, domain=...)``, ``turn_off(...)``, ``toggle_service(...)``
- Events: ``fire_event(event_type, event_data=None)``
- History/Logbook: ``get_history(...)``, ``get_histories(...)``, ``get_logbook(...)``
- Misc: ``render_template(template, variables=None)``, ``set_state(entity_id, state, attributes=None)``, ``delete_entity(entity_id)``, ``get_camera_image(entity_id, timestamp=None)``, ``get_calendars()``, ``get_calendar_events(...)``

Examples
--------
.. code-block:: python

   # Turn on a light with brightness
   await self.api.turn_on("light.bedroom", domain="light", brightness=200)

   # Fetch a typed state
   from hassette import states
   s = await self.api.get_state("light.bedroom", states.LightState)

   # Call a service directly
   await self.api.call_service("notify", "mobile_app_me", message="Hello from Hassette")

Sync facade
-----------
``self.api.sync`` mirrors the async API with blocking calls for synchronous code. Do not call from within an event loop.

.. code-block:: python

   # Inside an AppSync or non-async context
   self.api.sync.turn_off("light.bedroom", domain="light")

Typing status
-------------
- Many models and read operations are strongly typed.
- Service calls are not fully typed yet; finishing this is a high priority. For now, ``call_service`` accepts ``**data`` and performs string normalization for REST parameters.
