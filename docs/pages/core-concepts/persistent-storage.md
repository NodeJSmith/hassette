# Persistent Storage

Hassette provides a built-in disk-based cache that allows you to persist data between app restarts. This cache is available on all Resource instances (Apps, Services, etc.) via the `self.cache` property.

## Overview

The cache is useful when you need to:

- **Rate-limit notifications** - Track when you last sent a notification to avoid spam
- **Remember state between restarts** - Track counters, timestamps, or app state that should survive restarts
- **Cache expensive operations** - Store API responses to avoid rate limits or reduce external calls
- **Store historical data** - Keep logs or aggregated data that doesn't belong in Home Assistant state

The cache uses the [`diskcache`](https://grantjenks.com/docs/diskcache/) library under the hood, providing a simple dictionary-like interface backed by persistent storage.

## Basic Usage

The cache works like a Python dictionary:

```python
from hassette import App, AppConfig

class MyApp(App[AppConfig]):
    async def on_initialize(self):
        # Store data
        self.cache["last_run"] = self.now()
        self.cache["user_preferences"] = {"theme": "dark", "notifications": True}

        # Retrieve data
        if "last_run" in self.cache:
            last_run = self.cache["last_run"]
            self.logger.info(f"Last run: {last_run}")

        # Get with default value
        count = self.cache.get("run_count", 0)
        self.cache["run_count"] = count + 1

        # Delete data
        del self.cache["old_key"]
```

## How It Works

### Storage Location

Cache data is stored on disk in your configured data directory:

```
{data_dir}/{ClassName}/cache/
```

For example, if your app is named `WeatherApp` and your `data_dir` is `/home/user/.hassette`, the cache will be stored at:

```
/home/user/.hassette/WeatherApp/cache/
```

### Shared Cache

All instances of the same resource class share the same cache directory. If you have multiple instances of `MyApp`, they all read from and write to the same cache.

!!! warning "Instance Sharing"
    Because cache is shared across instances of the same class, be careful with key naming if you have multiple instances. Consider including instance-specific identifiers in your cache keys.

### Lazy Initialization

The cache is created lazily when first accessed. If you never use `self.cache`, no directory is created.

### Automatic Cleanup

The cache is automatically cleaned up during app shutdown, ensuring data is properly flushed to disk.

## Configuration

You can configure the maximum cache size in your [global configuration](configuration/global.md):

```toml
# hassette.toml
[hassette]
default_cache_size = 104857600  # 100 MiB (default)
data_dir = "/path/to/data"
```

The `default_cache_size` setting controls the maximum size in bytes for each cache. When the limit is reached, the least recently used items are automatically evicted.

## Examples

### Caching API Responses

Avoid hitting rate limits by caching external API responses:

```python
from hassette import App, AppConfig

class WeatherApp(App[AppConfig]):
    async def on_initialize(self):
        self.scheduler.run_every(self.update_weather, 60)

    async def update_weather(self):
        weather = await self.get_weather("New York")
        await self.api.set_state(
            "sensor.weather_forecast",
            weather["temperature"]
        )

    async def get_weather(self, location: str) -> dict:
        cache_key = f"weather:{location}"

        # Check cache first
        if cache_key in self.cache:
            cached_time, data = self.cache[cache_key]
            # Check if cache is still fresh (less than 30 minutes old)
            if cached_time > self.now().subtract(minutes=30):
                self.logger.info(f"Using cached weather for {location}")
                return data

        # Fetch fresh data from API
        self.logger.info(f"Fetching fresh weather for {location}")
        data = await self.fetch_weather_api(location)
        self.cache[cache_key] = (self.now(), data)
        return data

    async def fetch_weather_api(self, location: str) -> dict:
        # Your API call here
        pass
```

### Rate-Limiting Notifications

Prevent notification spam by tracking when you last sent a notification:

```python
from hassette import App, AppConfig
from hassette.event_handling import P

class WaterLeakAlertApp(App[AppConfig]):
    async def on_initialize(self):
        self.bus.on_state_change(
            "binary_sensor.water_leak",
            handler=self.on_leak_detected,
            P.to_state.is_on
        )

    async def on_leak_detected(self, event):
        """Send notification, but not more than once every 4 hours."""
        cache_key = "last_leak_notification"

        # Check when we last sent a notification
        last_sent = self.cache.get(cache_key)

        if last_sent is not None:
            # Check if last notification was sent less than 4 hours ago
            if last_sent > self.now().subtract(hours=4):
                time_since_last = self.now() - last_sent
                self.logger.info(
                    f"Skipping notification - last sent {time_since_last} ago"
                )
                return

        # Send the notification
        await self.api.call_service(
            "notify",
            "mobile_app",
            message="Water leak detected!",
            title="⚠️ Alert"
        )

        # Update cache with current time
        self.cache[cache_key] = self.now()
        self.logger.info("Leak notification sent")
```

You can also track notifications per entity:

```python
class MultiSensorAlertApp(App[AppConfig]):
    async def on_initialize(self):
        self.bus.on_state_change(
            "binary_sensor.*",
            handler=self.on_sensor_alert,
            P.to_state.is_on
        )

    async def on_sensor_alert(self, event):
        """Rate-limit notifications per sensor."""
        entity_id = event.data.entity_id
        cache_key = f"last_notification:{entity_id}"

        last_sent = self.cache.get(cache_key)
        # Skip if we sent a notification less than 2 hours ago
        if last_sent and last_sent > self.now().subtract(hours=2):
            return

        await self.api.call_service(
            "notify",
            "mobile_app",
            message=f"Alert from {entity_id}",
        )

        self.cache[cache_key] = self.now()
```

### Persistent Counters

Track events across restarts:

```python
from hassette import App, AppConfig
from hassette.event_handling import P

class MotionCounterApp(App[AppConfig]):
    async def on_initialize(self):
        # Initialize counter from cache or start at 0
        self.motion_count = self.cache.get("motion_count", 0)
        self.logger.info(f"Motion count restored: {self.motion_count}")

        self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_motion,
            P.to_state.is_on
        )

    async def on_motion(self, event):
        self.motion_count += 1
        self.cache["motion_count"] = self.motion_count
        self.logger.info(f"Total motion events: {self.motion_count}")
```

### Storing Complex Data

The cache can store any Python object that can be pickled:

```python
from dataclasses import dataclass
from hassette import App, AppConfig
from whenever import ZonedDateTime

@dataclass
class EnergyStats:
    total_kwh: float
    peak_usage: float
    last_updated: ZonedDateTime

class EnergyTrackerApp(App[AppConfig]):
    async def on_initialize(self):
        # Load previous stats or create new ones
        self.stats = self.cache.get(
            "energy_stats",
            EnergyStats(0.0, 0.0, self.now())
        )

        self.scheduler.run_hourly(self.update_stats)

    async def update_stats(self):
        current_usage = await self.get_current_usage()

        self.stats.total_kwh += current_usage
        self.stats.peak_usage = max(self.stats.peak_usage, current_usage)
        self.stats.last_updated = self.now()

        # Persist to cache
        self.cache["energy_stats"] = self.stats
        self.logger.info(f"Updated stats: {self.stats}")

    async def get_current_usage(self) -> float:
        state = await self.api.get_state("sensor.power_usage")
        return float(state.state)
```

### Expiring Cache Entries

Implement time-based expiration:

```python
from hassette import App, AppConfig

class DataCacheApp(App[AppConfig]):
    async def get_cached_data(self, key: str, ttl_minutes: int = 60):
        """Get data from cache if not expired."""
        cache_key = f"data:{key}"

        if cache_key in self.cache:
            timestamp, value = self.cache[cache_key]

            # Check if cache entry is still fresh
            if timestamp > self.now().subtract(minutes=ttl_minutes):
                return value

        # Data expired or not found
        return None

    async def set_cached_data(self, key: str, value):
        """Store data with timestamp."""
        cache_key = f"data:{key}"
        self.cache[cache_key] = (self.now(), value)
```

## Best Practices

### What to Cache

✅ **Good uses:**

- Notification timestamps for rate-limiting
- API responses with rate limits
- Computed values that are expensive to calculate
- Historical data aggregation
- User preferences or settings
- Counters and statistics across restarts

❌ **Avoid caching:**

- Real-time Home Assistant state (use [StateManager](states/index.md) instead)
- Large binary files (consider external storage)
- Temporary session data (use instance variables)

### Data Types

The cache can store any Python object that is pickle-able:

- Primitives: `str`, `int`, `float`, `bool`, `None`
- Collections: `list`, `dict`, `tuple`, `set`
- Dates/times: `ZonedDateTime`, `PlainDateTime`, `Instant`, `TimeDelta` (from `whenever` library)
- Home Assistant objects: State instances, event instances, and other Hassette models
- Custom classes (if they support pickling)

!!! tip "Using `self.now()`"
    `self.now()` returns a `ZonedDateTime` in your system timezone. This is the recommended type for storing timestamps in the cache.

### Performance Considerations

- Cache access is fast but not instant (disk I/O involved)
- For frequently accessed data within a single run, consider caching in memory first
- The cache is thread-safe and can be accessed from multiple async tasks

```python
class OptimizedApp(App[AppConfig]):
    async def on_initialize(self):
        # Load from disk cache once
        self.config_data = self.cache.get("config", {})

    async def on_ready(self):
        # Use in-memory copy for frequent access
        setting = self.config_data.get("some_setting")

    async def on_shutdown(self):
        # Persist changes back to disk cache
        self.cache["config"] = self.config_data
```

### Cache vs StateManager

Choose the right storage mechanism:

| Use Case | Tool | Why |
|----------|------|-----|
| Current sensor values | [StateManager](states/index.md) | Real-time HA state |
| Historical data | Cache | Persists across restarts |
| Computed aggregates | Cache | Not part of HA state |
| External API data | Cache | Reduce external calls |
| Temporary flags | Instance variables | No persistence needed |

## Lifecycle

The cache is automatically managed through the resource lifecycle:

1. **Initialization** - Cache directory created on first access
2. **Runtime** - Data reads/writes happen transparently
3. **Shutdown** - Cache is closed and flushed to disk

You don't need to manually open or close the cache.

## Troubleshooting

### Cache Not Persisting

If data isn't surviving restarts, check:

- Are you accessing `self.cache` correctly (not creating a local variable)?
- Is the app completing initialization without errors?
- Does the cache directory have write permissions?
- Is the data type pickle-able?

### Cache Size Issues

If you're hitting size limits:

- Increase `default_cache_size` in [global configuration](configuration/global.md)
- Implement expiration logic to remove old entries
- Consider storing large data externally and caching only references

### Debugging

Enable debug logging to see cache operations:

```toml
# hassette.toml
[logging]
level = "DEBUG"
```

Check the cache directory to verify data is being written:

```bash
ls -lah ~/.hassette/MyApp/cache/
```

## Related Resources

- [Global Configuration](configuration/global.md) - Configure cache size and data directory
- [Apps Overview](apps/index.md) - Learn about app lifecycle
- [Core Concepts](index.md) - Understanding Hassette's architecture
- [diskcache documentation](https://grantjenks.com/docs/diskcache/) - Full cache library reference
