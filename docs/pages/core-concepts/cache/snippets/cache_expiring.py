from hassette import App, AppConfig


class DataCacheApp(App[AppConfig]):
    async def get_cached_data(self, key: str, ttl_minutes: int = 60):
        """Get data from cache if not expired, or None if expired or absent."""
        cache_key = f"data:{key}"

        entry = await self.cache.get(cache_key)
        if entry is not None:
            timestamp, value = entry

            # Return cached data if still within TTL
            if timestamp > self.now().subtract(minutes=ttl_minutes):
                return value

        # Data expired or not found
        return None

    async def set_cached_data(self, key: str, value) -> None:
        """Store data alongside a timestamp for TTL tracking."""
        cache_key = f"data:{key}"
        await self.cache.set(cache_key, (self.now(), value))
