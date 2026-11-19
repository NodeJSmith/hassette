"""A failed commit of an instance's declared entities, through a real app and the real lifecycle (spec 157 D10)."""

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from hassette_wire import ResourceStatus

from hassette import IntegrationHandleClosedError
from hassette.core.app_factory import AppFactory
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry
from hassette.integration.declarations import EntityState
from tests.support.app_manifests import make_test_app_manifest
from tests.support.outcomes import AnyNameOutcomes

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from hassette import HassetteConfig
    from hassette.testing import HassetteHarness
    from tests.data.apps.integration_commit_app import IntegrationCommitApp

APP_KEY = "integration_commit"
INSTANCE_NAME = "integration_commit"


@pytest.fixture
async def harness(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]", test_config_with_apps: "HassetteConfig"
) -> "AsyncIterator[HassetteHarness]":
    async with hassette_harness(test_config_with_apps).with_app_handler().with_scheduler().with_integration() as h:
        yield h


async def run_instance(
    harness: "HassetteHarness", registry: AppRegistry, lifecycle: AppLifecycleService
) -> "tuple[IntegrationCommitApp, AnyNameOutcomes]":
    """Create and initialize the app's one instance, returning it."""
    manifest = make_test_app_manifest(APP_KEY, "integration_commit_app.py", "IntegrationCommitApp")
    registry.set_manifests({APP_KEY: manifest})
    results = AppFactory(harness.hassette, registry).create_instances(
        APP_KEY, manifest, force_reload=True, outcomes=AnyNameOutcomes()
    )
    [app] = results.values()
    assert not isinstance(app, Exception)
    registry.set_status(APP_KEY, INSTANCE_NAME, ResourceStatus.NOT_STARTED, app=app)
    outcomes = AnyNameOutcomes()
    await lifecycle.initialize_instances(APP_KEY, {INSTANCE_NAME: app}, manifest, outcomes=outcomes)
    return app, outcomes


async def test_failed_commit_runs_shutdown_hook_fails_instance_and_keeps_the_committed_set(
    harness: "HassetteHarness",
) -> None:
    registry = AppRegistry()
    lifecycle = AppLifecycleService(harness.hassette, parent=None, registry=registry)
    service = harness.integration_service
    key = (APP_KEY, INSTANCE_NAME)

    first, _ = await run_instance(harness, registry, lifecycle)
    assert registry.get_status(*key) is ResourceStatus.RUNNING
    assert [(e.declaration.key, e.state) for e in service.entities(*key)] == [("temp", EntityState(21.5, {}))]
    # The first instance's own shutdown hook writes while it still owns the set, so the set ends at 30.0.
    await lifecycle.shutdown_instance(first, outcomes=AnyNameOutcomes())
    committed = EntityState(30.0, {})
    assert [(e.declaration.key, e.state) for e in service.entities(*key)] == [("temp", committed)]
    revision = service.revision

    with patch.object(service, "persist_instance_set", side_effect=OSError("disk full")):
        second, outcomes = await run_instance(harness, registry, lifecycle)

    assert second.shutdown_hook_ran
    assert isinstance(second.shutdown_set_error, IntegrationHandleClosedError)
    assert second.shutdown_set_error.key == "temp"
    assert second.shutdown_set_error.instance_name == INSTANCE_NAME
    assert "temp" in str(second.shutdown_set_error)
    assert registry.get_status(*key) is ResourceStatus.FAILED
    [outcome] = outcomes.snapshot()
    assert outcome.result.value == "failed"
    assert [(e.declaration.key, e.state) for e in service.entities(*key)] == [("temp", committed)]
    assert service.revision == revision

    await lifecycle.shutdown_all()
