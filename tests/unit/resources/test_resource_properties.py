"""Tests for Resource properties not exercised elsewhere.

Verifies:
- cache: cached_property builds a real diskcache.Cache under data_dir/<class>/cache
- cache: a pre-set ._cache is returned as-is, without reconstruction
- owner_id: top-level resource (no parent) returns its own unique_name
- register_task_bucket_factory: module-level function stores the factory on Resource
"""

from diskcache import Cache

from hassette.resources.base import Resource
from hassette.resources.operations import register_task_bucket_factory
from hassette.test_utils import make_mock_hassette

from .conftest import ConcreteResource


class TestCache:
    """Resource.cache lazily builds a disk cache scoped to the resource's class."""

    def test_cache_builds_directory_and_returns_cache_instance(self, tmp_path) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        resource = ConcreteResource(hassette=hassette)

        cache = resource.cache

        assert isinstance(cache, Cache)
        expected_dir = tmp_path / "ConcreteResource" / "cache"
        assert expected_dir.is_dir()
        cache.close()

    def test_cache_is_memoized_across_accesses(self, tmp_path) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        resource = ConcreteResource(hassette=hassette)

        first = resource.cache
        second = resource.cache

        assert first is second
        first.close()

    def test_cache_returns_preset_cache_without_reconstruction(self, tmp_path) -> None:
        """When ._cache is already set (e.g. injected), the property returns it directly."""
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        resource = ConcreteResource(hassette=hassette)

        preset = Cache(tmp_path / "preset-cache-dir")
        resource._cache = preset

        # The class-scoped directory must NOT have been created — the preset short-circuits
        # before the mkdir/Cache(...) construction path runs.
        assert resource.cache is preset
        assert not (tmp_path / "ConcreteResource").exists()
        preset.close()


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
