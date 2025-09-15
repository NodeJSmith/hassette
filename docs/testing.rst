Testing
=======

Test matrix and commands
------------------------
- Run all tests (requires Docker/HA):

  .. code-block:: bash

     uv run nox -s tests

- Skip HA-dependent tests:

  .. code-block:: bash

     uv run nox -s tests_no_ha

- With pytest directly:

  .. code-block:: bash

     uv run pytest -m "not requires_ha"
