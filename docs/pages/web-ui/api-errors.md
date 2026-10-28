# API Error Responses

Every error response from the web API (paths under `/api`) is an [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html) problem details body, served as `application/problem+json`. Its `code` member names the reason for the failure. A client branches on `code`, never on the message text.

```json
{
  "type": "about:blank",
  "title": "Conflict",
  "status": 409,
  "detail": "App 'garage_door' is blocked by the --app filter",
  "code": "app_blocked"
}
```

## Body members

| Member | Contents |
|---|---|
| `type` | Always `about:blank`. `code` carries the specific meaning. |
| `title` | The HTTP reason phrase for `status`, such as `Not Found` or `Unprocessable Content`. |
| `status` | The HTTP status code, repeated from the response. |
| `detail` | A human-readable explanation of this failure. Clients display it and don't parse it. |
| `code` | The machine-readable reason. One of the codes below. |
| `outcomes` | Only on an error from an app action that acted on at least one instance: what the action did to each instance. See [App action outcomes](#app-action-outcomes). |

A body carries these members and no others. Headers such as `Allow` on a `405` and `X-Max-Body-Bytes` on a `413` still arrive on the response.

## Endpoint codes

These codes come from specific endpoints. Each endpoint lists the ones it can return under `x-problem-codes` on each error response in the interactive API docs at `/api/docs`.

| Code | Status | Meaning |
|---|---|---|
| `invalid_app_key` | 400 | The app key in the path is not a valid app key. |
| `app_not_found` | 404 | No app with this key is configured. |
| `instance_not_found` | 404 | The instance index is out of range for the app's current config. |
| `bootstrap_not_released` | 409 | App bootstrap prerequisites aren't ready yet. Retry the start or reload later. |
| `app_blocked` | 409 | The `--app` filter excludes this app. Retrying won't help until the filter changes. |
| `action_in_progress` | 409 | Another start, stop, or reload on this app is still running, so this one was rejected without running. |
| `needs_restart` | 409 | A targeted instance needs a Hassette restart, so the start, stop, or reload did nothing to it. Retrying won't help until Hassette restarts. |
| `action_failed` | 500 | A start, stop, or reload failed on at least one targeted instance. `detail` names each one with its failure. |
| `telemetry_unavailable` | 503 | The telemetry database could not be read. |
| `source_not_found` | 404 | The app's source file doesn't exist. |
| `path_traversal` | 403 | The app's source path resolves outside its app directory. |
| `source_unavailable` | 500 | The app's source file exists but could not be read. |
| `invalid_token` | 401 | The token sent to `POST /api/auth/session` is wrong. |
| `job_not_registered` | 409 | The scheduled job has no live registration: never registered, or removed since the caller saw it. |

The four `409` codes on the app action endpoints (`POST /api/apps/{app_key}/start` and the others) mean different things. `bootstrap_not_released` clears on its own once Hassette finishes connecting, so a retry succeeds. `app_blocked` does not clear until the `--app` filter changes. `needs_restart` does not clear until Hassette restarts. `action_in_progress` means Hassette is still working on an earlier action for the same app, such as a reload whose request timed out on the client side. Hassette rejects the new action instead of queuing it. Once the app's status shows the earlier action has finished, the same request succeeds.

## App action outcomes

An app action (`POST /api/apps/{app_key}/start`, `/stop`, `/reload`, and the per-instance `/instances/{index}/...` forms) finishes before it answers, and reports what it did to each instance it targeted. A whole-app action targets every configured instance. A stop or reload also targets any instance Hassette still tracks outside the current config, and a reload only stops those. Each entry in `outcomes` has these members:

| Member | Contents |
|---|---|
| `instance_index` | The instance's index in the app's config. |
| `instance_name` | The instance's name. |
| `result` | `succeeded`, `failed`, or `refused`. |
| `needs_restart` | Whether the instance needs a Hassette restart after this action. |
| `reason` | The failure or refusal. On a success, a note on anything beyond a plain success, such as `already running`, or an earlier stop failure a reload recovered from. Otherwise `null`. |

`refused` means the instance needs a Hassette restart from an earlier action: its last shutdown left work that may still be running, so Hassette doesn't start, stop, or reload it again. An instance this action left needing a restart is `failed` with `needs_restart` set.

The worst outcome sets the response:

- Any `failed` instance: `500` `action_failed`.
- Otherwise, any `refused` instance: `409` `needs_restart`.
- Otherwise: `200`, with `outcomes` in the `ActionResponse` body.

So a whole-app action that worked on two instances and failed on a third answers `500`, and its `outcomes` still shows the two that worked. On an error, `detail` names each instance that didn't succeed, with its reason, after a count of how many did:

```json
{
  "type": "about:blank",
  "title": "Conflict",
  "status": 409,
  "detail": "Stopped 1 of 2 instances of app 'lights'; 'porch' needs a hassette restart (flagged at 2024-01-01T12:00:00-06:00[America/Chicago]: on_shutdown timed out)",
  "code": "needs_restart",
  "outcomes": [
    {"instance_index": 0, "instance_name": "hall", "result": "succeeded", "needs_restart": false, "reason": null},
    {"instance_index": 1, "instance_name": "porch", "result": "refused", "needs_restart": true, "reason": "needs a hassette restart (flagged at 2024-01-01T12:00:00-06:00[America/Chicago]: on_shutdown timed out)"}
  ]
}
```

A reload of an app the [`--app` filter](../cli/commands.md#hassette-run) blocks stops the app before it is refused, so its `app_blocked` body carries the stop's `outcomes`. So does an `app_not_found` from a reload whose app left the config while it ran. Every other error from these endpoints is answered before any instance is touched, and has no `outcomes`.

## Codes any endpoint can return

These codes come from routing, authentication, request validation, or an unexpected failure. They apply to every endpoint, so `/api/docs` doesn't list them per endpoint.

| Code | Status | Meaning |
|---|---|---|
| `not_authenticated` | 401 | The request carried no valid credential. See [Web UI](index.md) for how authentication works. |
| `body_too_large` | 413 | The request body is over the 64 KiB limit. `X-Max-Body-Bytes` carries the limit. |
| `validation_failed` | 422 | A path, query, or body value failed validation. |
| `not_found` | 404 | Nothing exists at this path. |
| `method_not_allowed` | 405 | The path exists but doesn't accept this method. `Allow` lists the methods it does accept. |
| `http_error` | varies | Any other HTTP error, such as a `400` for a request body that isn't valid UTF-8. `status` carries the actual status. |
| `internal_error` | 500 | An unexpected server error. |

A `validation_failed` body summarizes each failure as `location: message`, joined by `; `. For example, `Validation failed: query.limit: Input should be greater than or equal to 1`. The summary never repeats the rejected value, so a pasted token can't come back in an error message.

An `internal_error` body always carries the same `detail`, `Internal Server Error`. The traceback goes to Hassette's log with the request's method and path, and never into the response.

The `detail` text of `not_found` and `method_not_allowed` comes from the router and is not stable. Clients match on `code` instead.

## Responses that aren't problem bodies

Two health probes answer `503` with their normal `application/json` status body, not a problem body:

- `GET /api/health/ready` returns its readiness body with a `503` while Hassette is starting or degraded. See [Configure Health Checks](health-endpoints.md).
- `GET /api/telemetry/status` returns its status body with a `503` when the telemetry database is degraded.

Endpoints that read history from the telemetry database (logs, executions, listeners, jobs, telemetry, app manifests) answer `telemetry_unavailable` when that database can't be read. A few of them still answer `200` when only an optional part of the response is unavailable, for example the dashboard's per-app statistics, which fall back to zeros.

A rejected CORS preflight (an `OPTIONS` request whose origin, method, or headers fall outside `cors_origins` and the allowed methods and headers) returns a `400` with a `text/plain` body. Browsers report a failed preflight to the calling script as a network error and never expose its body. Non-browser clients don't send preflights.

The WebSocket at `/api/ws` reports problems with close codes, not problem bodies.

## Stability

`code` values are part of the wire contract published in the `hassette-wire` package. Before Hassette 1.0, a code can still be renamed or removed, or have its status changed. Any such change ships as a breaking change, called out in the changelog. New codes can appear in any release, so a client should treat an unrecognized code by its `status`.

The `hassette-wire` package exports the code set as the `ProblemCode` enum and the body as the `ProblemDetail` model.

## Related Pages

- [Web UI](index.md): authentication and the request body limit
- [Configure Health Checks](health-endpoints.md): the readiness and liveness endpoints
- [CLI Configuration](../cli/configuration.md): how the `hassette` CLI reports these errors
