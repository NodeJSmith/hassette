# API

`self.api` sends commands to Home Assistant and retrieves data from it. It wraps the REST and WebSocket APIs with automatic authentication, retries, and type conversion. Every [`App`](../apps/index.md) instance has one.

## Quick Example

The two most common operations are reading state and calling a service.

```python
--8<-- "pages/core-concepts/api/snippets/api_overview_usage.py"
```

`get_state()` fetches the entity from Home Assistant over the network. It returns a typed state object with `.value` (the state string) and `.attributes` (domain-specific fields). `call_service()` sends a service call via WebSocket.

## API vs StateManager

[`self.states`](../states/index.md) covers most state-reading needs. It returns typed state objects from a local cache, with no network call and no `await`.

| | `self.states` | `self.api` |
|---|---|---|
| Access pattern | Synchronous | `async` / `await` |
| Data source | Local cache, updated from HA events | Direct from Home Assistant |
| Latency | Instant | Network round-trip |
| Best for | Reading state in handlers | Writes, fresh data, helpers |

`self.states` is faster and simpler for reads. `self.api` is the right choice when fresh-from-HA data is needed, or for any write operation: service calls, `set_state()`, and [managing HA helpers](managing-helpers.md) (`input_boolean`, `counter`, `timer`, etc.).

## Error Handling

[Api][hassette.api.api.Api] raises typed exceptions for common failures.

- [`EntityNotFoundError`][hassette.exceptions.EntityNotFoundError] if the entity does not exist in Home Assistant.
- [`InvalidAuthError`][hassette.exceptions.InvalidAuthError] if authentication failed (invalid or expired token).
- [`HassetteError`][hassette.exceptions.HassetteError] for any other upstream error from Home Assistant.

Network errors are retried automatically. Catching [`HassetteError`][hassette.exceptions.HassetteError] handles all API failures in one place.

??? note "Synchronous usage (AppSync only)"
    `self.api.sync` exposes an [`ApiSyncFacade`][hassette.api.sync.ApiSyncFacade] that mirrors all API methods as blocking calls. It exists for [`AppSync`][hassette.app.app.AppSync] lifecycle hooks, which run outside the async event loop. The [Apps](../apps/index.md) page covers the `AppSync` pattern.

## Next Steps

- [API Methods](methods.md): all `self.api` methods organized by task: reading state, calling services, history, templates, and more.
- [Managing Helpers](managing-helpers.md): creating and managing input helpers (booleans, counters, timers, and more).
