Apps Reference
==============

Attributes
----------

.. autoclass:: hassette.core.resources.app.app::App
    :no-index:
    :exclude-members: __init__, __new__

    .. autoattribute:: api
    .. autoattribute:: bus
    .. autoattribute:: scheduler
    .. autoattribute:: task_bucket
    .. autoattribute:: hassette
    .. autoattribute:: app_config_cls
    .. autoattribute:: app_config
    .. autoattribute:: instance_name
    .. autoattribute:: index
    .. autoattribute:: logger
    .. automethod:: hassette.core.resources.app.app::App.now


Async Methods
---------------

.. automethod:: hassette.core.resources.app.app::App.on_initialize
.. automethod:: hassette.core.resources.app.app::App.after_initialize
.. automethod:: hassette.core.resources.app.app::App.before_initialize
.. automethod:: hassette.core.resources.app.app::App.on_shutdown
.. automethod:: hassette.core.resources.app.app::App.before_shutdown
.. automethod:: hassette.core.resources.app.app::App.after_shutdown
.. automethod:: hassette.core.resources.app.app::App.send_event



Sync Methods (AppSync class)
-----------------------------

.. autoclass:: hassette.core.resources.app.app::AppSync

    .. automethod:: on_initialize_sync
    .. automethod:: after_initialize_sync
    .. automethod:: before_initialize_sync
    .. automethod:: on_shutdown_sync
    .. automethod:: before_shutdown_sync
    .. automethod:: after_shutdown_sync


App Config
------------

.. autoclass:: hassette.core.resources.app.app_config::AppConfig
    :members:
    :exclude-members: __init__, __new__, model_config
