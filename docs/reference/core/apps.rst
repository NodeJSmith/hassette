Apps Reference
==============

.. currentmodule:: hassette.core.resources.app.app

.. autoclass:: App
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
    .. automethod:: now
    .. automethod:: App.on_initialize
    .. automethod:: App.after_initialize
    .. automethod:: App.before_initialize
    .. automethod:: App.on_shutdown
    .. automethod:: App.before_shutdown
    .. automethod:: App.after_shutdown
    .. automethod:: App.send_event


.. autoclass:: AppSync
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
    .. automethod:: now
    .. automethod:: on_initialize_sync
    .. automethod:: after_initialize_sync
    .. automethod:: before_initialize_sync
    .. automethod:: on_shutdown_sync
    .. automethod:: before_shutdown_sync
    .. automethod:: after_shutdown_sync



.. currentmodule:: hassette.core.resources.app.app_config

.. autoclass:: AppConfig
    :members:
    :exclude-members: __init__, __new__, model_config
