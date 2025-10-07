Hassette
========

A simple, modern, async-first Python framework for building Home Assistant automations.

Why Hassette?
-------------
- **Modern developer experience** with typed APIs, Pydantic models, and IDE-friendly design
- **Async-first architecture** designed for modern Python from the ground up
- **Simple, transparent framework** with minimal magic and clear extension points
- **Focused mission**: does one thing well — run user-defined apps that interact with Home Assistant


Quick Start
-----------

Option A: Docker Compose (recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Ensure you have a valid Home Assistant long-lived access token.
2. Set the token in your environment as either ``HASSETTE__TOKEN`` or ``HOME_ASSISTANT_TOKEN``.
3. Start Hassette via Docker Compose.

Example ``docker-compose.yml``::

  services:
    hassette:
      image: ghcr.io/nodejsmith/hassette:latest
      container_name: hassette
      restart: unless-stopped
      environment:
        # Either variable works; HASSETTE__TOKEN has highest priority
        HASSETTE__TOKEN: ${HASSETTE__TOKEN}
        HOME_ASSISTANT_TOKEN: ${HOME_ASSISTANT_TOKEN}
      volumes:
        - ./config:/config   # hassette.toml (+ optional .env)
        - ./src:/apps        # your app files
        - data:/data         # persistent data (e.g., sqlite)
        - uv_cache:/uv_cache # uv cache for faster startup

  volumes:
    data:
    uv_cache:

Run::

  # In a shell where the token is set
  docker compose up -d

Option B: Local installation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Install Hassette and its CLI using uv (or pip):

.. code-block:: bash

  uv pip install hassette

2. Provide your Home Assistant token via environment variable or CLI. Then run:

.. code-block:: bash

  # Using environment variable
  export HASSETTE__TOKEN=<your_long_lived_access_token>
  uv run run-hassette -c ./config/hassette.toml -e ./config/.env

  # Or pass token on the command line (shorthand examples)
  uv run run-hassette -t <token>  # maps to token
  # or
  uv run run-hassette --token <token>


Configuration Basics
--------------------
Create a ``hassette.toml`` (e.g., in ``./config``)::

  [hassette]
  base_url = "http://localhost:8123"
  app_dir  = "src/apps"  # where your app modules live

  # Declare apps under the [apps.*] tables
  [apps.my_app]
  filename = "my_app.py"
  class_name = "MyApp"
  enabled = true
  # inline config for a single instance
  config = { some_option = true }


Learn More
~~~~~~~~~~~~~~~~~~~~~

.. toctree::
  :maxdepth: 2

  getting-started
  configuration
  apps
  api
  bus
  scheduler
  appdaemon-comparison
  pyscript-comparison
  reference/index



Indices and tables
------------------
* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
