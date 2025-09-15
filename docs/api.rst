API
===

Async-first API for REST and WebSocket interactions.

Common calls
------------
.. code-block:: python

   await self.api.get_states()
   await self.api.get_state_value("sun.sun")
   await self.api.call_service("light", "turn_on", target={"entity_id": "light.bedroom"})

Note: Use ``self.api.sync`` only from non-async contexts.
