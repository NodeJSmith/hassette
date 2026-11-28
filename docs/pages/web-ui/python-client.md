# Call the API from Python

The `hassette-client` package is a typed async client for Hassette's web API. It sends the requests, parses each response into a typed model, and raises a specific exception for each kind of failure. Use it from code that runs outside Hassette: a script on your laptop, a monitoring service, or a Home Assistant integration. Inside a Hassette app, `self.api` talks to Home Assistant; this client talks to Hassette itself.

The response models come from `hassette-wire`, the package that defines every request and response body in Hassette's API. Installing the client installs it too. Neither one depends on the `hassette` framework.

## Before you start

- A running Hassette server. Its web API listens on port `8126` unless `web_api.port` says otherwise.
- A web API token, unless the server trusts your machine as a proxy. [Web API token](../cli/configuration.md#web-api-token) covers where to find it.
- Python 3.11 or newer. The client is async: you call its methods with `await`, inside a function that `asyncio.run()` starts.

```bash
pip install hassette-client
```

## First request

```python
--8<-- "pages/web-ui/snippets/python_client_basic.py"
```

This prints the server's version and status, then one line per configured app:

```text
Hassette 0.55.0: ok
garage_door: running
porch_lights: stopped
```

The examples further down are fragments: they run inside `main()` and use its `client`.

`aiohttp.ClientSession` is the HTTP connection pool every request goes through. You open it and pass it in; the client never opens or closes a session itself. That way one session can serve several clients, and you decide how it verifies TLS. A Home Assistant integration passes the shared session from `async_get_clientsession(hass)` instead of opening its own.

## Connecting

`HassetteClient(session, base_url, *, token=None, request_timeout=10.0)` takes:

- `base_url`: the server's root URL. A path prefix is kept, so `https://example.com/hassette` works behind a reverse proxy that serves Hassette under a sub-path. Leave out any `user:password@`: `aiohttp` turns it into Basic authentication, and combined with a token every request raises `ValueError`.
- `token`: the web API token. With `None` (the default), requests carry no `Authorization` header. A server that lists your machine in `web_api.trusted_proxies` admits those requests anyway (see [Enabling and accessing the web UI](index.md#enabling-and-accessing)). Any string is sent as given, including an empty one (such as from an unset environment variable), which the server rejects with a 401 instead of falling back to that trust.
- `request_timeout`: seconds allowed for each request, including reading the whole response. It must be a positive, finite number.

`token` and `request_timeout` are keyword-only.

`action()` waits for the action to finish, and a reload or start includes the app's `on_initialize()`. For an app that takes longer than 10 seconds to start, create a second client with a longer `request_timeout` on the same session. A client holds no state of its own, so a second one costs nothing, and your other calls keep the short timeout that notices quickly when the server is down:

```python
--8<-- "pages/web-ui/snippets/python_client_timeout.py:slow"
```

The client never follows redirects. Hassette's API doesn't redirect, so a redirect means something in front of it did. Usually that's a forward-auth proxy, such as Authelia or Authentik, sending the request to its login page. The client raises `RedirectError`, and its `location` attribute holds the login page's URL.

## Methods

Each API route has one method. Each returns a `hassette-wire` model, or a list of them.

| Method | Route |
|---|---|
| `get_health()` | `GET /api/health` |
| `get_liveness()` | `GET /api/health/live` |
| `get_ready()` | `GET /api/health/ready` |
| `get_apps()` | `GET /api/apps` |
| `get_app(app_key)` | `GET /api/apps/{app_key}` |
| `action(app_key, action, *, instance=None)` | `POST /api/apps/{app_key}/{action}` or `POST /api/apps/{app_key}/instances/{instance}/{action}` |
| `reload_all(*, wait=False)` | `POST /api/apps/reload` |
| `set_debug_capture(app_key, enabled, *, instance=None)` | `PUT /api/apps/{app_key}/debug` or `PUT /api/apps/{app_key}/instances/{instance}/debug` |
| `press_button(app_key, instance, key)` | `POST /api/apps/{app_key}/instances/{instance}/buttons/{key}/press` |
| `set_switch(app_key, instance, key, on)` | `POST /api/apps/{app_key}/instances/{instance}/switches/{key}/turn_on` or `.../turn_off` |
| `get_app_config(app_key)` | `GET /api/apps/{app_key}/config` |
| `get_app_source(app_key)` | `GET /api/apps/{app_key}/source` |
| `get_app_grid()` | `GET /api/telemetry/app-grid` |
| `get_app_health(app_key)` | `GET /api/telemetry/app/{app_key}/health` |
| `get_app_listeners(app_key)` | `GET /api/telemetry/app/{app_key}/listeners` |
| `get_app_activity(app_key)` | `GET /api/telemetry/app/{app_key}/activity` |
| `get_app_jobs(app_key)` | `GET /api/telemetry/app/{app_key}/jobs` |
| `get_app_blocking_findings(app_key)` | `GET /api/telemetry/app/{app_key}/blocking` |
| `get_blocking_findings()` | `GET /api/telemetry/blocking/findings` |
| `get_unattributed_blocking()` | `GET /api/telemetry/blocking/unattributed` |
| `get_executions()` | `GET /api/telemetry/executions` |
| `get_listener_executions(listener_id)` | `GET /api/telemetry/listener/{listener_id}/executions` |
| `get_listener_misses(listener_id)` | `GET /api/telemetry/listener/{listener_id}/misses` |
| `get_job_executions(job_id)` | `GET /api/telemetry/job/{job_id}/executions` |
| `get_execution(execution_id)` | `GET /api/telemetry/execution/{execution_id}` |
| `get_telemetry_status()` | `GET /api/telemetry/status` |
| `get_listeners()` | `GET /api/bus/listeners` |
| `get_jobs()` | `GET /api/scheduler/jobs` |
| `trigger_job(job_id)` | `POST /api/scheduler/jobs/{job_id}/trigger` |
| `get_recent_logs()` | `GET /api/logs/recent` |
| `get_execution_detail(execution_id)` | `GET /api/executions/{execution_id}` |
| `set_log_level(logger, level)` | `PUT /api/logs/level` |
| `get_config()` | `GET /api/config` |

`app_key` is the app's key from `hassette.toml`. `action` is `"start"`, `"stop"` or `"reload"`. An app configured with several instances acts on all of them unless you pass `instance=` with one instance's name.

`reload_all()` reloads every app in place, as [Reload all](manage-apps.md#reload-all) does: it re-reads the config, re-imports every module loaded from your app directories, and restarts every running or failed app. It returns once every app has restarted, so give it a client with a longer `request_timeout`, as for a slow `action()`. It returns a `ReloadAllResponse` even when some apps failed; check `counts.failed` and `counts.refused`. Each entry in its `apps` carries an `action`: `reload`, `stop` for an app the config removed, or `start` for one it added. Before stopping anything it raises `ReloadConfigInvalidError` for an invalid config or `ReloadSyntaxError` for a syntax error, and `ActionInProgressError` when another reload or app action is running. Pass `wait=True` to wait for that one to finish instead. After a timeout the outcome is unknown, and calling it again reloads every app a second time.

`press_button()` and `set_switch()` send a command to a button or switch an app instance declares through `self.integration`, and return as soon as Hassette has published the command, not once the handler has run. Commands are accepted while the instance is running, and may be accepted briefly around its start and stop.

!!! warning "An accepted command can still be dropped"
    A successful `press_button()` or `set_switch()` means Hassette accepted and published the command, not that the app's handler ran. The handler's [execution mode](../core-concepts/bus/execution-modes.md) can still drop it. The default, `single`, skips a command that arrives while the previous one is still running, and a `queued` handler skips one when its queue is full. Each skip is recorded as a [near-miss](../core-concepts/bus/filtering.md#near-misses) (`hassette listener <id> --misses`). A `restart` handler runs the new command and cancels the earlier one, which shows up as a cancelled execution. The app chooses the mode with `mode=` when it [declares the button or switch](../core-concepts/apps/integration-entities.md). A command accepted while the instance or Hassette is shutting down can be lost with no record beyond a debug log line. None of this appears in the response, so check the handler's executions and near-misses to see what happened.

Each instance's declared entities, with their current state, are in `get_apps()`'s `AppInstance.entities`; every other method that returns instances leaves `entities` as `None`. The listing's `boot_id` and `entity_revision` say how fresh those entities are: `entity_revision` goes up with every change, and comparing two revisions only makes sense when both listings carry the same `boot_id`.

`POST /api/auth/session` has no method. It trades a token for a browser session cookie, which a client sending its token on every request doesn't need.

Filters such as `since`, `limit`, `instance_name` and `source_tier` are keyword-only and use the server's own parameter names. `since` is a Unix timestamp in seconds. A filter you leave as `None` isn't sent, so the server applies its own default. For `instance_name` that means every instance of the app, and a name no row carries answers empty rather than an error. For `get_recent_logs()` and `get_execution_detail()`, an unsent `author` leaves out Hassette's own lines below ERROR. On `get_recent_logs()` that holds even when `level` asks for `WARNING` or `INFO`. Pass `author="all"` to include them.

A method returning a list fails as a whole when any one item doesn't match its model, so a schema change shows up as an error rather than as missing rows.

## Handling errors

Every network or server failure raises a subclass of `HassetteClientError`. You never see a raw `aiohttp` or `pydantic` exception for one, so a single `except HassetteClientError` covers everything that can go wrong on the network or the server.

```python
--8<--
pages/web-ui/snippets/python_client_errors.py:imports
pages/web-ui/snippets/python_client_errors.py:handle
--8<--
```

This table lists every failure. The last two rows are bugs in the calling code rather than failures to recover from, and `except HassetteClientError` doesn't catch them:

| Exception | Raised for | Caught by `HassetteClientError` |
|---|---|---|
| `HassetteHTTPError` and its subclasses | An error status from Hassette or a proxy in front of it (table below) | Yes |
| `HassetteConnectionError` | No response at all: connection refused or reset, a DNS or TLS failure, or a malformed `base_url` | Yes |
| `HassetteTimeoutError` | No complete response within `request_timeout` | Yes |
| `ResponseValidationError` | A response that doesn't match its model: a renamed or removed field | Yes |
| `UnexpectedResponseError` | A success response that isn't JSON, such as a proxy's login page or the web UI's HTML. A subclass of `ResponseValidationError` | Yes |
| `UnsupportedServerVersionError` | A server older than this client supports. Only `check_server_version()` raises it | Yes |
| `ValueError` | A `request_timeout` that isn't a positive, finite number, raised by the constructor. A path argument that is empty, `.` or `..`, or contains `/`, raised before any request. Also a token containing a control character such as a newline, or a token combined with `user:password@` in `base_url` or a session created with `auth=`, raised by `aiohttp` on the first request | No |
| `RuntimeError` | A session that's already closed, raised by `aiohttp` itself. The client never closes the session you pass in | No |

A malformed `base_url` raises `HassetteConnectionError` rather than `ValueError`, so a Home Assistant config flow can show the same "cannot connect" error for a bad URL as for an unreachable one.

Each error response from Hassette carries a [problem `code`](api-errors.md), a machine-readable reason such as `app_not_found`. The client picks the exception from that code first, then from the HTTP status. In the table below, `A → B` means `B` is a subclass of `A`, so `except NotFoundError` also catches `AppNotFoundError`.

| Exception | Raised for |
|---|---|
| `RedirectError` | Any 3xx |
| `BadRequestError` → `InvalidAppKeyError` | 400 |
| `AuthenticationError` | 401: a missing or wrong token |
| `ForbiddenError` → `PathTraversalError` | 403 |
| `NotFoundError` → `AppNotFoundError`, `InstanceNotFoundError`, `SourceNotFoundError` | 404 |
| `ConflictError` → `BootstrapNotReleasedError`, `AppBlockedError`, `ActionInProgressError`, `NeedsRestartError`, `ReloadConfigInvalidError`, `ReloadSyntaxError`, `JobNotRegisteredError`, `InstanceNotRunningError`, `EntityNotDeclaredError` | 409 |
| `RequestValidationError` | 422: the server rejected a parameter |
| `ServerError` → `ActionFailedError`, `SourceUnavailableError` | 5xx |
| `GatewayError` | 502 or 504 from a proxy in front of Hassette |
| `ServiceUnavailableError` → `TelemetryUnavailableError` | 503 |

Most scripts only need a few of these: `HassetteConnectionError` and `HassetteTimeoutError` for an unreachable server, `AuthenticationError` for a bad token, and the `AppNotFoundError` family for a mistyped key.

Every HTTP error carries `status`, `code`, `detail` and `problem`, the whole parsed error body. The message includes Hassette's `detail`. When the body isn't a Hassette error, such as a proxy's HTML error page, `code`, `detail` and `problem` are `None`, and the message gives only the media type and size. The start of the body is on `body_excerpt`, kept out of the message so a proxy's page doesn't end up in your logs. `UnexpectedResponseError` has a `body_excerpt` too.

### Reading a "no such endpoint" error

A `NotFoundError` whose `code` is `not_found`, or an error whose `code` is `method_not_allowed`, means the server has no such endpoint at all. That's different from `app_not_found` and its siblings, which mean the endpoint exists but the thing you named doesn't. It has three usual causes:

- The server is older than the client and doesn't have the endpoint yet. `check_server_version()` catches this up front (see [Talking to an older or newer server](#talking-to-an-older-or-newer-server)).
- `base_url` has an extra path, such as `http://127.0.0.1:8126/api`, so every request goes to `/api/api/...`.
- An action name the server doesn't know. `action()` sends whatever you pass and leaves the check to the server, so a client can use an action a newer server added.

A `base_url` that points somewhere outside the API, such as the web UI's root path behind a proxy, gets the web UI's HTML instead, and raises `UnexpectedResponseError`.

### Retrying

The client never retries. The exception class tells you whether a retry can help:

- **Worth retrying with backoff:** `BootstrapNotReleasedError`, raised when apps can't start yet because Hassette hasn't connected to Home Assistant and loaded its initial state, and `ServiceUnavailableError` on a read. Any failure on a read (a `get_*` method) is also safe to retry.
- **Outcome unknown on a write:** `HassetteTimeoutError`, `HassetteConnectionError`, `GatewayError`, `UnexpectedResponseError`, `ServiceUnavailableError` (Hassette never answers a write with 503, so it came from a proxy), and any `ServerError` other than `ActionFailedError` (an unexpected server error can happen partway through). The server may or may not have received an `action()`, `trigger_job()`, `press_button()` or `set_switch()`, or may still be working on it: a proxy can give up with a 502 or 504 while Hassette is still reloading the app. A connection error can also be permanent, such as a TLS certificate problem or a bad URL.

`ActionFailedError` is different: the action ran and failed on at least one instance, and its `problem` says why. `problem.detail` names each instance that didn't succeed, and `problem.outcomes` lists what the action did to every instance. Before sending a write again after one of those, check whether it already happened. `start` and `stop` are safe to send again, since starting a running app or stopping a stopped one does nothing, unless an instance needs a restart. `reload`, `trigger_job()` and `press_button()` aren't: each one sent again reloads the app, runs the job, or presses the button a second time, so check the app's status or the handler's executions first.

`NeedsRestartError` from `action()` means an instance the action targeted needs a Hassette restart, so nothing was done to it. The app's other instances were still acted on, as `problem.outcomes` shows. Retrying won't help until Hassette restarts. It subclasses `ConflictError`, so code that retries every `ConflictError` should catch `NeedsRestartError` first. See [Instances that need a restart](../operating/index.md#instances-that-need-a-restart).

`ActionInProgressError` from `action()` means nothing ran: an earlier action on the same app is still running, perhaps one whose request already timed out on your side. Hassette rejects the new action rather than queuing it behind the first, so check the app's status once the first one finishes instead of retrying straight away.

A `ResponseValidationError` on a write whose `status` is 2xx usually means Hassette already carried out the request and only its answer didn't parse, so it shouldn't be sent blindly again. The client can't prove the 2xx came from Hassette, though: a proxy in front of it can answer 2xx too. Check the app's status or the job's executions, as above, before deciding. An `UnexpectedResponseError` is the clear case of an answer that didn't come from Hassette.

This retries a `start` with exponential backoff and jitter, so many clients recovering at once don't all hit the server in the same second:

```python
--8<--
pages/web-ui/snippets/python_client_errors.py:imports
pages/web-ui/snippets/python_client_errors.py:retry
--8<--
```

Inside Home Assistant, don't retry in the integration at all. Raise `ConfigEntryNotReady` during setup and let Home Assistant retry it, and let the coordinator's next poll be the retry for reads.

## Health probes

`get_ready()` and `get_telemetry_status()` return their result even when the server answers 503, because for those two endpoints the 503 is the answer. Check `ready` on the `get_ready()` result, or `degraded` on the `get_telemetry_status()` result, rather than catching an error. A 503 whose body isn't that result, such as a proxy's page reporting that Hassette is down, raises `ServiceUnavailableError` from these two as well. Every other method raises on any 503. [Configure Health Checks](health-endpoints.md) explains what each endpoint reports.

## Streaming entity state

`get_apps()` returns a snapshot. `listen()` opens Hassette's WebSocket stream, which pushes a declared sensor or switch the moment its app sets it:

```python
await client.listen(on_message, types=[EntityStateChangedWsMessage], on_connected=refresh)
```

`listen()` connects with the client's session and token and waits until the stream is receiving. It awaits `on_connected()`, then awaits `on_message` for each message whose type is in `types`, one at a time, in the order the server sent them. Other types are skipped without being parsed, including types a newer Hassette adds, so a change to a message the client doesn't listen for never breaks the stream. The message classes come from `hassette_wire`. `AppStatusChangedWsMessage` is the other one an integration usually wants, for an instance starting or stopping; [App status](#app-status) covers how to apply it.

`listen()` never returns and never reconnects, so run it as a background task. When the stream ends, it raises `HassetteConnectionError`: the server closed it, the connection stopped answering the heartbeat sent every 30 seconds, or it was reset. Reconnecting is the caller's decision. Cancel the task to close the stream.

A bad token raises `AuthenticationError`, as on any other method. A Hassette server older than the release that added `listen()` rejects the token with a bare 403 instead, which raises `ForbiddenError`, and it sends no entity messages at all, so the poll described below matters there even more.

Each `EntityStateChangedWsMessage` carries one entity's full state, in the same shape as an entry of `AppInstance.entities`, plus the `boot_id` and `entity_revision` it was committed at. Apply messages by these rules:

- **Same boot, newer revision.** Apply a pushed entity only when its `boot_id` equals the `boot_id` of the listing last applied and its `entity_revision` is newer than the last one applied. Ignore a message from any other boot rather than treating it as a restart. If Hassette restarts while a listing fetch is in flight, the old socket can still deliver deltas from the old boot after the new boot's listing is applied, and the reconnect brings that listing anyway. Messages reach each client in revision order, but a fetched listing can already include a change whose message is still on its way.
- **Revisions skip.** `entity_revision` counts every change across all of Hassette's instances, and adding or removing entities when an instance starts moves it too. A gap between two messages doesn't mean one was missed.
- **Only a listing repairs a lost message.** Hassette drops messages for a client that falls too far behind, and nothing in the stream signals it. Keep fetching `get_apps()` on a timer, and refetch it in `on_connected()` on every connect, including the first: changes made before the stream opened appear only in that listing.
- **Entities appear and disappear through the listing.** The stream reports new state only for entities that already exist. A new or removed entity shows up in the next `get_apps()`.

### App status

Each `AppStatusChangedWsMessage` reports one instance's new `status`, plus `app_status`, the app's overall status after the change, and the `status_revision` it was written at. Every `AppSummary` that `get_apps()`, `get_app()` and the app grid return carries the `status_revision` it was read at. The two numbers come from one counter, so a message and a snapshot compare directly:

- **Strictly newer wins.** Apply a message to an app only when its `status_revision` is greater than the `status_revision` of the `AppSummary` you last applied for that app. On a tie, keep the summary. Write `>`, not `>=`.
- **Refetch on `AppsChangedWsMessage`.** Disabling or blocking an app, a config change, and registering an instance change status without sending `AppStatusChangedWsMessage`. They send `AppsChangedWsMessage` once the load pass ends, so listen for it and refetch.
- **No boot check needed.** `status_revision` is seeded from the server's clock, so it keeps increasing across restarts and a summary from before a restart doesn't outrank a message from after it. `boot_id` still tells you a restart happened, if you keep other state per server process.
- **Revisions skip.** Writes that send no message move `status_revision` too, so a gap doesn't mean a message was lost. As with entity messages, a dropped message is repaired only by the next fetch.

!!! warning "A clock that steps backwards hides status messages"
    If the server's clock steps backwards across a restart (a device with no battery-backed clock, before it syncs time), the summaries you kept from before the restart outrank every new `AppStatusChangedWsMessage`, and those messages are ignored. The next `get_apps()` replaces the kept summaries and fixes it, which is one more reason to keep fetching on a timer.

For availability, read each instance's `status`, not the app-level `app_status`: an app with several instances reads `starting` or `stopping` while any one of them is restarting.

## Talking to an older or newer server

`hassette-client` is released alongside Hassette, but the two often upgrade at different times. A freshly installed client may meet last month's server, or a Home Assistant integration may update its client before Hassette. Three rules cover the gap:

- `check_server_version()`, called once after connecting, makes an older server fail clearly instead of halfway through.
- `UnknownValue` needs handling wherever code uses `match` on a status.
- The client tolerates everything else a newer server changes.

### A newer server

Some fields hold one of a fixed set of values, such as an app's `status` (`running`, `stopped`, and so on). Most are *open*: a newer server may add a value this client has never heard of. The client parses that value as a `hassette_wire.UnknownValue` instead of failing. `UnknownValue` is a `str` subclass holding exactly what the server sent, so printing or comparing it still works. A few fields are *closed*, such as `source_tier`, a log line's `author`, and log levels. Their values are fixed, and an unknown one raises `ResponseValidationError`.

`app.status` from [First request](#first-request) is an open field. This loop, inside `main()`, handles a status the client doesn't know:

```python
--8<--
pages/web-ui/snippets/python_client_skew.py:unknown-imports
pages/web-ui/snippets/python_client_skew.py:unknown
--8<--
```

`case UnknownValue() as unknown:` matches only unrecognized values; `case status:` takes everything else. Against a server newer than the client, it prints a line like `porch_lights: 'paused' is newer than this client`.

The client also ignores response fields it doesn't know: they don't appear on the returned model.

### An older server

Against an older server, a new method fails later with a `not_found` error. A new filter, such as `since=`, is silently ignored by the server: the call returns unfiltered data with no error. `check_server_version()` catches both up front. Call it once, when setting up a connection:

```python
--8<--
pages/web-ui/snippets/python_client_skew.py:check-imports
pages/web-ui/snippets/python_client_skew.py:check
--8<--
```

Against a server that's too old, it prints a message like:

```text
hassette server 0.40.0 reports no API schema, older than 7, the oldest this hassette-client supports: upgrade the hassette server, or install an older hassette-client
```

The message names the two fixes: upgrade Hassette, or pin `hassette-client` to the release matching the server.

The check compares API schema numbers, not Hassette's release version. Each server reports its API schema, an integer, as `api_schema_version` in `get_health()`. The number rises when the API gains something this client needs. A server released before the schema existed reports none, which counts as `0`. `MIN_API_SCHEMA_VERSION`, exported from `hassette_client`, is the oldest schema this client release works with. The check is exact for released servers. A server running from a git checkout reports the schema of the most recent bump, which can predate API added since, because the schema is bumped once per release.

Nothing calls `check_server_version()` automatically, so `get_health()` and the rest still work against an older server, for example to show its status.

### What each side tolerates

| Server change | Client older than the server | Client newer than the server (after `check_server_version()` passes) |
|---|---|---|
| New response field | Ignored | The client never requires a field this server lacks |
| New value in an open field | Parsed as `UnknownValue` | Doesn't arise: the client knows every value the server sends |
| New value in a closed field | `ResponseValidationError`; upgrade the client. Hassette releases this as a breaking change | Doesn't arise |
| New problem code | Raises the exception for its HTTP status; `exc.problem.code` is an `UnknownValue` | Doesn't arise |
| New method or action | No method for it | Doesn't arise: the check guarantees the server has it |
| New query parameter | Not sent; the server uses its default | Doesn't arise: the check guarantees the server has it |
| New request body field | Not sent; the server uses its default | Not checked: the server may ignore it or answer 422 |
| Renamed, removed or retyped field | `ResponseValidationError`. Hassette releases this as a breaking change | `ResponseValidationError` |

??? note "How Hassette tests these guarantees"
    Every code change to Hassette runs two checks. A wire-compatibility check compares the API with the latest release in both directions. It fails on a new required response field or a removed field unless the change is released as breaking. A client floor check runs the client against the oldest release reporting `MIN_API_SCHEMA_VERSION`. Every method and query parameter the client uses must exist there, and every response field the client requires must be present with the same type, or the change has to raise the API schema. Neither check covers a new value in a closed field or a request body field, and neither proves an endpoint means the same thing on both releases.

## Logging

The client logs under the `hassette_client` logger, at DEBUG only: each request's method, path, query parameter names and timeout; each response's status, media type, size and duration; each exception as it's raised, with the underlying `aiohttp` error type; and each judgment call, such as parsing a body that had no `Content-Type`. It never logs the token, cookies, body content, or a username or password in `base_url`. Nothing is logged above DEBUG, since every problem it notices is also raised, and your code decides how serious it is.

To see it in Home Assistant, add the logger to `configuration.yaml`:

```yaml
logger:
  logs:
    hassette_client: debug
```

## Parsing saved responses

`parse_response(response_type, payload)`, also exported from `hassette_client`, parses a JSON body exactly the way the client's methods do. It checks saved responses against a client release without a running server.

This example parses a `get_health()` response saved as `health.json`, then prints the server's status:

```python
--8<-- "pages/web-ui/snippets/python_client_parse.py"
```

`payload` is the raw JSON as `str` or `bytes`, not a decoded dict. Pass the model the matching method returns, or a type built from one, such as `list[Execution]`.

## Next steps

- [API Error Responses](api-errors.md) lists every problem code and the endpoints that return it.
- [Configure Health Checks](health-endpoints.md) covers what the health endpoints report.
- [CLI Configuration](../cli/configuration.md) covers the web API token and reverse-proxy setups.
