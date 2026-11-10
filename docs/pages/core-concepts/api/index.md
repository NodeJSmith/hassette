# API

`self.api` sends commands to Home Assistant and retrieves data from it. It wraps the REST and WebSocket APIs with automatic authentication, retries, and type conversion. Every [`App`](../apps/index.md) instance has one.

## Quick Example

The two most common operations are reading state and calling a service.

```python
--8<-- "pages/core-concepts/api/snippets/api_overview_usage.py"
```

`get_state()` fetches the entity from Home Assistant over the network. It returns a typed state object with `.value` and `.attributes` (domain-specific fields). `.value` holds the state converted to a domain-specific type, such as `True`/`False` for lights and switches. [States](../states/index.md) covers the conversion rules. `call_service()` sends a service call via WebSocket.

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

[Api][hassette.api.api.Api] raises typed exceptions that say whether the command reached Home Assistant.

- [`CommandNotSentError`][hassette.exceptions.CommandNotSentError] if the command never reached Home Assistant, because the WebSocket was disconnected or a REST request could not connect. The command did not apply.
- [`OutcomeUnknownError`][hassette.exceptions.OutcomeUnknownError] if the command was sent but no answer arrived ([`ResponseTimeoutError`][hassette.exceptions.ResponseTimeoutError], [`ResponseLostError`][hassette.exceptions.ResponseLostError]). The command may or may not have applied.
- [`CommandRejectedError`][hassette.exceptions.CommandRejectedError] if Home Assistant answered a WebSocket command with an error. Its `.code` holds HA's error code.
- [`EntityNotFoundError`][hassette.exceptions.EntityNotFoundError] if a REST request answered 404, such as for an entity that does not exist.
- [`HttpRequestError`][hassette.exceptions.HttpRequestError] for any other REST error status. Its `.status` holds the code, such as 401 for an invalid or expired token.

Hassette's WebSocket connection also rejects an invalid token when it authenticates. That raises [`InvalidAuthError`][hassette.exceptions.InvalidAuthError] during startup or reconnect, never from an `Api` call.

REST reads (`get_state`, `get_history`) retry failed connects, timeouts, dropped connections, 5xx responses, 408, and 429, with backoff between attempts. Any other 4xx response raises on the first attempt, because re-sending the request gets the same answer. Every other REST call (`set_state`, `delete_entity`, and `render_template`, which is sent as a POST) retries only a failed connect. Anything later may already have applied, so the request is sent once. Catching [`HassetteError`][hassette.exceptions.HassetteError] handles every failure in one place.

??? note "Synchronous usage (AppSync only)"
    `self.api.sync` exposes an [`ApiSyncFacade`][hassette.api.sync.ApiSyncFacade] that mirrors all API methods as blocking calls. It exists for [`AppSync`][hassette.app.app.AppSync] lifecycle hooks, which run outside the async event loop. The [Apps](../apps/index.md) page covers the `AppSync` pattern.

## Next Steps

- [API Methods](methods.md): all `self.api` methods organized by task: reading state, calling services, history, templates, and more.
- [Managing Helpers](managing-helpers.md): creating and managing input helpers (booleans, counters, timers, and more).
