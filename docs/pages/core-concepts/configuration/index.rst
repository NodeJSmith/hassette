Configuration
=============

This guide helps you configure Hassette for a smooth first run. The settings below are not necessarily exhaustive,
but cover the most important and commonly used options.

.. seealso::

    First time here? Start with :doc:`../getting-started/index`.

Hassette requires very few settings to run - just the Home Assistant URL and a token. The URL can be provided
via the config file or environment variable; the token should be provided via environment variable or CLI
argument for security reasons.

Specifying the location of your files
-------------------------------------
By default, Hassette looks for ``hassette.toml`` in one of three locations (in order):

1. ``/config/hassette.toml`` (for Docker setups)
2. ``./hassette.toml`` (in the current working directory)
3. ``./config/hassette.toml`` (in a ``config`` subdirectory of the working directory)

The same locations are checked for a ``.env`` file, which can contain environment variables (e.g., for secrets).

If you want to use a different path for the config file, you can pass it via the CLI flag ``-c`` or
``--config-file``. You can also pass a different path for the ``.env`` file via ``-e`` or ``--env-file``.

.. code-block:: bash

    uvx hassette -c ./config/hassette.toml -e ./config/.env

Home Assistant Token
--------------------
Hassette needs a long-lived access token from your Home Assistant user profile to authenticate with the
WebSocket API. You can create one on your Home Assistant user profile page.

This can be provided to ``Hassette`` under multiple names: ``HASSETTE__TOKEN``, ``HOME_ASSISTANT_TOKEN``,
``HA_TOKEN`` if using environment variables, or ``--token``/``-t`` if using the CLI.

hassette.toml file
------------------
Hassette expects a ``hassette.toml`` file to set basic options and declare your apps. The structure is:

.. literalinclude:: basic_config.toml
   :language: toml


``[hassette]`` section
----------------------

- ``base_url``: Home Assistant URL (default ``http://127.0.0.1:8123``)
    - Set this to your HA address. If it includes a port, that port is used for API requests and WebSocket connections.
- ``app_dir``: Directory of your app modules; determines import package name
    - This should point to the directory where your app Python files live, such as ``src/apps``.
    - If you have a file named ``my_app.py``, Hassette will attempt to find it in ``src/apps/my_app.py`` and import it as ``apps.my_app``.

.. note::

    When running in Docker, you should typically mount your apps to ``/apps`` and config to ``/config``.

``[apps.<name>]`` section
--------------------------

- ``enabled``: determines whether Hassette loads this app; defaults to true, so only required if you want to disable
- ``filename``: the Python file within ``app_dir`` containing your app class (e.g., ``my_app.py``)
- ``class_name``: the class name of your app within that file (e.g., ``MyApp``)
- ``display_name``: optional; defaults to ``class_name``
- ``config``: either a single map, if you will only have one instance of your app, or multiple tables (``[[apps.<name>.config]]``) for multiple instances


Single vs multiple instances:

.. note::

     See :doc:`../apps/index` for a deeper walkthrough of app anatomy, ``App`` vs ``AppSync``,
     and how to use ``self.api``, ``self.bus``, ``self.scheduler``, ``self.logger``, and ``self.hassette``.

.. literalinclude:: single_instance.toml
   :language: toml

.. literalinclude:: multiple_instances.toml
   :language: toml

.. note::

    An *app* is validated by the ``AppManifest`` class, which checks that required fields are present and correctly typed. There can only be one ``[apps.<name>]`` section per app name.

    An *app config* is validated by your app's ``AppConfig`` subclass, which checks that required fields are present and correctly typed. There can be multiple ``[[apps.<name>.config]]`` sections per app name.


Typed app configuration
-----------------------

Your app classes inherit from ``App``, which is generic on a config type. The generic parameter gives you a typed config instance at ``self.app_config`` and validates TOML ``config`` values.

``AppConfig`` is a subclass of ``pydantic.BaseSettings``, so you can use all of Pydantic's features, including field validation, defaults, and environment variable support. Environment variables
or values in a ``.env`` file that match your app name and config field names will be passed to your app config. This can be a bit unwieldy at times, but you can also set an ``env_prefix`` to set a
custom prefix - in this case ``Hassette`` is no longer involved and ``pydantic`` will take over.

.. literalinclude:: ../apps/typed_config_example.py
   :language: python

.. literalinclude:: ../apps/typed_config_toml.toml
   :language: toml

.. code-block:: bash

    export MYAPP_REQUIRED_SECRET="s3cr3t"
    # OR
    export HASSETTE__APPS__MY_APP__CONFIG__REQUIRED_SECRET="s3cr3t"


Common pitfalls (and quick fixes)
---------------------------------
- WebSocket auth fails → set ``HASSETTE__TOKEN`` or ``HOME_ASSISTANT_TOKEN``
- Import errors for your app → ensure ``app_dir`` in TOML matches your mounted path
- Multiple instances not starting → use ``[[apps.<name>.config]]`` (list-of-tables)
- Token in TOML → move it to env/.env


Configuration sources (what wins?)
----------------------------------
Hassette merges configuration from multiple places (first writer wins):

#. CLI flags (e.g., ``-c``, ``--config``, ``--token``)
#. Environment variables (prefer ``HASSETTE__*``)
#. .env files:

    #. Will check ``/config/.env``, ``.env``, ``./config/.env`` by default
    #. If ``--config`` or ``-c`` is provided then this will take priority and the other locations will be skipped
#. File secrets (if used)
#. TOML files:

    #. Will check ``/config/hassette.toml``, ``./hassette.toml``, ``./config/hassette.toml`` by default
    #. If ``--config`` or ``-c`` is provided then this will take priority and the other locations will be skipped

Best practice: use env vars (or .env) for tokens and secrets; keep TOML non-secret.

See Also
--------

- :doc:`../index` — how apps fit into the overall architecture
- :doc:`../apps/index` — how apps fit into the overall architecture
- :doc:`../scheduler/index` — more on scheduling jobs and intervals
- :doc:`../bus/index` — more on subscribing to and handling events
- :doc:`../api/index` — more on interacting with Home Assistant's APIs
