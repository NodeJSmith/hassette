API Reference
=============

The Api class provides access to the Home Assistant REST and WebSocket APIs. It is async-first and provides a ``sync`` property to access a synchronous facade.

Api
-----

.. autoclass:: hassette.api.Api
   :members:
   :undoc-members:
   :exclude-members: sync


Sync Facade
-------------

.. autoclass:: hassette.api.ApiSyncFacade
   :members:
   :undoc-members:


Services
--------

.. autoclass:: hassette.core.services.api_service._ApiService
   :members:
   :undoc-members:


.. autoclass:: hassette.core.services.websocket_service._WebsocketService
   :members:
   :undoc-members:
