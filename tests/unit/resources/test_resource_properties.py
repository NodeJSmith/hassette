"""Tests for Resource properties not exercised elsewhere.

Verifies:
- cache: Resource no longer exposes a `cache` attribute -- cache moved to App only
- owner_id: top-level resource (no parent) returns its own unique_name
- register_task_bucket_factory: module-level function stores the factory on Resource
"""

from hassette.resources.base import Resource
from hassette.resources.operations import register_task_bucket_factory
from hassette.test_utils import make_mock_hassette

from .conftest import ConcreteResource


class TestNoCacheOnResource:
    """Cache moved from Resource to App-only (design/specs/013-resource-cache-redesign)."""

    def test_resource_has_no_cache_attribute(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)

        assert not hasattr(resource, "cache")


class TestOwnerId:
    """owner_id resolves to the nearest App's unique_name, or the resource's own for top-level resources."""

    def test_owner_id_without_parent_returns_own_unique_name(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)  # no parent passed

        assert resource.parent is None
        assert resource.owner_id == resource.unique_name

    def test_owner_id_with_parent_returns_parent_unique_name(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        parent = ConcreteResource(hassette=hassette)
        child = ConcreteResource(hassette=hassette, parent=parent)

        assert child.owner_id == parent.unique_name
        assert child.owner_id != child.unique_name


class TestRegisterTaskBucketFactory:
    """register_task_bucket_factory() is the module-level function hassette.task_bucket calls at import time."""

    def test_register_task_bucket_factory_stores_factory_on_class(self) -> None:
        original = Resource._default_task_bucket_factory
        try:

            def sentinel_factory(_hassette, _resource):
                return "sentinel-task-bucket"

            register_task_bucket_factory(sentinel_factory)

            assert Resource._default_task_bucket_factory is sentinel_factory
        finally:
            Resource._default_task_bucket_factory = original
