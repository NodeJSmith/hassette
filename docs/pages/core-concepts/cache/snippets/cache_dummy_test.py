from hassette.cache import DummyCache


async def test_cache_round_trip(dummy_cache: DummyCache):
    await dummy_cache.set("run_count", 3)

    assert await dummy_cache.get("run_count") == 3
    assert await dummy_cache.get("missing", default=0) == 0
