---
task_id: "T03"
title: "Create HTTP client with instance resolution"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#1", "FR#6", "FR#7", "AC#4", "AC#11", "AC#8", "AC#9"]
---

## Summary

Create the HTTP client wrapper that CLI commands use to query the hassette REST API. Handles base URL construction from HassetteConfig, bind-all address substitution, explicit timeouts, response model deserialization, and structured error handling. Includes `--app` endpoint routing logic and `--instance` name-to-index resolution.

## Prompt

### Create `src/hassette/cli/client.py`

Build a thin wrapper around `httpx.Client` (synchronous):

**Base URL construction:**
- Read `web_api.host` and `web_api.port` from HassetteConfig
- Substitute bind-all addresses: `0.0.0.0` → `127.0.0.1`, `::` → `::1` (these are valid bind addresses but not routable connect addresses)
- Construct `http://{host}:{port}` as the base URL

**Request handling:**
- Set explicit timeout on every request (10s default)
- Deserialize responses: `model.model_validate(response.json())` where the model type is passed by the calling command
- For `dict[str, Any]` responses (services endpoint), return the raw JSON dict

**Error handling — two modes based on `--json`:**
- **Human mode**: print error detail to stderr via Rich console, `sys.exit(1)` for 4xx/5xx, `sys.exit(2)` for network errors
- **JSON mode**: emit `{"error": true, "status": <http_status>, "detail": "..."}` to stdout, same exit codes. For network errors (no HTTP status), `status` is `null`
- Connection refused: include the attempted address in the error message
- Timeout: include the timeout value and address

**`--app` endpoint routing:**
- Provide a method or parameter that commands use to select between global and per-app endpoints
- Example: `client.get_listeners(app_key=None)` → `/api/bus/listeners`; `client.get_listeners(app_key="my-app")` → `/api/telemetry/app/my-app/listeners`
- The routing logic can be a simple URL construction helper, not a separate abstraction per endpoint

**`--instance` resolution:**
- Accept `instance: str | None` parameter alongside `app_key`
- If `instance` is None, don't pass `instance_index` (let API default)
- If `instance` is a digit string (e.g., `"0"`, `"2"`), convert to int and pass as `instance_index` query param
- If `instance` is a non-digit string (e.g., `"office"`), resolve by fetching `GET /api/apps/{app_key}` (returns `AppManifestListResponse` which contains manifests with `instances: list[AppInstanceResponse]`). Match the `instance_name` field. If found, pass the matching `index` as `instance_index`. If not found, exit non-zero with an error listing available instance names.
- `--instance` without `--app` is a usage error — validate this in the client or in the calling command

**Client lifecycle:**
- Accept HassetteConfig in constructor, build httpx.Client once
- The client is used synchronously — no async, no connection pooling needed for v1

### Unit tests

Test with mocked httpx responses (use `httpx.MockTransport` or `respx`):
- Successful request returns deserialized Pydantic model
- 404 response exits with code 1 and appropriate error message
- Connection refused exits with code 2
- Timeout exits with code 2
- JSON mode error: verify stdout JSON structure `{"error": true, "status": ..., "detail": ...}`
- Human mode error: verify stderr output, nothing on stdout
- Address substitution: `0.0.0.0` → `127.0.0.1`, `::` → `::1`
- `--app` routing: verify correct URL constructed for global vs per-app endpoints
- `--instance` integer passthrough: verify `instance_index=N` in query params
- `--instance` name resolution: mock manifest response, verify correct index extracted
- `--instance` unknown name: verify error message lists available names
- `--instance` without `--app`: verify usage error

## Focus

- `src/hassette/config/config.py`: `WebApiConfig` is in `config/models.py` — check exact field names for host and port. The config object is `config.web_api.host`, `config.web_api.port`.
- Response models to import: `AppManifestListResponse` from `web/models.py` (line 131), `AppInstanceResponse` (line 90) — these are needed for instance resolution
- Exit code convention: 1 = server error (HTTP), 2 = network error (connection/timeout). This is a design doc constraint, not a general convention.
- The JSON error format (`{"error": true, ...}`) maintains the stdout-only JSON contract — scripts can reliably parse stdout even on errors.

## Verify

- [ ] FR#1: Client successfully queries a running hassette API endpoint and returns a deserialized model
- [ ] FR#6: `--app` routes to per-app telemetry endpoint; `--instance` narrows by instance index or resolved name
- [ ] FR#7: Client reads server address from HassetteConfig (which loads from env vars, .env, TOML)
- [ ] AC#4: `--app my-app` constructs URL to `/api/telemetry/app/my-app/listeners` (or equivalent per-app endpoint)
- [ ] AC#11: `--instance 1` passes `instance_index=1`; `--instance office` resolves name to index via manifest lookup
- [ ] AC#8: Connection refused produces non-zero exit with human-readable error on stderr
- [ ] AC#9: Non-default host/port from config produces correct base URL
