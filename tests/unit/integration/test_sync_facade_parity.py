"""Signature guard for the hand-written ``IntegrationSyncFacade``.

Unlike the bus and scheduler facades it isn't generated: it mirrors only the three ``add_*`` methods (plus a
``set()`` that takes a handle, which has no ``Integration`` counterpart). These tests stop a change to an
``Integration.add_*`` signature from silently leaving the facade behind.
"""

import inspect

import pytest

from hassette.integration.integration import Integration
from hassette.integration.sync import IntegrationSyncFacade


@pytest.mark.parametrize("method", ["add_button", "add_switch", "add_sensor"])
def test_facade_add_methods_match_integration(method: str) -> None:
    async_params = inspect.signature(getattr(Integration, method)).parameters
    sync_params = inspect.signature(getattr(IntegrationSyncFacade, method)).parameters
    assert [(p.name, p.kind, p.default, p.annotation) for p in sync_params.values()] == [
        (p.name, p.kind, p.default, p.annotation) for p in async_params.values()
    ]
