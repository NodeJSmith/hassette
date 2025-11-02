Getting Started
===============

This guide walks you from zero to a running Hassette instance with a tiny automation app.

Prerequisites
-------------
- A running Home Assistant instance with WebSocket API access
- A long-lived access token from your HA profile
- Either Docker Compose or Python 3.11+ with ``uv`` (or pip)

1) Create your first app
------------------------
Create a Python file in your apps directory (e.g., ``src/apps/my_app.py``):

.. include:: ./first_app.py
   :literal:

Type-safe by default
~~~~~~~~~~~~~~~~~~~~
The event passed to your handler is fully typed. For lights, ``event`` is a
``StateChangeEvent[states.LightState]``, so your editor can offer completions and
catch mistakes early.

.. code-block:: python

   # Inside your handler
   data = event.payload.data  # StateChangePayload[LightState]
   brightness = data.new_state.attributes.brightness  # float | None
   if data.new_state_value == "on": # new_state_value handles missing `new_state` for you
       ...  # do something when the light turns on

1) Add configuration
--------------------
Create ``config/hassette.toml`` (or ``hassette.toml`` in your working directory):

.. include:: ./config.toml
   :literal:

3) Provide your Home Assistant token
------------------------------------
Export one of these environment variables before starting Hassette:

.. code-block:: bash

    export HASSETTE__TOKEN=<your_long_lived_access_token>
    # or
    export HOME_ASSISTANT_TOKEN=<your_long_lived_access_token>

4) Run Hassette
---------------

Option A - Docker Compose
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

    services:
      hassette:
         image: ghcr.io/nodejsmith/hassette:latest
         container_name: hassette
         restart: unless-stopped
         environment:
            HASSETTE__TOKEN: ${HASSETTE__TOKEN}
         volumes:
            - ./config:/config
            - ./src:/apps

.. code-block:: bash

    docker compose up -d

Option B - Local (uv)
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    uvx hassette -c ./config/hassette.toml -e ./config/.env

To pass the token on the command line instead of env vars:

.. code-block:: bash

    uvx hassette --token <your_long_lived_access_token>

5) Verify it's working
----------------------
- You should see log lines indicating WebSocket authentication and service startup.
- Set HASSETTE__LOG_LEVEL=DEBUG to see detailed logs.

Next steps
----------
- Explore the :doc:`../bus` page for powerful filtering and predicates.
- Learn the :doc:`../api` for service calls, state access, and history.
- Schedule recurring jobs with the :doc:`../scheduler`.
- Build richer automations with typed configs and lifecycle details in :doc:`../apps`.
