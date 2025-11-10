Apps
====

Apps are the heart of Hassette — the logic *you* write to respond to events and manipulate resources.
Each app encapsulates its own behavior, configuration, and internal state, interacting with Home Assistant through a rich, typed API.

Apps can be **asynchronous** or **synchronous**, depending on your needs.
Async apps are preferred for most use cases since they integrate directly with Hassette's event loop and can run multiple tasks concurrently.
Sync apps are supported for compatibility with legacy code or blocking libraries — they're automatically run in a background thread using ``asyncio.to_thread()`` so they never block the event loop.

App Structure
-------------

.. mermaid::

   graph LR
       A[App] -->|uses| Api
       A -->|subscribes to| Bus
       A -->|schedules| Scheduler

Defining an App
---------------

Every app is a Python class that inherits from :class:`~hassette.app.app.App` (for async apps)
or :class:`~hassette.app.app.AppSync` (for sync apps).

Each app may also define a Pydantic configuration model inheriting from :class:`~hassette.app.app_config.AppConfig`,
which parses and validates its configuration.

.. literalinclude:: example_app.py
   :language: python

This small class is all you need to create a working Hassette app.


Core Capabilities
-----------------

Each app automatically receives several built-in helpers — interfaces to core services that make automation easy and expressive:

- ``self.api`` — Typed async interface to Home Assistant's REST and WebSocket APIs.
  See :doc:`../api/index`.

- ``self.bus`` — Subscribe to and handle events.
  See :doc:`../bus/index`.

- ``self.scheduler`` — Schedule jobs to run on intervals or cron-like expressions.
  See :doc:`../scheduler/index`.

- ``self.logger`` — Standard :class:`logging.Logger` instance preconfigured for your app.

- ``self.app_config`` — Parsed configuration model for this app instance, typed to your subclass of ``AppConfig``.

Additional attributes like ``self.instance_name`` and ``self.index`` are available for logging and introspection.

For a detailed list of attributes and advanced capabilities, see :doc:`app-advanced`.


Lifecycle
---------

Every app follows a structured lifecycle with clear startup and shutdown phases.
Hassette ensures that all services (API, Bus, Scheduler, etc.) are ready before your app's initialization hooks are called,
and it cleans up all resources automatically on shutdown.

**Initialization**

During startup, Hassette transitions the app through ``STARTING → RUNNING`` and invokes the following hooks in order:

1. :meth:`before_initialize <hassette.resources.base.Resource.before_initialize>`
2. :meth:`on_initialize <hassette.resources.base.Resource.on_initialize>`
3. :meth:`after_initialize <hassette.resources.base.Resource.after_initialize>`

Use these to register event handlers, schedule jobs, or perform any startup logic.
You don't need to call ``super()`` in these hooks — they're discovered automatically.

**Shutdown**

When shutting down or reloading, Hassette transitions the app through ``STOPPING → STOPPED``
and calls the shutdown hooks in order:

1. :meth:`before_shutdown <hassette.resources.base.Resource.before_shutdown>`
2. :meth:`on_shutdown <hassette.resources.base.Resource.on_shutdown>`
3. :meth:`after_shutdown <hassette.resources.base.Resource.after_shutdown>`

Afterward, the ``cleanup`` method runs automatically, canceling all subscriptions, jobs, and active tasks.
If your app allocates its own resources (files, network sockets, etc.), clean them up in ``on_shutdown`` or ``after_shutdown``.

.. warning::

   You cannot override ``initialize``, ``shutdown``, or ``cleanup`` directly — use the lifecycle hooks instead.
   Attempting to override these will raise a :class:`~hassette.exceptions.CannotOverrideFinalError`.


App Configuration
-----------------

Each app can define a Pydantic configuration model (subclassing :class:`~hassette.app.app_config.AppConfig`) to parse and validate its configuration.
These config classes are used when parsing TOML configuration files and can include default values, field constraints,
and environment variable support.

The base ``AppConfig`` includes two optional fields:

- ``instance_name: str | None`` — Used for logging and identification.
- ``log_level: str | None`` — Optional log-level override; defaults to the global setting.

Because ``App`` is generic on the config type, specifying it allows IDEs and type checkers to infer the correct type automatically.

.. literalinclude:: typed_config_example.py
   :language: python

.. literalinclude:: typed_config_toml.toml
   :language: toml


App Secrets
-----------

Because ``AppConfig`` inherits from :class:`pydantic_settings.BaseSettings`,
you can load secrets from environment variables or ``.env`` files.

By default, environment variables follow Hassette's nested naming convention:

``HASSETTE__APPS__MY_APP__CONFIG__REQUIRED_SECRET``

You can simplify this by defining an ``env_prefix`` in your config class:

.. code-block:: python

    from hassette import AppConfig
    from pydantic_settings import SettingsConfigDict

    class MyAppConfig(AppConfig):
        model_config = SettingsConfigDict(env_prefix="MYAPP_")
        required_secret: str

Then the same field can be set with:

.. code-block:: bash

    export MYAPP_REQUIRED_SECRET="s3cr3t"


See Also
--------

- :doc:`../index` — how apps fit into the overall architecture
- :doc:`../scheduler/index` — more on scheduling jobs and intervals
- :doc:`../bus/index` — more on subscribing to and handling events
- :doc:`../api/index` — more on interacting with Home Assistant's APIs
- :doc:`../configuration/index` — Hassette and app configuration
