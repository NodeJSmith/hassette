Apps
====

Apps are the core building blocks of automations in Hassette. They encapsulate logic, state, and configuration, and interact with Home Assistant through a rich API.
Apps can be asynchronous or synchronous, depending on your needs. Asynchronous apps are preferred for most use cases, as they can take full advantage of Python's async
capabilities and integrate seamlessly with Hassette's event loop. Synchronous apps are supported for legacy code or libraries that do not support async - these are run
using ``asyncio.to_thread`` to avoid blocking the event loop.

Apps are defined as Python classes that inherit from :class:`~hassette.app.app.App` (for async) or :class:`~hassette.app.app.AppSync` (for sync) and are configured using
a Pydantic model that inherits from :class:`~hassette.app.app_config.AppConfig`.


Example
-------

.. literalinclude:: example_app.py
   :language: python

App Capabilities
----------------
  - :class:`self.api <hassette.api.api.Api>`

    - Async Home Assistant API (see :doc:`../api/index`). In sync apps, use :class:`self.api.sync <hassette.api.sync.ApiSyncFacade>`.

  - :class:`self.bus <hassette.bus.bus.Bus>`

    - Subscribe to events with filters (see :doc:`../bus/index`).

  - :class:`self.scheduler <hassette.scheduler.scheduler.Scheduler>`

    - Run jobs on intervals or cron (see :doc:`../scheduler/index`).

  - :class:`self.logger <logging.Logger>`

    - Individual logger per app instance. Standard lib logger, use it as normal.

  - :class:`self.app_config <hassette.app.app_config.AppConfig>`

    - The parsed config for this app instance, typed as the app's :class:`AppConfig <hassette.app.app_config.AppConfig>` class.

  - :attr:`self.index <hassette.app.app.App.index>`

    - The index of this app instance in the config list, or 0 if only a single instance.

  - :attr:`self.instance_name <hassette.app.app.App.instance_name>`

    - The name of this app instance as set in the config, or ``<ClassName>.[index]`` if not set.

  - :meth:`self.now <hassette.app.app.App.now>`

    - Get the current time as :class:`ZonedDateTime <whenever.ZonedDateTime>`.

Advanced Capabilities
---------------------
    - :class:`self.hassette <hassette.core.Hassette>`: Access to the core ``Hassette`` instance for advanced use cases.
    - :class:`self.task_bucket <hassette.task_bucket>`: Low-level sync/async task management (documentation coming soon).
    - :meth:`self.send_event <hassette.core.Hassette.send_event>`: Emit custom events (currently not very ergonomic; will be improved in a future release).
    - :class:`self.app_manifest <hassette.config.app_manifest.AppManifest>`: Class-level :class:`AppManifest <hassette.config.app_manifest.AppManifest>` with details that ``Hassette`` needs to start the app.
    - :attr:`self.status <hassette.resources.mixins.LifecycleMixin.status>`: Current status of the app (NOT_STARTED, STARTING, RUNNING, STOPPED, FAILED, CRASHED).
    - :attr:`self.ready_event <hassette.resources.mixins.LifecycleMixin.ready_event>`: An :class:`asyncio.Event` that is set when :meth:`mark_ready <hassette.resources.mixins.LifecycleMixin.mark_ready>` is called.

     - Note: This is *not* set automatically and is not necessary for most apps. It can be set manually to signal readiness to other parts of your app or to coordinate between multiple apps.

    - :attr:`self.shutdown_event <hassette.resources.mixins.LifecycleMixin.shutdown_event>`: An :class:`asyncio.Event` that is set when the app begins shutdown.

     - Note: This is set automatically during shutdown and can be used in your app to check if shutdown is in progress and to clean up resources or exit gracefully.


Lifecycle
---------
All resources, including Apps, follow a clear lifecycle with startup and shutdown hooks. As each app is started, it is transitioned to the STARTING state, the initialization hooks are called in order, and then the app is marked RUNNING.
Apps do not start until all services they depend on are available, which include the Home Assistant API, the event bus, and the scheduler. This ensures that your app can rely on these services being available in your initialization logic.

When the App is shutting down (including when being reloaded), the ``shutdown_event`` is set, the shutdown hooks are called in order, the ``cleanup`` method is called to clean up resources, and then the app is marked STOPPED. If an
unhandled exception occurs during startup or shutdown, the app is marked as FAILED, but the ``cleanup`` method is still called to ensure resources are cleaned up.

