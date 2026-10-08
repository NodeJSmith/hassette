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

- `base_url`: the server's root URL. A path prefix is kept, so `https://example.com/hassette` works behind a reverse proxy that serves Hassette under a sub-path. Leave out any `user:password@`: `aiohttp` turns it into Basic authentication, which replaces the token.
- `token`: the web API token. Without one, requests carry no `Authorization` header. A server that lists your machine in `web_api.trusted_proxies` admits those requests anyway (see [Enabling and accessing the web UI](index.md#enabling-and-accessing)).
- `request_timeout`: seconds allowed for each request, including reading the whole response.

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
| `action(app_key, action, instance=None)` | `POST /api/apps/{app_key}/{action}` or `POST /api/apps/{app_key}/instances/{instance}/{action}` |
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
| `get_job_executions(job_id)` | `GET /api/telemetry/job/{job_id}/executions` |
| `get_execution(execution_id)` | `GET /api/telemetry/execution/{execution_id}` |
| `get_telemetry_status()` | `GET /api/telemetry/status` |
| `get_listeners()` | `GET /api/bus/listeners` |
| `get_jobs()` | `GET /api/scheduler/jobs` |
| `trigger_job(job_id)` | `POST /api/scheduler/jobs/{job_id}/trigger` |
| `get_recent_logs()` | `GET /api/logs/recent` |
| `get_execution_logs(execution_id)` | `GET /api/executions/{execution_id}` |
| `set_log_level(logger, level)` | `PUT /api/logs/level` |
| `get_config()` | `GET /api/config` |

`app_key` is the app's key from `hassette.toml`. `action` is `"start"`, `"stop"` or `"reload"`. An app configured with several instances acts on all of them unless you pass `instance=` with one instance's index.

`POST /api/auth/session` has no method. It trades a token for a browser session cookie, which a client sending its token on every request doesn't need.

Filters such as `since`, `limit`, `instance_index` and `source_tier` are keyword-only and use the server's own parameter names. `since` is a Unix timestamp in seconds. A filter you leave as `None` isn't sent, so the server applies its own default.

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
| `ValueError` | A path argument that is `.` or `..` or contains `/`, raised before any request. Also a token containing a control character such as a newline, raised by `aiohttp` on the first request | No |
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
| `ConflictError` → `BootstrapNotReleasedError`, `AppBlockedError`, `JobNotRegisteredError` | 409 |
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

- **Worth retrying with backoff:** `ServiceUnavailableError` and `BootstrapNotReleasedError`, raised when apps can't start yet because Hassette hasn't connected to Home Assistant and loaded its initial state. Any failure on a read (a `get_*` method) is also safe to retry.
- **Outcome unknown on a write:** `HassetteTimeoutError`, `HassetteConnectionError`, `GatewayError` and `UnexpectedResponseError`. The server may or may not have received an `action()` or `trigger_job()`, or may still be working on it: a proxy can give up with a 502 or 504 while Hassette is still reloading the app. A connection error can also be permanent, such as a TLS certificate problem or a bad URL.

Before sending a write again after one of those, check whether it already happened. `start` and `stop` are safe to send again, since starting a running app or stopping a stopped one does nothing. `reload` and `trigger_job()` aren't: each one sent again reloads the app or runs the job a second time, so check the app's status or the job's executions first.

A `ResponseValidationError` on a write whose `status` is 2xx is different: the server already carried out the request, and only its answer didn't parse. Don't send it again. `UnexpectedResponseError` is the exception to that rule, because its answer may not have come from Hassette at all.

This retries a `start` with exponential backoff and jitter, so many clients recovering at once don't all hit the server in the same second:

```python
--8<--
pages/web-ui/snippets/python_client_errors.py:imports
pages/web-ui/snippets/python_client_errors.py:retry
--8<--
```

Inside Home Assistant, don't retry in the integration at all. Raise `ConfigEntryNotReady` during setup and let Home Assistant retry it, and let the coordinator's next poll be the retry for reads.

## Health probes

`get_ready()` and `get_telemetry_status()` return their result even when the server answers 503, because for those two endpoints the 503 is the answer. Check `ready` on the `get_ready()` result, or `degraded` on the `get_telemetry_status()` result, rather than catching an error. A 503 that isn't JSON, such as a proxy reporting that Hassette is down, raises `ServiceUnavailableError` from these two as well. Every other method raises on any 503. [Configure Health Checks](health-endpoints.md) explains what each endpoint reports.

## Talking to an older or newer server

`hassette-client` is released alongside Hassette, but the two are often upgraded at different times. A Home Assistant integration usually updates first, so the client is often the newer side.

### A newer server

A newer server can send a status or other named value that this client doesn't know. Instead of failing, the client parses that value as a `hassette_wire.UnknownValue`, a string holding exactly what the server sent. The status fields in the example above are this kind of field:

```python
--8<--
pages/web-ui/snippets/python_client_skew.py:imports
pages/web-ui/snippets/python_client_skew.py:unknown
--8<--
```

The client also ignores response fields it doesn't know.

### An older server

`MIN_SERVER_VERSION` is the oldest Hassette server this client release works with. `check_server_version()` takes a `get_health()` result and raises `UnsupportedServerVersionError` when the server is older. No method calls it for you, so `get_health()` still reports on an older server. Call it once when you set up a connection:

```python
--8<-- "pages/web-ui/snippets/python_client_skew.py:check"
```

Versions compare by [PEP 440](https://peps.python.org/pep-0440/), so a development build of the minimum version, such as `0.56.0.dev3`, counts as older than `0.56.0`. A server whose version isn't readable, such as `"unknown"` from a source checkout, passes, because there's nothing to compare. The example warns in that case, since nothing else will.

### What each side tolerates

| Server change | Older client, newer server | Newer client, server at or above `MIN_SERVER_VERSION` |
|---|---|---|
| New response field | Ignored | Can't be missing: new fields are optional, so an older server's response gets the default |
| New value in an open field (statuses, kinds) | Parsed as `UnknownValue` | Doesn't arise: the client knows every value the server sends |
| New value in a closed field (`source_tier`, log levels) | `ResponseValidationError`. Hassette treats this as a breaking change | Doesn't arise |
| New problem code | Raises the status's exception; `code` is an `UnknownValue` | Doesn't arise |
| New endpoint or action | No method for it | Can't happen |
| New query parameter or request field | Not sent; the server uses its default | Can't happen |
| Renamed, removed or retyped field | `ResponseValidationError`. Hassette treats this as a breaking change | `ResponseValidationError` |

Two CI checks back this table. A wire-compatibility check compares every change to Hassette's API with the latest release in both directions, and fails on a new required response field or a removed field unless the change is released as breaking. On every release, the client's requests are checked against the API of `MIN_SERVER_VERSION`, and the release can't ship until the minimum is raised to cover any endpoint, method or query parameter the client started using. That check proves each one exists on the older server, not that it means the same thing there.

"Can't happen" assumes `check_server_version()` passed with a readable version. Against an older server, a new endpoint fails with a `not_found` error, and a new query parameter is silently ignored, so the filter has no effect.

## Logging

The client logs under the `hassette_client` logger, at DEBUG only: each request's method, path, query parameter names and timeout; each response's status, media type, size and duration; each exception as it's raised, with the underlying `aiohttp` error type; and each judgment call, such as parsing a body that had no `Content-Type`. It never logs the token, cookies, body content, or a username or password in `base_url`. Nothing is logged above DEBUG, since every problem it notices is also raised, and your code decides how serious it is.

To see it in Home Assistant, add the logger to `configuration.yaml`:

```yaml
logger:
  logs:
    hassette_client: debug
```

## Parsing saved responses

`parse_response(model, body)`, also exported from `hassette_client`, parses a JSON body exactly the way the client's methods do. It checks saved responses against a client release without a running server.

## Next steps

- [API Error Responses](api-errors.md) lists every problem code and the endpoints that return it.
- [Configure Health Checks](health-endpoints.md) covers what the health endpoints report.
- [CLI Configuration](../cli/configuration.md) covers the web API token and reverse-proxy setups.
