"""Shared fixtures for web unit tests."""

import logging

import pytest


@pytest.fixture(autouse=True)
def _propagate_hassette_logger() -> None:
    """Ensure the "hassette" logger propagates so caplog can see records.

    Some other test in the session may have left ``propagate`` set to False (e.g. via
    ``enable_basic_logging()``); caplog relies on propagation to the root logger. Same
    workaround as ``tests/unit/test_validate_apps.py``.

    Living here rather than in the five caplog-using modules that used to each carry a copy
    means it is autouse for every module in this directory, including ones that never touch
    caplog. That is deliberate and inert: it forces the logger back to Python's own default,
    so a module that does not read log records cannot observe the difference.
    """
    logging.getLogger("hassette").propagate = True