- Initialization
   - Hook into startup with ``on_initialize``, ``before_initialize``, or ``after_initialize`` (``on_initialize_sync``, etc. for sync apps).
   - All resources and services are available in these hooks.
   - When your application is starting up the ``@final`` method ``initialize`` is called, which in turn calls these hooks in order:

    1. :meth:`before_initialize <hassette.resources.base.Resource.before_initialize>` - This runs prior to the app's own ``on_initialize``.
    2. :meth:`on_initialize <hassette.resources.base.Resource.on_initialize>` - This is where you should put most of your initialization logic, such as subscriptions and scheduled jobs.
    3. :meth:`after_initialize <hassette.resources.base.Resource.after_initialize>` - This runs after the app's own ``on_initialize``.

   - You never need to call ``super()`` in these methods, as they are hooks, not overrides.

- Shutdown
   - Hook into shutdown with ``on_shutdown``, ``before_shutdown``, or ``after_shutdown`` (``on_shutdown_sync``, etc. for sync apps).
   - When your application is shutting down the ``@final`` method ``shutdown`` is called, which in turn calls these hooks in order:

    1. :meth:`before_shutdown <hassette.resources.base.Resource.before_shutdown>`
    2. :meth:`on_shutdown <hassette.resources.base.Resource.on_shutdown>`
    3. :meth:`after_shutdown <hassette.resources.base.Resource.after_shutdown>`

   - After these hooks are called, the ``cleanup`` method is called to clean up resources.

    - This will cancel all subscriptions and scheduled jobs automatically, as well as cancelling all tasks in your app's task bucket.

   - If you set up your own resources (e.g. open files, network connections), clean them up in ``on_shutdown`` or ``after_shutdown``.
   - Generally speaking you will not need to do any cleanup, as the framework handles it for you.

.. warning::

    You cannot override ``initialize``, ``shutdown``, or ``cleanup`` directly; use the hooks instead. If you attempt to do so, a :class:`~hassette.exceptions.CannotOverrideFinalError` will be raised.

.. note::

    ``Hassette`` performs a pre-check prior to spinning up all services to ensure that all apps can be imported. This will catch import/syntax/name errors early,
    along with errors caused by overriding final methods.


AppConfig Class
-------------------------
Every app should define a Pydantic model that inherits from :class:`~hassette.app.app_config.AppConfig` to represent its configuration (although this is not required).
This model is used to parse and validate the configuration provided in the TOML file.

The base AppConfig class includes two fields by default:

 - ``instance_name: str | None``: Optional name for the instance, used in logging.
 - ``log_level: str | None``: Optional log level override, defaults to the global app level or the hassette log level.

.. literalinclude:: presence_app_config_example.py
   :language: python


Typed app configuration
-----------------------

Your app classes inherit from ``App``, which is generic on a config type. The generic parameter gives you a typed config instance at ``self.app_config`` and validates TOML ``config`` values.

.. literalinclude:: typed_config_example.py
   :language: python

.. literalinclude:: typed_config_toml.toml
   :language: toml


App Secrets
-----------------

``AppConfig`` is a subclass of ``pydantic.BaseSettings``, so you can use all of Pydantic's features, including field validation, defaults, and environment variable support.
Environment variables or values in a ``.env`` file that match your app name and config field names will be passed to your app config. This can be a bit unwieldy at times, due to the nested delimiters.

It may be easier to use the ``env_prefix`` configuration value to set a custom prefix - in this case ``Hassette`` is no longer involved and ``pydantic`` will take over. For example,
if you set ``env_prefix = "MYAPP_"``, then an app config field named ``required_secret`` would be set from the environment variable ``MYAPP_REQUIRED_SECRET``. Otherwise, you would need to use
``HASSETTE__APPS__MY_APP__CONFIG__REQUIRED_SECRET`` to set the same field.


.. code-block:: bash

    export MYAPP_REQUIRED_SECRET="s3cr3t"
    # OR
    export HASSETTE__APPS__MY_APP__CONFIG__REQUIRED_SECRET="s3cr3t"


See also
--------
- :doc:`../configuration/index` for TOML structure and app_dir import rules
- :doc:`../bus/index` for subscription patterns and predicates
- :doc:`../api/index` for service calls, templates, and history
- :doc:`../scheduler/index` for job scheduling and management
