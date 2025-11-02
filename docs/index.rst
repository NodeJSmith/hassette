Hassette
========

A simple, modern, async-first Python framework for building Home Assistant automations.

Why Hassette?
-------------
- **Modern developer experience** with typed APIs, Pydantic models, and IDE-friendly design
- **Async-first architecture** designed for modern Python from the ground up
- **Simple, transparent framework** with minimal magic and clear extension points
- **Focused on Home Assistant** with first-class support for its APIs and event bus

Getting Started
================

You can get running with Hassette in a few lines of code.

#) Copy the below to a file.

.. include:: ./getting-started/first_app.py
   :literal:


#) Run Hassette, giving it your Home Assistant token, url, and app directory (where you saved the above file).

.. code-block:: bash

    uvx hassette -t $HOME_ASSISTANT_TOKEN --base-url 'http://192.168.1.179:8123' --app-dir .


See the :doc:`getting started guide <getting-started/index>` for more details.


Learn More
~~~~~~~~~~~~~~~~~~~~~

.. toctree::
  :maxdepth: 1
  :caption: Next steps

  configuration
  apps
  api
  bus
  scheduler
  comparisons/index
  code-reference/index
