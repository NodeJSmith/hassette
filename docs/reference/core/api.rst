API Reference
=============

The Api class provides access to the Home Assistant REST and WebSocket APIs. It is async-first and provides a ``sync`` property to access a synchronous facade.

Api
-----

.. autoclass:: hassette.core.resources.api.api.Api
   :members:
   :undoc-members:
   :exclude-members: sync


Sync Facade
-------------

.. autoclass:: hassette.core.resources.api.api.ApiSyncFacade
   :members:
   :undoc-members:
   :exclude-members: sync


Services
--------

.. autoclass:: hassette.core.services.api_service._ApiService
   :members:
   :undoc-members:


.. autoclass:: hassette.core.services.websocket_service._Websocket
   :members:
   :undoc-members:
