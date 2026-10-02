# Research Brief: RFC 9457 problem details for every /api error response (#2382)

- **Date:** 2026-09-29
- **Status:** Draft
- **Flexibility:** Decided
- **Depth:** normal
- **Motivation:** callers (HACS integration via hassette-client, #2386) need machine-readable error codes; avoid a partial rollout.
- **Constraints:** `detail` byte-identical except FastAPI 422s; `db_degrades_to` 503 degraded payloads and category C/D sites out of scope; WebSocket out of scope; CLI and frontend keep reading `detail`.
- **Non-goals:** WS messages, non-/api static responses, clients reading `code`.
- **Worktree:** `/home/jessica/source/hassette/.claude/worktrees/2382` (HEAD `a146d370`). Design target dir `design/specs/115-api-problem-details/` already exists (empty).

**Initiated by:** investigation for a design doc on issue #2382.

## Bottom line

The approach fits the stack, and every piece maps onto an existing seam. There are six things the design has to settle up front. None of them block the approach.

1. **`title` must come from a pinned table, not `http.HTTPStatus`.** On Python 3.11 the phrase for 413 is "Request Entity Too Large" and for 422 "Unprocessable Entity". On 3.14 they are "Content Too Large" and "Unprocessable Content" (verified by running both interpreters). Hassette supports 3.11 through 3.14, so a derived title would differ between CI legs. The same derivation feeds FastAPI's default OpenAPI response descriptions, so `openapi.json` would stop being deterministic too.
2. **The unhandled-`Exception` handler runs in `ServerErrorMiddleware`, outside `CORSMiddleware`.** A 500 `internal_error` body therefore carries no CORS headers. Today's plain-text 500 has none either, and the handler still re-raises afterwards.
3. **The OpenAPI override has to be selective.** `/health/ready` and `/telemetry/status` declare 503 responses using success-shaped models. A blanket "rewrite every ≥400 response to problem+json" would corrupt those two.
4. **`tests/integration/web_api/test_endpoints.py` is already 870 lines, over the 800-line HSL102 limit.** Any net growth there fails the `file-sizes` CI gate, so new tests have to go in a new file.
5. **The issue's code table has errors and gaps, and the caller's constraints contradict it in one place** (the category-D 503 in `get_app_manifest`). Details in §2.
6. **No raw-bytes serializer is needed.** A Starlette `Response` is itself an ASGI app, so `_send_413` can just call `await problem_response(...)(scope, receive, send)`.

## Context

### What prompted this

Error bodies today are `{"detail": "<string>"}` (FastAPI's default `http_exception_handler`, `.venv/.../fastapi/exception_handlers.py`). The only exceptions are FastAPI's 422 (`{"detail": [ ... ]}`) and unhandled 500s (Starlette's plain-text `Internal Server Error`). #2386's typed client exception hierarchy splits 409s by `code`, and nothing on the wire carries one today.

### Current state

**Versions (uv.lock):** fastapi `0.136.3` (uv.lock:744-745), starlette `1.3.1` (uv.lock:2651-2652), pydantic `2.12.3` (uv.lock:2047-2048). The installed `.venv` matches. Frontend openapi-typescript is `^7.13.0` (frontend/package.json:61), and 7.13.0 is installed.

**Middleware stack, outermost to innermost.** `add_middleware` does `insert(0, ...)` (starlette/applications.py:101), so the last one added ends up outermost. FastAPI's `build_middleware_stack` (fastapi/applications.py:1018-1066) wraps user middleware between two framework layers:

```
ServerErrorMiddleware          <- handler registered for Exception / 500
  CORSMiddleware               (web/app.py:80)
    RequestBodySizeLimitMiddleware  (web/app.py:78, pure ASGI)
      DefaultDenyMiddleware    (web/app.py:71, BaseHTTPMiddleware)
        ExceptionMiddleware    <- every other handler: HTTPException, RequestValidationError, ...
          AsyncExitStackMiddleware
            Router
```

**Error producers today.** 24 `HTTPException` raises across 6 route files plus app.py. Two pre-routing responses: `_unauthorized_response` (middleware.py:206-207) and `_send_413` (body_limit.py:56-71). FastAPI's own 422 and body-parse 400. Starlette routing 404/405. Unhandled 500. Full inventory in §2.

**Declared `responses=` today** (description-only, no schema): apps.py:327, 347, 366, 390, 408; scheduler.py:50; auth.py:18. Two use success models: health.py:24 (`{503: {"model": ReadinessResponse}}`) and telemetry.py:60 (`{503: {"model": TelemetryStatusResponse}}`).

### Key constraints

- `detail` must stay byte-identical. Every in-scope raise passes an explicit `detail`, so this is achievable. Starlette's `HTTPException` only fills `detail` from the phrase when it's omitted (starlette/exceptions.py:8-10).
- The web-api rule's "Category C/D" taxonomy (`.claude/rules/web-api.md`) is about DB-failure handling. The only category-D site, apps.py:305, raises an `HTTPException`, which is an error body (see §2 conflict).

---

## 1. Exception handlers vs. the middleware stack

**Where each handler runs** (fastapi/applications.py:1025-1029). Any handler keyed on `500` or `Exception` becomes `ServerErrorMiddleware`'s `handler`. Every other key goes to `ExceptionMiddleware`. `app.add_exception_handler(Exception, h)` therefore installs `h` in the outermost layer, outside CORS.

**What `ServerErrorMiddleware` does** (starlette/middleware/errors.py:163-186):
- It calls the handler and sends the response on the raw `send`, which is outside CORS.
- It skips sending if `response_started` is already set.
- It then always runs `raise exc` ("allows servers to log the error, or allows test clients to optionally raise the error").
- In `debug` mode it bypasses the handler and returns a traceback page. `FastAPI(...)` at app.py:54 doesn't set `debug`, so this doesn't apply today.

**Consequences:**
- **CORS:** a 500 `internal_error` body gets no `Access-Control-Allow-Origin`, so a cross-origin browser sees an opaque network error and can't read `code`. This isn't a regression, because today's text/plain 500 is sent from the same layer. The impact is small. The only configured origins are dev servers (`cors_origins` default `("http://localhost:3000", "http://localhost:5173")`, config/models.py:460-463). The SPA is same-origin (`FETCH_CREDENTIALS = "same-origin"`, frontend/src/api/client.ts:5), and the HACS integration calls server-to-server.
- **Re-raise still happens.** uvicorn still logs the traceback. httpx `ASGITransport` with the default `raise_app_exceptions=True` still raises inside tests. `BaseHTTPMiddleware.call_next` re-raises app exceptions on the way out (starlette/middleware/base.py:~156-168), so `DefaultDenyMiddleware` doesn't swallow them. No test uses Starlette `TestClient(raise_server_exceptions=...)`. The only test that reads a 500 body path uses `ASGITransport(app=app, raise_app_exceptions=False)` (tests/integration/web_api/test_telemetry_unavailable_seam.py:74) and asserts only `status_code == 500` (:78). It keeps passing and could add a `code == "internal_error"` assertion.
- **If CORS on 500 ever matters:** add a small pure-ASGI catch-all inside CORS (registered before `CORSMiddleware`) that sends the problem response and re-raises. `ServerErrorMiddleware` sees `response_started` and doesn't double-send. This isn't recommended now because there's no cross-origin consumer (Inferred).

**Handler lookup** (starlette/_exception_handler.py). Status-code handlers are checked first, then the exception's MRO. A `WebApiError(starlette.exceptions.HTTPException)` is therefore caught by a handler registered for Starlette's `HTTPException`, which also covers `fastapi.HTTPException` (a subclass). One handler with an `isinstance(exc, WebApiError)` branch is enough. Registering `WebApiError` separately also works. The handler must:
- **Forward `exc.headers`.** Starlette's routing 405 carries an `Allow` header (starlette/routing.py:271). FastAPI's default handler forwards headers and checks `is_body_allowed_for_status_code` (fastapi/exception_handlers.py), and the replacement should keep both behaviors.
- **Accept being called for a WebSocket scope.** `wrap_app_handling_exceptions` also calls handlers with a `WebSocket` conn and sends the returned response as a WS denial. No WS route raises `HTTPException` today (ws.py:85 closes with a policy code), so this matters only in principle.

**Routing-level errors reach the handler as `HTTPException`,** because FastAPI puts `app` in scope:
- Router 404: starlette/routing.py:616, `detail="Not Found"`.
- Route 405: routing.py:271, `detail="Method Not Allowed"`, plus `Allow`.
- `StaticFiles` 404/405 under `/assets` and `/fonts` (starlette/staticfiles.py:114-152) also become problem+json. That's harmless and consistent with the non-goal.
- When the SPA is built and `run_ui` is on, the GET-only catch-all `/{path:path}` (app.py:106) partially matches every path. A `POST /api/nonexistent` then returns **405, not 404**. The detail text of an /api 404 also depends on `run_ui` ("Not Found" vs `"/api/x not found"`, app.py:121). The error catalog shouldn't promise specific detail text for routing errors.

**Pre-routing responses stay inside CORS.** `_unauthorized_response` (DefaultDeny) and `_send_413` (body limit) both run inside `CORSMiddleware` (app.py:63-86 comments), so they keep their CORS headers after conversion. `DefaultDenyMiddleware` counts failed auth from `response.status_code == 401` (middleware.py:254, 291). That stays unchanged because only the body changes.

**Serializer shape.** No raw-bytes variant is needed. `Response.__call__` sends `http.response.start` and `http.response.body` (starlette/responses.py:163-167). `_send_413` can therefore become:

```python
await problem_response(ProblemCode.BODY_TOO_LARGE, "Request body too large",
                       headers={"x-max-body-bytes": str(max_bytes)})(scope, receive, send)
```

`JSONResponse.render` uses compact separators and `ensure_ascii=False` (responses.py:194-201), so `detail` is serialized exactly as today. A single `problem_response()` then serves the handlers, `BaseHTTPMiddleware` (which returns a `Response`), and the raw ASGI path. Build it on `JSONResponse` with `media_type="application/problem+json"`.

---

## 2. Every error-producing site in `src/hassette/web/`

### In scope: gets problem+json and a specific code

| # | Site | Status | `detail` today | Proposed code | Issue table |
|---|---|---|---|---|---|
| 1 | apps.py:76 `_validate_app_key` (called from :128, :208, :299, :444, :517) | 400 | `Invalid app_key: {app_key!r}` | `invalid_app_key` | matches |
| 2 | apps.py:111 `_require_known_app` | 404 | `App {app_key!r} not found` | `app_not_found` | matches |
| 3 | apps.py:133 `_require_valid_instance_index` (no manifest) | 404 | same | `app_not_found` | matches |
| 4 | apps.py:138 index out of range | 404 | `Instance {index} not found for app {app_key!r}` | `instance_not_found` | matches |
| 5 | apps.py:213-215 `AppBootstrapNotReleasedError` | 409 | `App bootstrap prerequisites are not ready yet; retry later` | `bootstrap_not_released` | matches |
| 6 | apps.py:217 `AppBlockedError` | 409 | `App {app_key!r} is blocked by the --app filter` | `app_blocked` | matches |
| 7 | apps.py:220 `ValueError`/`RuntimeError` from operation | 500 | `Failed to {action} app {app_key!r}` | `action_failed` | matches |
| 8 | apps.py:239 swallowed FAILED instance | 500 | registry `error_message` or generic | `action_failed` | matches (#2368 path) |
| 9 | apps.py:305 `get_app_manifest` telemetry failure (**category D**) | 503 | `Telemetry store unavailable` | `telemetry_unavailable` | table says "get_app_manifest / get_app_config" |
| 10 | apps.py:308 `get_app_manifest` unknown key | 404 | `App {app_key!r} not found` | `app_not_found` | matches |
| 11 | apps.py:447 `get_app_config` | 404 | same | `app_not_found` | matches |
| 12 | apps.py:520 `get_app_source` no manifest | 404 | same | `app_not_found` | matches |
| 13 | apps.py:528 path resolve failure | 500 | `Failed to resolve app path` | `source_unavailable` | matches |
| 14 | apps.py:537 traversal | 403 | `Path traversal not allowed` | `path_traversal` | matches |
| 15 | apps.py:540 file missing | 404 | `Source file not found for app {app_key!r}` | `source_not_found` | matches |
| 16 | apps.py:545 `FileNotFoundError` on read | 404 | same | `source_not_found` | matches |
| 17 | apps.py:548 `OSError`/`UnicodeDecodeError` | 500 | `Failed to read app source` | `source_unavailable` | matches |
| 18 | routes/auth.py:35 | 401 | `Invalid token` | `invalid_token` | matches |
| 19 | routes/executions.py:67-69 | 422 | `Invalid execution_id: {id!r} is not a valid UUID` | `invalid_execution_id` | matches |
| 20 | routes/logs.py:33-36 `_validate_choice` (level, source_tier) | 422 | `Invalid {param} {value!r}. Must be one of: ...` | `invalid_query_param` | matches |
| 21 | routes/logs.py:95 empty logger | 422 | `logger name must not be empty` | `invalid_log_level_request` | matches |
| 22 | routes/logs.py:98-101 unknown level | 422 | `Invalid log level {level!r}. Must be one of: ...` | `invalid_log_level_request` | matches |
| 23 | routes/scheduler.py:72 `ValueError` from `trigger_job` | 409 | `str(exc)` | `job_not_registered` | matches |
| 24 | routes/scheduler.py:77 `JobRemovedError` | 409 | `str(exc)` | `job_not_registered` | matches |
| 25 | **web/app.py:121** SPA catch-all (`api/*` or static-extension paths) | 404 | `/{path} not found` | `not_found` (fallback code, raised explicitly) | **missing from table** (listed under Affected Areas only) |
| 26 | middleware.py:206-207 `_unauthorized_response` | 401 | `Not authenticated` | `not_authenticated` | matches |
| 27 | body_limit.py:56-71 `_send_413` (+ `x-max-body-bytes`) | 413 | `Request body too large` | `body_too_large` | matches |

### Framework-produced, handled via the registered handlers

| Source | Status | Code |
|---|---|---|
| FastAPI `RequestValidationError` (query/path/body validation, and JSON decode, fastapi/routing.py:~426-441) | 422 | `validation_failed`. `detail` becomes a summary string and the list moves to `errors`. |
| FastAPI body-parse failure, fastapi/routing.py:445-447 `HTTPException(400, "There was an error parsing the body")` | 400 | fallback `http_error`. **Missing from table.** |
| Starlette router 404 (routing.py:616), route 405 (routing.py:271, `Allow` header), StaticFiles 404/405 | 404/405 | fallback `not_found` / `method_not_allowed` |
| Any unhandled exception, including FastAPI `ResponseValidationError` | 500 | `internal_error` (detail should be the constant `Internal Server Error`, never `str(exc)`) |

### Out of scope: success-shaped or no error status

| Site | Why excluded |
|---|---|
| `db_degrades_to`, dependencies.py:124-137, used at bus.py:28, apps.py:264, logs.py:72, scheduler.py:40, telemetry.py (10 sites incl. :74) | Degraded success payload with 503 status. Excluded by the issue. |
| **routes/executions.py:76-79** inline `response.status_code = 503` returning an empty `LogsByExecutionResponse` | Same semantics as `db_degrades_to` but hand-rolled. **Not named in the issue.** Treat it as a degraded payload and exclude it. The web-api rule says A/B sites should use `db_degrades_to`, so this site is drift. Converting it is a separate cleanup and shouldn't ride along. |
| **routes/health.py:29** readiness 503 (`ReadinessResponse`, declared at health.py:24) | A load-balancer contract documented at docs/pages/web-ui/health-endpoints.md:43-49. Not an error body. **Not named in the issue. Exclude it explicitly and document it.** |
| **routes/telemetry.py:60/74** `TelemetryStatusResponse(degraded=True)` 503 | Covered by the `db_degrades_to` exclusion, but its 503 is *declared in OpenAPI* with a success model. The OpenAPI override must not touch it. The CLI reads this body on 503 (`tolerate_503=True`, cli/commands/status.py:29). |
| Category C: apps.py:271, apps.py:317, telemetry.py:305/320/324, executions.py:42-44 | These catch and continue at 200, so no error status is produced. |
| ws.py:85 `websocket.close(code=WS_POLICY_VIOLATION_CLOSE_CODE)` | WebSocket, out of scope. |

### Issue-table problems the design must resolve

- **`telemetry_unavailable` is listed for `get_app_config`, but that route makes no telemetry call** (apps.py:430-460). The only 503 error body is apps.py:305.
- **Conflict: the caller says category D is out of scope; the issue assigns it `telemetry_unavailable`.** apps.py:305 *raises* an `HTTPException`, so it can't keep the old `{"detail"}` shape. The global `HTTPException` handler converts it regardless, and the AST guard would reject the bare raise. The only real choice is between `telemetry_unavailable` and a fallback code. Reading "category C/D out of scope" as "don't restructure their inline try/except into `db_degrades_to`", while still converting the raise, is consistent with both sources (Inferred). **Decision needed.**
- **Fallback-code rule diverges.** The issue says fallback = "snake_cased HTTP reason phrase (`not_found`, `conflict`, ...)". The proposal narrows it to `not_found`, `method_not_allowed`, `http_error`. The proposal's closed set is safer: snake-casing the Python phrase would give `request_entity_too_large`/`unprocessable_entity` on 3.11-3.12 and `content_too_large`/`unprocessable_content` on 3.13+. The issue text and the catalog must match whichever rule is chosen.
- **Type name diverges.** The issue ACs name `ApiProblem`; the proposal names `WebApiError`. The ACs need updating, or the design should use the issue's name.
- **`CODE_STATUS` can't cover `http_error`**, whose status varies (400, and any future unmapped status). Either `WebApiError` refuses fallback codes except the fixed-status ones (`not_found` → 404, `method_not_allowed` → 405), or `http_error` is produced only by the generic `HTTPException` branch using `exc.status_code`. The second is simpler.

---

## 3. OpenAPI: replacing the default 422 and declaring `application/problem+json`

**How FastAPI adds the 422** (fastapi/openapi/utils.py:453-475). For every route with params or a body, and with no `"422"`, `"4XX"` or `"default"` key already present, FastAPI adds `422: {"description": "Validation Error", "content": {"application/json": {"schema": {"$ref": ".../HTTPValidationError"}}}}` and registers `HTTPValidationError` and `ValidationError` (utils.py:42-68). `frontend/openapi.json` has 25 `"422"` entries today.

**How `responses=` entries are rendered** (utils.py:409-449):
- A `model` is always placed under `route_response_media_type or "application/json"` (utils.py:436). The route's response class is `JSONResponse`, so `"model": ProblemDetail` alone lands under **`application/json`**.
- Supplying `content={"application/problem+json": {...}}` together with `model` produces *both* media types, because `setdefault` adds `application/json` as well.
- Without `model`, FastAPI never registers the `ProblemDetail`/`ProblemCode` component schemas.
- When `description` is omitted, it defaults to `http.client.responses[int(code)]` (utils.py:442-449). That's the Python-version-dependent phrase, so 413/422 descriptions would differ across interpreters and break `tests/integration/test_schema_freshness.py:39-47` on some CI legs. **`problem_responses()` must always supply `description`.**

**Options compared:**

| Approach | Verdict |
|---|---|
| Per-route `responses={422: ...}` on every route with params | Suppresses the auto-422 but means about 25 edits and more drift surface. Rejected. |
| App-level `FastAPI(responses={422: ...})` (merged into every route, fastapi/routing.py:1370, :1734) | Documents a 422 on parameterless routes (`/health/live`, `/apps`) that can never produce one. `"4XX"`/`"default"` keys would suppress the auto-422 and blanket-document every route, but that's a bigger schema diff than needed. |
| **`openapi()` override (recommended)** | Walk `paths`: (a) on responses whose schema `$ref`s `ProblemDetail`, rename the `application/json` key to `application/problem+json`; (b) replace every `HTTPValidationError` 422 response with a ProblemDetail problem+json response (keep `description: "Validation Error"`); (c) delete `HTTPValidationError` and `ValidationError` from `components.schemas`. Leave every other response alone, especially the `ReadinessResponse`/`TelemetryStatusResponse` 503s. |

**Recommended `problem_responses(*codes)` shape:** `{status: {"model": ProblemDetail, "description": "<one clause per code, naming the code>"}}`, grouping codes by `CODE_STATUS`. Using `model` makes FastAPI hoist `ProblemDetail` and the `ProblemCode` enum into components correctly (enum `$defs` included). The override then only renames the media-type key. The alternative is to omit `model` and inject `ProblemDetail.model_json_schema(ref_template="#/components/schemas/{model}")` by hand, which means hoisting `$defs` yourself. That's more code for the same output.

**Mechanics.**
- `FastAPI.openapi()` caches in `app.openapi_schema` (fastapi/applications.py:1068+). The override should call the base implementation and post-process once.
- Assigning `app.openapi = fn` will likely need a `# pyright: ignore[reportAttributeAccessIssue]` for method assignment (Inferred, not run). A small `FastAPI` subclass overriding `openapi()` avoids that.
- Either way, `scripts/schema_helpers.py:46-49` (`build_openapi_schema` returns `app.openapi()`) picks it up, as do `scripts/export_schemas.py:50` and `tools/check_schemas_fresh.py`.

**openapi-typescript / frontend.**
- openapi-typescript 7.13.0 emits one key per media type. The generated operations will read `content: { "application/problem+json": components["schemas"]["ProblemDetail"] }`.
- `ProblemCode` as a `StrEnum` becomes a string-literal union, which is useful for #2386 and the frontend.
- The frontend imports only `components` from `generated-types.ts` (8 files: app.test.tsx, utils/app-data.ts, test/handlers.ts, execution-detail.tsx, config-tab.test.tsx, utils/status.ts, api/endpoints.ts, utils/status-priority.ts). Nothing references `paths`, `operations` or `HTTPValidationError`, so deleting `HTTPValidationError` breaks no TS code.
- CI git-diffs `generated-types.ts` (`.claude/rules/frontend-worktree.md`). Run `uv run python scripts/export_schemas.py --types` after `cd frontend && npm install` in the worktree.

**Wire model location.** `wire/src/hassette_wire/__init__.py` is the only file in the package today. #2385 (open) moves `web/models.py` there, and its AC wants a byte-identical `openapi.json`. For now `ProblemCode` and `ProblemDetail` go in `src/hassette/web/models.py` (520 lines, room to spare), and whichever of #2382/#2385 lands second carries them over. `errors.py` in `web/` must not import `core` (tools/check_module_boundaries.py:188-191 `web-no-core`).

---

## 4. Tests that assert on error bodies or content-type

**Assertions on error `detail` (7 in 3 files):**

| File:line | Assertion | Effect |
|---|---|---|
| tests/integration/web_api/test_body_limit.py:50 | `response.json() == {"detail": "Request body too large"}` | **Breaks** (exact dict). Rewrite to assert `detail` + `code` + content-type. |
| tests/integration/web_api/test_endpoints.py:269, 289, 306, 371, 408 | `response.json()["detail"] == ...` on action 500s | Pass unchanged. Adding `code` assertions here must be **line-neutral** (see §7). |
| tests/integration/web_api/test_trigger_job.py:69 | `"not currently triggerable" in response.json()["detail"]` | Passes. |

`tests/integration/web_api/test_dashboard_api.py:57` (`issue["detail"]`) is a `BootIssueResponse` field, not an error body.

**Content-type:** no web-API test asserts a response content-type. The `content-type` hits are request headers (test_body_limit.py:91, :150), the HA REST client (tests/integration/test_api.py:24), and CLI mock transports.

**422 tests:** tests/integration/web_api/test_validation.py:263 (FastAPI query range), test_body_limit.py:94, :101 (FastAPI body/field validation), test_logs_endpoint.py:108, test_execution_endpoint.py:141, test_telemetry.py:375. **All assert status only, so the 422 shape change breaks none of them.**

**500 / raise behavior:** only test_telemetry_unavailable_seam.py:74-78 (`raise_app_exceptions=False`, status only). Nothing uses `raise_server_exceptions`.

**Status-only error assertions** (unaffected, since status is unchanged), counted by `status_code == 4xx/5xx`: test_endpoints.py 27, test_auth.py 14, test_body_limit.py 8, test_api_app_source.py 4, test_validation.py 3, and 1-2 each in test_logs_endpoint, test_trigger_job, test_execution_endpoint, test_api_app_config, test_telemetry, test_telemetry_unavailable_seam, tests/unit/web/test_dependencies.py, tests/unit/core/test_web_api_service.py. The `get_json(..., expect_status=503)` calls (test_validation.py:41, 47, 84, 164; test_endpoints.py:112, 119; test_telemetry_unavailable_seam.py:38, 48, 133) all hit degraded payloads and are unaffected.

**CLI unit tests** (tests/unit/cli/test_client.py, test_client_credentials.py, test_commands_app.py, conftest.py:299): mock transports return `{"detail": ...}`. They're unaffected because the CLI reads `detail` either way.

**Frontend tests:** MSW mocks with `{detail}` (e.g. api/client.test.ts:34, login.test.tsx:46). Unaffected.

**Schema tests:** `tests/integration/test_schema_freshness.py:39-47` fails until `openapi.json` is regenerated. OpenAPI shape tests (test_endpoints.py:842, test_execution_endpoint.py:159-171) don't touch 422 or error schemas.

**New test surface:** every row in §2 plus routing 404/405 (assert `Allow` survives on 405), asserting `content-type: application/problem+json` and `code`. Also a 422 with `errors` and a string `detail`, a 500 via `raise_app_exceptions=False`, and an OpenAPI assertion that no `HTTPValidationError` remains and that the readiness/telemetry-status 503s still reference their success models.

---

## 5. CLI and frontend compatibility

**CLI** (`_handle_http_error`, src/hassette/cli/client.py:551-583):
- `detail = response.json().get("detail", response.text)` (:554). httpx's `.json()` ignores content-type, so `application/problem+json` parses normally.
- The 401 hint is appended at :558-559. `Not authenticated` and `Invalid token` stay byte-identical, so 401 output is unchanged.
- **FastAPI 422, today:** `detail` is a list, printed via `str(detail)` (:576, :583) as a Python repr like `[{'type': 'less_than_equal', 'loc': [...], ...}]`. **After:** the summary string. This improves human mode, and in `--json` mode `detail` goes from a stringified list to a clean string.
- **Unhandled 500:** today the body is text/plain, `.json()` raises `ValueError` (:555), and the fallback prints `response.text` = `Internal Server Error`. After, `detail` = `Internal Server Error`. The printed text is identical.
- The CLI's only POSTs are bodyless action routes (`post()`, :226-243). It can't trigger body-validation 422s, only query-param ones.

**Frontend** (frontend/src/api/client.ts:24-32):
- `response.json()` (fetch) ignores content-type. `body.detail ?? body.message` passes only when it's a `string`.
- The `Accept: application/json` request header (:40) isn't honored for errors because there's no content negotiation. That's fine.
- **FastAPI 422, today:** `detail` is an array, so the message is undefined and the UI shows `API error: 422 Unprocessable Entity`. **After:** it shows the summary string. The reachable cases are `PUT /api/logs/level` and `postSession` with a token over `MAX_SESSION_TOKEN_LENGTH` (4096), which the login form renders inline (:86-88).
  - **The summary must never include `input`.** Otherwise a pasted token would be echoed into the login UI.
  - The `errors` extension reproduces FastAPI's `jsonable_encoder(exc.errors())`, which *does* include `input`. That's existing behavior (the token is already echoed in today's 422 list), but it's worth deciding whether to strip it now (see Open Questions).
- **Unhandled 500:** today `json()` throws and the message is `API error: 500 Internal Server Error`. After, it's `Internal Server Error`. It's a minor wording change and needs no test update.

**Other clients.** aiohttp 3.14.3 (HA's pin, and hassette-client's likely transport) accepts `application/problem+json` in `ClientResponse.json()` by default: `json_re = r"^application/(?:[\w.+-]+?\+)?json"`, aiohttp/client_reqrep.py:90, 250-254. The content-type change therefore doesn't break aiohttp, httpx, requests or fetch consumers. A strict client doing an exact `content-type == "application/json"` check would break; none exists in-repo.

---

## 6. Docs to update and where the catalog goes

| Page | Change |
|---|---|
| docs/pages/cli/configuration.md:268-285 (Debug Mode) | The example body `{"detail":"Internal Server Error","traceback":"..."}` is already inaccurate (today's 500 is text/plain). Update it to the problem+json body. |
| docs/pages/web-ui/health-endpoints.md:43-53 | State that the readiness 503 is a status body, not problem+json (it's the deliberate exclusion). |
| docs/pages/web-ui/index.md:35-37 (413), :65 (401) | Link to the catalog. |
| docs/pages/web-ui/debug-handler.md:59 (Run Now 409) | Optionally name `job_not_registered`. |
| docs/pages/operating/log-levels.md:107 ("return `422`") | Optionally name the codes. |
| `.claude/rules/web-api.md` | Document `WebApiError`/`problem_responses` as the way to raise errors, and record why `db_degrades_to`, executions.py:78, and the readiness/telemetry-status 503s aren't problem bodies (issue AC). |
| `src/hassette/web/REVIEW.md` | Optionally add a review question: does a new error site raise `WebApiError` with a specific code, and is it declared via `problem_responses`? |

**Catalog placement.** There's no web-API reference page today. The Web UI nav section already hosts the API-facing `health-endpoints.md`. A new `docs/pages/web-ui/api-errors.md` (name TBD) with a nav entry after `Configure Health Checks` in `mkdocs.yml:95` fits the existing structure. Per CLAUDE.md, run `doc-persona-review` and `doc-accuracy-review` on the touched pages. The catalog should cover each code with its status and when it's raised, the fallback rule, and a note that routing-error `detail` text is not stable (the `run_ui` difference in §1).

---

## 7. File-size risk

- The HSL102 limit is `max_lines = 800` (pyproject.toml:244-245).
- `tools/check_file_size_regressions.py` fails only if a **touched** file already over the limit **grows**, or a new file is born over it (docstring lines 1-14).
- `src/hassette/web/routes/apps.py` is 555 lines and `web/models.py` 520, so both have ample headroom. Swapping `raise HTTPException(status_code=..., detail=...)` for `raise WebApiError(ProblemCode.X, ...)` is about line-neutral. Adding `responses=problem_responses(...)` to about 12 routes in apps.py adds a few dozen lines at most. **Low risk.**
- **High risk: `tests/integration/web_api/test_endpoints.py` is 870 lines, already over the limit.** Adding a `code` assertion next to each of the 5 `detail` assertions (:269-408) would grow it and turn the `file-sizes` check red. CLAUDE.md says to fix that in-PR. Two ways to comply:
  - Replace each `detail` assertion with a same-length helper call, e.g. `assert_problem(response, "action_failed", "...")`, so the net change is zero or negative.
  - Put all new problem-details coverage in a new file such as `tests/integration/web_api/test_problem_details.py`.
- test_auth.py (633 lines) and test_body_limit.py (187 lines) have room.

---

## Feasibility summary

| Area | Files affected | Effort | Risk |
|---|---|---|---|
| New `web/errors.py` (`WebApiError`, `CODE_STATUS`, pinned titles, `problem_response`, `problem_responses`, handlers, openapi post-processor) | 1 new | Med | Low. Needs a pinned title table and header forwarding. |
| Wire models `ProblemCode`, `ProblemDetail` | web/models.py (later hassette_wire) | Low | Coordinate with #2385 ordering. |
| Handler registration and openapi override | web/app.py | Low | The override must be selective (§3). |
| Raise-site conversion | apps.py (17), auth.py, executions.py, logs.py (3), scheduler.py (2), app.py (1) | Med | Mechanical, but `detail` must stay byte-identical. |
| Pre-routing responses | middleware.py, body_limit.py | Low | Keep `x-max-body-bytes`. |
| Guard against bare `HTTPException` | new test or `tools/` hook | Low | Scope question (below). |
| Tests | 1 break (test_body_limit.py:50) plus new file | Med | test_endpoints.py is over the size limit. |
| Regenerated schemas | frontend/openapi.json, generated-types.ts | Low | Freshness test, CI diff. |
| Docs and rule | about 4-6 pages, a new catalog page, mkdocs.yml, web-api.md | Med | Docs review skills. |

### What already supports this

- Every route error already goes through FastAPI's replaceable `HTTPException` handler, so registering a handler converts the whole surface at once, including routing 404/405 and FastAPI's body-parse 400.
- The two pre-routing responses are each one small function (middleware.py:206-207, body_limit.py:56-71).
- Every in-scope raise passes an explicit string `detail`, so byte-identity holds by construction.
- Both in-repo consumers (httpx CLI, fetch frontend) ignore content-type and read only a string `detail`.

### What works against this

- The `Exception` handler's placement outside CORS (§1).
- FastAPI puts `model=` schemas under `application/json`, so the problem+json media type needs post-processing (§3).
- Python-version-dependent status phrases feed both `title` and FastAPI's default response descriptions (§ Bottom line, §3).
- test_endpoints.py is already over the size limit (§7).

## Chosen approach: deep dive

**How it works.** `errors.py` owns the whole contract:
- A `ProblemCode → status` table and a pinned `status → title` table using RFC 9110 phrases, e.g. 413 "Content Too Large" and 422 "Unprocessable Content". Those are what RFC 9457 §4.2.1 asks for ("the title SHOULD be the same as the recommended HTTP status phrase").
- `WebApiError(code, detail, headers=None)`, which derives `status_code` from the code table.
- `problem_response(code, detail, *, status=None, headers=None, errors=None) -> JSONResponse` with `media_type="application/problem+json"`.
- Three handlers:
  - `HTTPException` (`WebApiError` passes its code through. A plain `HTTPException` maps 404 → `not_found`, 405 → `method_not_allowed`, else `http_error`, and forwards `exc.headers`.)
  - `RequestValidationError` (a summary `detail` built from `loc`+`msg` only, with `errors` = `jsonable_encoder(exc.errors())`).
  - `Exception` (`internal_error`, constant detail).
- `problem_responses(*codes)` for route declarations.
- A function that post-processes the OpenAPI dict.

`app.py` registers the handlers and installs the override. The middleware and body-limit layers call `problem_response`.

**Pros:**
- One serializer, and coverage comes from structure rather than enumeration, as the issue intends.
- Routing errors are covered for free.
- `ProblemCode` becomes a TS union and a typed wire enum for #2386.
- The CLI and frontend need no code changes.
- aiohttp, httpx and fetch all parse `+json`.

**Cons:**
- `type: "about:blank"` together with a semantic `code` goes slightly against RFC 9457 §4.2.1 ("about:blank ... indicates that the problem has no additional semantics beyond that of the HTTP status code"). It's conformant enough, since `code` is an extension member and clients must ignore unknown extensions (§3.2). A later move to per-code `type` URIs, such as catalog anchors, wouldn't break `code` readers.
- 500s stay CORS-less.
- An OpenAPI post-processor is new code with no precedent in the repo.

**Effort:** Large (the issue is labeled `size:large`). It's mechanically broad across about 27 sites, tests, schema regeneration, a docs catalog, and a rule update, but each piece is simple.

**Dependencies:** none new. Pydantic `StrEnum` and FastAPI/Starlette are already present.

## Concerns

### Technical risks

- **Version-dependent phrases** (verified on 3.11 and 3.14). `title`, any snake-cased fallback code, and default OpenAPI descriptions all vary for 413/422. Pin them.
- **Over-eager OpenAPI rewrite.** It would silently change the documented `ReadinessResponse`/`TelemetryStatusResponse` 503s (health.py:24, telemetry.py:60) that the CLI and load balancers rely on. Match on a `ProblemDetail` `$ref`, not on status range.
- **Lost headers.** A handler that doesn't forward `exc.headers` drops `Allow` on 405s.
- **Secret echo.** The 422 `detail` summary must exclude `input`. `errors` keeps today's echo unless the design strips it.
- **`POST /api/<unknown>` returns 405 when the SPA is served** (catch-all partial match). The catalog shouldn't document it as 404.

### Complexity risks

- The guard's scope. The proposal's "no bare `HTTPException` construction outside errors.py" is broader than the issue AC's "route module". It also covers app.py:121, which must be converted, and should cover both `fastapi.HTTPException` and `starlette.exceptions.HTTPException` imports.
- Repo precedent for structural rules is a `tools/check_*.py` prek hook (e.g. tools/check_coordinator_internal.py, wired in prek.toml:294-299), not a pytest. Either satisfies the AC. A prek hook fails earlier; a test runs on every CI leg.

### Maintenance risks

- The `ProblemCode` enum, `CODE_STATUS`, the docs catalog, and hass-hassette's mapping must stay in sync. A test that asserts every `ProblemCode` appears in the catalog page would turn this into a structural check.
- Once published through hassette-wire, codes are a wire contract, so renaming one is a breaking change.

## Open questions

- [ ] **apps.py:305 (category D 503):** does it get `telemetry_unavailable` (issue), or does "category C/D out of scope" mean something else? It can't keep the old shape either way.
- [ ] **Fallback-code rule:** snake-cased phrase (issue) or the closed set `not_found`/`method_not_allowed`/`http_error` (proposal)? Update the issue text to match.
- [ ] **Type name:** `WebApiError` or `ApiProblem` (issue ACs)?
- [ ] **executions.py:78 inline 503:** confirm exclusion as a degraded payload, and whether to note it in web-api.md next to `db_degrades_to`.
- [ ] **422 `errors` content:** keep FastAPI's items verbatim (with `input`), or strip `input`/`ctx`? Keeping them is the least surprising; stripping closes the token-echo path on `/api/auth/session`.
- [ ] **CORS on 500:** accept it as a known limitation, or add the inside-CORS catch-all? No cross-origin consumer was found.
- [ ] **Changelog framing:** the 422 `detail` type change (list → string) and the content-type change are wire changes. Decide whether this ships as `feat!:` with a `BREAKING CHANGE:` footer per CLAUDE.md, or as `feat:` with a note (the issue says "gets a changelog note").
- [ ] **#2385 ordering:** if #2385 lands first, `ProblemCode`/`ProblemDetail` go straight into `hassette_wire`, and its byte-identical-OpenAPI AC is unaffected. If #2382 lands first, #2385 carries two more models.
- [ ] **Not verified by running:** whether pyright accepts `app.openapi = ...` without an ignore. The exact openapi-typescript output for `application/problem+json` is inferred from its per-media-type emission; it wasn't generated.

## Recommendation

Proceed with the decided design, with these adjustments written into the design doc:

- Pin titles (and any OpenAPI descriptions) instead of deriving them from `http.HTTPStatus`.
- Drop the raw-bytes serializer variant in favor of calling the `Response` as an ASGI app.
- Make the OpenAPI post-processor match `ProblemDetail` references, not status ranges.
- Forward `HTTPException.headers`.
- Put new tests in a new file and keep test_endpoints.py line-neutral.
- Explicitly list executions.py:78, health.py:29 and telemetry.py:74 as excluded degraded payloads.

Before writing tasks, resolve the apps.py:305 conflict and the fallback-rule and naming divergences with the issue.

### Suggested next steps

1. Write `design/specs/115-api-problem-details/design.md` via `/mine-define`, using §2's inventory as the conversion table and §3's override algorithm.
2. Update the #2382 body to fix the `get_app_config` row, add the SPA 404 and the FastAPI body-parse 400, and align the fallback rule and type name with the design.
3. Spike the OpenAPI post-processor against `scripts/schema_helpers.build_openapi_schema` and diff `openapi.json`/`generated-types.ts` before converting raise sites. It's the one piece with no repo precedent.

## Sources

- RFC 9457 (§3.1.1 type default, §3.1.4 detail, §3.2 extensions, §4.2.1 about:blank): https://www.rfc-editor.org/rfc/rfc9457.html
- Local package sources under `.venv/lib/python3.14/site-packages/` (fastapi 0.136.3, starlette 1.3.1, aiohttp 3.14.3), cited inline.
