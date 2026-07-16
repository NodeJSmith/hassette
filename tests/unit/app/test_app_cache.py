"""Unit tests for App/AppSync cache wiring (design/specs/013-resource-cache-redesign).

Verifies:
- cache_key defaults to `{app_key}/{index}` and can be overridden via AppManifest.cache_key
- different instance indices produce different cache directories/db paths
- an injected DummyCache (via the `cache=` constructor parameter) is used directly --
  no AsyncCache is constructed
- App.cleanup() closes the cache, and swallows a close() exception
- AppSync.before_initialize() calls super() so cache init fires for sync apps too
- default_cache_ttl resolution chain: class attribute -> HassetteConfig.default_cache_ttl -> None
"""

from unittest.mock import AsyncMock

from hassette.app.app import App, AppSync
from hassette.app.app_config import AppConfig
from hassette.cache import AsyncCache, DummyCache
from hassette.config.classes import AppManifest
from hassette.test_utils import make_mock_hassette


def _make_app_config(name: str = "kitchen") -> AppConfig:
    return AppConfig(instance_name=name)


def _make_manifest(tmp_path, *, app_key: str = "kitchen_lights", cache_key: str = "") -> AppManifest:
    return AppManifest(
        app_key=app_key,
        filename=f"{app_key}.py",
        class_name="KitchenLights",
        app_dir=tmp_path,
        full_path=tmp_path / f"{app_key}.py",
        cache_key=cache_key,
    )


class TestCacheKey:
    def test_default_cache_key_uses_app_key_and_index(self, tmp_path) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        app = App(hassette, app_config=_make_app_config(), index=3, app_key="kitchen_lights")

        assert app.cache_key == "kitchen_lights/3"

    def test_manifest_cache_key_overrides_default(self, tmp_path) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        manifest = _make_manifest(tmp_path, cache_key="custom")
        app = App(
            hassette,
            app_config=_make_app_config(),
            index=0,
            app_key="kitchen_lights",
            app_manifest=manifest,
        )

        assert app.cache_key == "custom"

    def test_manifest_without_cache_key_falls_back_to_default(self, tmp_path) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        manifest = _make_manifest(tmp_path, cache_key="")
        app = App(
            hassette,
            app_config=_make_app_config(),
            index=2,
            app_key="kitchen_lights",
            app_manifest=manifest,
        )

        assert app.cache_key == "kitchen_lights/2"


class TestInstanceScopedCacheDirectories:
    def test_different_indices_get_different_cache_directories(self, tmp_path) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        app0 = App(hassette, app_config=_make_app_config(), index=0, app_key="kitchen_lights")
        app1 = App(hassette, app_config=_make_app_config(), index=1, app_key="kitchen_lights")

        assert isinstance(app0.cache, AsyncCache)
        assert isinstance(app1.cache, AsyncCache)
        assert app0.cache.db_path != app1.cache.db_path
        assert app0.cache.db_path == tmp_path / "kitchen_lights" / "0" / "cache" / "cache.db"
        assert app1.cache.db_path == tmp_path / "kitchen_lights" / "1" / "cache" / "cache.db"


class TestDummyCacheInjection:
    def test_injected_dummy_cache_used_directly(self, tmp_path, dummy_cache: DummyCache) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)

        app = App(
            hassette,
            app_config=_make_app_config(),
            index=0,
            app_key="kitchen_lights",
            cache=dummy_cache,
        )

        assert app.cache is dummy_cache
        assert not isinstance(app.cache, AsyncCache)

    async def test_injected_dummy_cache_skips_initialize(self, tmp_path, dummy_cache: DummyCache) -> None:
        """before_initialize() only calls initialize() on a real AsyncCache -- DummyCache injection skips it."""
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        dummy_cache.initialize = AsyncMock(wraps=dummy_cache.initialize)  # pyright: ignore[reportAttributeAccessIssue]

        app = App(
            hassette,
            app_config=_make_app_config(),
            index=0,
            app_key="kitchen_lights",
            cache=dummy_cache,
        )

        await app.before_initialize()

        dummy_cache.initialize.assert_not_awaited()  # pyright: ignore[reportAttributeAccessIssue]


class TestCleanupClosesCache:
    async def test_cleanup_closes_cache(self, tmp_path, dummy_cache: DummyCache) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        dummy_cache.close = AsyncMock(wraps=dummy_cache.close)  # pyright: ignore[reportAttributeAccessIssue]

        app = App(
            hassette,
            app_config=_make_app_config(),
            index=0,
            app_key="kitchen_lights",
            cache=dummy_cache,
        )

        await app.cleanup()

        dummy_cache.close.assert_awaited_once()  # pyright: ignore[reportAttributeAccessIssue]

    async def test_cleanup_swallows_cache_close_exception(self, tmp_path, dummy_cache: DummyCache) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        dummy_cache.close = AsyncMock(side_effect=RuntimeError("cache close boom"))  # pyright: ignore[reportAttributeAccessIssue]

        app = App(
            hassette,
            app_config=_make_app_config(),
            index=0,
            app_key="kitchen_lights",
            cache=dummy_cache,
        )

        # Must not raise despite cache.close() blowing up.
        await app.cleanup()


class TestAppSyncBeforeInitializeCallsSuper:
    async def test_before_initialize_calls_super_and_initializes_cache(self, tmp_path) -> None:
        """AppSync.before_initialize must call super() first so cache init fires for sync apps."""
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        app = AppSync(hassette, app_config=_make_app_config(), index=0, app_key="kitchen_lights")
        assert isinstance(app.cache, AsyncCache)
        app.cache.initialize = AsyncMock(wraps=app.cache.initialize)  # pyright: ignore[reportAttributeAccessIssue]

        try:
            await app.before_initialize()
            app.cache.initialize.assert_awaited_once()  # pyright: ignore[reportAttributeAccessIssue]
        finally:
            # This test opens real aiosqlite connections via initialize() -- close them so no
            # unclosed-connection ResourceWarning leaks into an unrelated later test's teardown.
            await app.cache.close()


class TestDefaultCacheTtlResolution:
    def test_class_attribute_ttl_is_used(self, tmp_path) -> None:
        class TtlApp(App[AppConfig]):
            default_cache_ttl = 60

        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        app = TtlApp(hassette, app_config=_make_app_config(), index=0, app_key="ttl_app")

        assert isinstance(app.cache, AsyncCache)
        assert app.cache.default_ttl == 60

    def test_global_config_ttl_is_fallback(self, tmp_path) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False, default_cache_ttl=120)
        app = App(hassette, app_config=_make_app_config(), index=0, app_key="kitchen_lights")

        assert isinstance(app.cache, AsyncCache)
        assert app.cache.default_ttl == 120

    def test_no_ttl_set_anywhere_is_none(self, tmp_path) -> None:
        hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
        app = App(hassette, app_config=_make_app_config(), index=0, app_key="kitchen_lights")

        assert isinstance(app.cache, AsyncCache)
        assert app.cache.default_ttl is None
