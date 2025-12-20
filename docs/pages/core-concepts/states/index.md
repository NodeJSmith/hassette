# States Overview

Hassette maintains a local, real-time cache of all Home Assistant states. This is available as `self.states` in your apps.

## Why use `self.states`?

| Feature | `self.states` | `self.api.get_state()` |
| ------- | ------------- | ---------------------- |
| **Speed** | Instant (Local Memory) | Slow (Network Request) |
| **IO** | Synchronous | Asynchronous (await) |
| **Freshness** | Real-time (Event driven) | Real-time (On demand) |

**Recommendation**: Use `self.states` for reading data (conditions, logic). Use `self.api` only when you need to write data (services) or explicitly confirm state with the server.

## Architecture

The cache is populated when Hassette starts and stays synchronized by listening to the global event stream.

## Next Steps

- **[Usage Guide](usage.md)**: Learn how to query, filter, and iterate over states efficiently.
