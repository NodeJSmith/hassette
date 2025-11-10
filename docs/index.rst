.. figure:: ./_static/hassette-logo.svg
   :alt: Hassette logo
   :class: hero

Hassette
========

A simple, modern, async-first Python framework for building Home Assistant automations.

Why Hassette?
-------------

Hassette is designed for developers who want to write Home Assistant automations in Python with modern tooling and type safety.

**Key Features:**

- **Type Safe**: Full type annotations and IDE support
- **Async-First**: Built for modern Python with async/await throughout
- **Simple & Focused**: Just Home Assistant automations - no complexity creep
- **Developer Experience**: Clear error messages, proper logging, hot-reloading

Built by a fellow HA geek frustrated with the HA python development experience. Read more about :doc:`why Hassette exists <pages/why-hassette>`.


Getting Started
===============

Get running with Hassette in a few lines of code:

**1. Create your first app:**

.. include:: ./getting-started/first_app.py
   :literal:

**2. Run Hassette:**

.. code-block:: bash

    uvx hassette -t $HOME_ASSISTANT_TOKEN --base-url 'http://127.0.0.1:8123' --app-dir .

**3. Hassette will auto-detect your app and start it:**

.. image:: ./_static/app-logs.png
   :alt: Hassette logs showing automation running

**Next Steps**

Ready to build something more complex? Check out the :doc:`getting started guide <pages/getting-started/index>` for a detailed walkthrough, explore :doc:`app patterns <pages/core-concepts/apps/index>`, or dive into the :doc:`API reference <pages/core-concepts/api/index>`.

.. toctree::
   :hidden:
   :maxdepth: 2

   pages/core-concepts/index
   pages/getting-started/index
   pages/why-hassette
   pages/comparisons/index
   code-reference/index
