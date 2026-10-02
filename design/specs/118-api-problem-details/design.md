# Design: RFC 9457 problem details for every web API error response

**Date:** 2026-10-02
**Status:** ratified
**Mode:** sketch

## Summary

Issue #2382. Error responses from hassette's web API (`/api/*`) are `{"detail": "<free text>"}`, so a caller that must act on *why* a request failed can only match prose. The driving case: `POST /api/apps/{key}/start` returns 409 both when app bootstrap hasn't released (retry later) and when the `--app` filter blocks the app (never works). `hassette-client` (#2386) and the HACS companion integration need to tell those apart. The error surface is also inconsistent: FastAPI's 422 has a list-typed `detail`, unhandled 500s are `text/plain`, and the middleware 401 and 413 are hand-built JSON.

The change makes every non-2xx error body under `/api` an RFC 9457 `application/problem+json` body with a stable machine-readable `code` (body shape in D2), keeps every status and existing header, and describes the shape in OpenAPI and the generated TypeScript types. It ships as `feat!:`.

Files involved:

- `wire/src/hassette_wire/`: new `ProblemCode` and `ProblemDetail` (new module, exported from the package root like every other wire model).
- `src/hassette/web/errors.py` (new, server-only, must not import `hassette.core`: the `web-no-core` rule in `tools/check_module_boundaries.py`): `WebApiError`, `CODE_STATUS`, `STATUS_TITLES`, `problem_response()`, `problem_responses()`, three exception handlers, `install_problem_openapi()`.
- `src/hassette/web/app.py` (handler registration, OpenAPI install, SPA catch-all), `middleware.py` (`_unauthorized_response`), `body_limit.py` (`_send_413` and its two call sites).
- `src/hassette/web/routes/apps.py`, `auth.py`, `executions.py`, `logs.py`, `scheduler.py`: every `HTTPException(...)` becomes `WebApiError(...)` with the same `detail` expression and the same `from exc` chaining; every route gets `responses=problem_responses(...)`.
- Regenerated `frontend/openapi.json` and `frontend/src/api/generated-types.ts` (`uv run python scripts/export_schemas.py --types`).
- Docs: new catalog page `docs/pages/web-ui/api-errors.md` (nav entry in `mkdocs.yml` after "Configure Health Checks"); updates to `docs/pages/cli/configuration.md` (Debug Mode's 500 example body), `docs/pages/web-ui/health-endpoints.md` (the readiness 503 is a status body, not a problem body), `docs/pages/web-ui/index.md` (link the 401/413 mentions to the catalog), `docs/pages/web-ui/debug-handler.md` (Run Now 409) and `docs/pages/operating/log-levels.md` (422) naming their codes. Internal: a new "Error responses" section in `.claude/rules/web-api.md`, a review question in `src/hassette/web/REVIEW.md`, and a correction to every place `design/specs/114-hassette-client/brief.md` assumes #2382 covers only the app action routes: "The client" section (drop the "until #2369 extends problem details repo-wide" clause), the #2382 row of the work-package table (the full `ProblemCode` set, not just the six action codes; drop "First slice of #2369"), the "Scope Boundaries" Out bullet ("problem details beyond the app action routes (#2369)"), and the "Related issues" mention of #2369 (closed as not planned; #2382 now covers its scope).

Out of scope: WebSocket (`/api/ws`) messages and close codes; the CLI (`src/hassette/cli/client.py`) and frontend (`frontend/src/api/client.ts`) reading `code` (both keep reading `detail`); restructuring category-C/D telemetry handling from `.claude/rules/web-api.md`; non-`/api` responses (SPA HTML; `StaticFiles` 404/405s under `/assets` and `/fonts` pick up the problem shape incidentally through the global handler, which is harmless).

Supporting research: `design/specs/118-api-problem-details/research.md` (line-level error-site inventory in §2, OpenAPI override in §3, tests that assert on error bodies in §4) and `design/research/2026-09-29-openapi-per-operation-error-codes/research.md`. Both were written for an earlier define-phase design of this issue (spec 115, never executed); every decision below marked "carried" was approved there. `design/research/2026-10-02-error-declaration-drift/research.md` (prior art on keeping per-route error declarations accurate, and on per-operation 5xx) informs D10.

Size: about 24 mechanical raise-site conversions, one new ~250-line module, four new test files, and seven doc pages. Expected to fit one build session, but on the large side.

## Decisions

### D1: Which error responses get the problem shape?

**Deciding factor:** clients handle one error shape, forever.

| | A: every `/api` error response | B: app action routes only (issue's original scope; rest in #2369) |
|---|---|---|
| Shapes a client must handle | one | two, indefinitely ("has a code" and "doesn't") |
| Unblocks #2386 | yes | yes |
| Diff size | ~24 sites + middleware + framework handlers | ~6 sites, but needs a handler anyway |
| Follow-up risk | none | #2369 has no milestone to pull it forward after HACS v0.1 |

**Recommendation:** A, because B ships a second error shape that every client then carries forever.
**Pick B instead if** #2386 were urgent enough that the extra scope blocked it.
**Reversibility:** hard (B's mixed shape becomes a contract the moment a client handles it)
**Ratified:** Chose every `/api` error response over action routes only, to achieve a single error shape for all clients, accepting the larger diff. (Carried from the approved spec-115 design; the user rejected B.)

Covered, each with the code(s) it must return (codes and statuses in D3/D4). This table is the single source for error coverage, and the build's integration coverage has one case per (row, code) pair. Each case pins status, content-type, `type`, `title`, `code`, exact `detail`, and, for route rows, that the code is listed in that operation's `x-problem-codes` for the status (D10). Stop-only permissiveness for orphaned apps and instances (`_orphan_app_permitted`) is unchanged, so `app_not_found`/`instance_not_found` are triggered via start or reload.

| Row | Trigger | Codes |
|---|---|---|
| `POST /api/apps/{app_key}/start`, `/stop`, `/reload` | bad key; unknown app; bootstrap not released; `--app` filter; operation raises or an instance ends FAILED | `invalid_app_key`, `app_not_found`, `bootstrap_not_released`, `app_blocked`, `action_failed` |
| `POST /api/apps/{app_key}/instances/{index}/start`, `/stop`, `/reload` | as above, plus out-of-range index | the app-route codes plus `instance_not_found` |
| `GET /api/apps/{app_key}/manifest` | bad key; telemetry unavailable; unknown app | `invalid_app_key`, `telemetry_unavailable`, `app_not_found` |
| `GET /api/apps/{app_key}/config` | bad key; unknown app | `invalid_app_key`, `app_not_found` |
| `GET /api/apps/{app_key}/source` | bad key; unknown app; path resolve fails; traversal; file missing or `FileNotFoundError`; `OSError`/`UnicodeDecodeError` | `invalid_app_key`, `app_not_found`, `source_unavailable`, `path_traversal`, `source_not_found` |
| `POST /api/auth/session` | wrong token | `invalid_token` |
| `GET /api/executions/{execution_id}` | non-UUID id | `validation_failed` (D4) |
| `GET /api/logs/recent` | bad `level` or `source_tier` | `validation_failed` (D4) |
| `PUT /api/logs/level` | empty logger; unknown level | `validation_failed` (D4) |
| `POST /api/scheduler/jobs/{job_id}/trigger` | unregistered or removed job (both raise sites) | `job_not_registered` |
| `DefaultDenyMiddleware` | protected route, no credential (`detail: "Not authenticated"`) | `not_authenticated` |
| `RequestBodySizeLimitMiddleware` | body over the limit; keeps `x-max-body-bytes` | `body_too_large` |
| FastAPI request validation | out-of-range query param; oversized field carrying a sentinel value | `validation_failed` (body per D6) |
| FastAPI body parsing | malformed JSON body (FastAPI's own `HTTPException(400)`) | `http_error`, status 400 |
| Router, `run_ui` off and on | `GET` and `POST` to `/api/nonexistent` | `not_found`, `detail: "Not Found"`, all four combinations (D8) |
| SPA catch-all, `run_ui` on | `GET /missing.js` (static extension, no built file) | `not_found`, `detail: "/missing.js not found"` |
| Router, `run_ui` off and on | `POST` to a GET-only route (e.g. `/api/apps`); keeps `Allow` | `method_not_allowed` |
| Unhandled exception | a route dependency raises `RuntimeError` | `internal_error` (D7) |
| Degraded payload (negative case) | a `db_degrades_to` route with telemetry unavailable | none: 503 success body unchanged, `application/json` (D13) |

### D2: What does a problem body look like?

**Deciding factor:** a standard shape with a stable discriminator, without hosting anything.

| | A: RFC 9457, `type: "about:blank"`, `code` extension member | B: RFC 9457 with per-code `type` URIs | C: custom envelope (`{"error": {"code", "message"}}`) |
|---|---|---|---|
| Standard | yes (§3.2 extension members) | yes | no |
| Needs hosted, stable URIs | no | yes | no |
| Existing `detail` readers (CLI, frontend) | unaffected | unaffected | break |
| Later migration | B can be added without breaking `code` readers | n/a | n/a |

**Recommendation:** A, because it's standard, keeps `detail` readers working, and leaves B open.
**Pick B instead if** a consumer needs dereferenceable error docs. **Pick C instead if** never.
**Reversibility:** easy toward B; hard otherwise
**Ratified:** Chose RFC 9457 with `type: "about:blank"` and a `code` extension over per-code type URIs, to achieve a standard shape with a semantic discriminator and no hosting, accepting that `type` carries no meaning beyond the status. (Carried; the user chose this in spec 115's discovery.)

Body behavior: served with `Content-Type: application/problem+json`; members are exactly `type`, `title`, `status`, `detail`, `code`. `status` equals the HTTP status. `title` is the RFC 9110 reason phrase for the status (IANA registry phrase where RFC 9110 defines none, e.g. 429), from a literal pinned table (`STATUS_TITLES`) covering every 4xx and 5xx `http.HTTPStatus` member, identical on every supported Python. A status outside `http.HTTPStatus` gets `title: "Error"`. `detail` is byte-identical to today's string everywhere it is a string today. Headers on an `HTTPException` (e.g. `Allow`) are preserved. Body-less statuses keep FastAPI's `is_body_allowed_for_status_code` behavior.

### D3: How are codes defined and bound to statuses?

**Deciding factor:** a code can never go out with the wrong status, and the set is typed.

| | A: closed `ProblemCode` StrEnum in `hassette_wire`; each code bound to one status in `CODE_STATUS`; fixed fallback codes | B: specific codes plus a snake-cased reason phrase as the fallback code |
|---|---|---|
| Typed enum for clients and TS | yes | no (open-ended set) |
| Stable across Python versions | yes | no: 3.11–3.12 give `request_entity_too_large`/`unprocessable_entity`, 3.13+ give `content_too_large`/`unprocessable_content` |
| Unmapped `HTTPException`s | `not_found` (404), `method_not_allowed` (405), `http_error` (any other, carrying that status) | phrase-derived |

**Recommendation:** A, because B's fallback codes change with the Python version and can't be an enum.
**Pick B instead if** never.
**Reversibility:** hard (codes are client-visible; changing one is a flagged break, see D14)
**Ratified:** Chose a closed `ProblemCode` enum with one status per code (`CODE_STATUS`), fixed fallback codes, and 401 reserved for the two auth codes, over phrase-derived fallbacks, to achieve a typed, version-stable code set that keeps failed-auth counting correct, accepting that every new error site needs a deliberate code.

The code set (statuses fixed; `http_error` is the only code without one and is produced only by the fallback branch):

| Code | Status | Raised by |
|---|---|---|
| `invalid_app_key` | 400 | `_validate_app_key` (every route taking an `app_key`) |
| `app_not_found` | 404 | `_require_known_app`, `_require_valid_instance_index`, `get_app_manifest`, `get_app_config`, `get_app_source` |
| `instance_not_found` | 404 | `_require_valid_instance_index` |
| `bootstrap_not_released` | 409 | `_run_app_action` |
| `app_blocked` | 409 | `_run_app_action` |
| `action_failed` | 500 | `_run_app_action` (operation raised, or a targeted instance ended FAILED; multi-instance failures surface the lowest-indexed instance's message; an empty `error_message` keeps today's `Failed to {action} app {key!r}` fallback) |
| `telemetry_unavailable` | 503 | `get_app_manifest` (its single category-D raise; control flow unchanged) |
| `source_not_found` | 404 | `get_app_source` |
| `path_traversal` | 403 | `get_app_source` |
| `source_unavailable` | 500 | `get_app_source` |
| `invalid_token` | 401 | `routes/auth.py` `create_session` |
| `not_authenticated` | 401 | `DefaultDenyMiddleware` |
| `job_not_registered` | 409 | `routes/scheduler.py` trigger |
| `validation_failed` | 422 | FastAPI request validation; the hand-raised 422s in `routes/executions.py`, `routes/logs.py` `_validate_choice`, and `routes/logs.py` set-level (D4) |
| `body_too_large` | 413 | `RequestBodySizeLimitMiddleware` |
| `not_found` | 404 | fallback (every unknown `/api` path), plus the SPA catch-all's static-extension 404, raised explicitly |
| `method_not_allowed` | 405 | fallback |
| `http_error` | varies | fallback for any other `HTTPException` status |
| `internal_error` | 500 | unhandled exceptions |

`ProblemDetail` is a Pydantic `BaseModel`: `type: str = "about:blank"`, `title: str`, `status: int`, `detail: str`, `code: ProblemCode`, no other members (D6). It is both the OpenAPI schema and the shape clients parse.

**401 is reserved for authentication failures.** `DefaultDenyMiddleware` counts every outgoing 401 as a failed auth attempt and rate-limits on that count (`src/hassette/web/middleware.py`). So only `not_authenticated` and `invalid_token` may map to 401 in `CODE_STATUS`. A unit test over `CODE_STATUS` pins this: a third 401 code fails it. The `.claude/rules/web-api.md` "Error responses" section states the rule. The counter itself is unchanged and still keys off status.

### D4: Do the hand-validated 422s get their own codes, or share `validation_failed`?

Three routes reject input by hand with a 422: `routes/executions.py` (non-UUID `execution_id`), `routes/logs.py` `_validate_choice` (bad `level`/`source_tier` query param), and `routes/logs.py` set-level (empty logger name, unknown level). The spec-115 design gave them three codes: `invalid_execution_id`, `invalid_query_param`, `invalid_log_level_request`. Reopened here because every code is client-visible wire contract (D14) and no known client branches on these.

**Deciding factor:** smallest code set that still lets every known client branch where it needs to.

| | A: three own codes (spec 115) | B: reuse `validation_failed` |
|---|---|---|
| Code set size | +3 codes | +0 |
| What a client can do differently | nothing: all mean "fix your input" | same |
| `detail` | today's strings, byte-identical | same (unchanged; `validation_failed`'s `detail` is human text whatever produced it) |
| Splitting later | n/a | changes those sites from `validation_failed` to a new code: a break for anyone matching `validation_failed` there |
| Merging later | removing codes is a break | n/a |
| Matches "one code per meaning" | three codes for one meaning | yes |

**Recommendation:** B, because the three codes add contract surface with nothing a client would do differently, and a 422 means the same thing whether pydantic or a route raised it.
**Pick A instead if** you expect a client (the HA integration, a future UI) to react specifically to, say, a bad log level differently from a bad query param.
**Reversibility:** hard either way (both directions break code-matchers)
**Ratified:** Chose reusing `validation_failed` over three route-specific 422 codes, to achieve the smallest code set, accepting that splitting them out later would break clients matching `validation_failed` at those sites.

### D5: How do routes raise a coded error?

**Deciding factor:** one handler covers specific and fallback cases, including framework-raised exceptions.

| | A: `WebApiError(HTTPException)`, status from `CODE_STATUS` | B: separate `ApiProblem` exception alongside `HTTPException` |
|---|---|---|
| Handlers needed | one `HTTPException` handler for both | two |
| FastAPI/Starlette's own `HTTPException`s | same path | separate path |
| Call site | `raise WebApiError(ProblemCode.APP_NOT_FOUND, f"App {app_key!r} not found") from exc` | `raise ApiProblem(ProblemCode.APP_NOT_FOUND, ...) from exc`, plus framework `HTTPException`s still raised separately |

**Recommendation:** A, because subclassing puts every `HTTPException` (ours and the framework's) through one handler.
**Pick B instead if** never.
**Reversibility:** easy (internal API)
**Ratified:** Chose `WebApiError` subclassing `HTTPException` over a separate exception type, to achieve one handler for specific and fallback errors, accepting the coupling to Starlette's exception class. (Carried.)

Naming: `WebApiError` is the user's choice, over `ApiProblem`/`ApiProblemError` and over `ApiError`, which collides with HA `Api` naming and the frontend's TS `ApiError`.

`WebApiError(code, detail, headers=None)` rejects `ProblemCode.HTTP_ERROR`. `problem_response(code, detail, *, status=None, headers=None) -> JSONResponse` is the single body builder (status defaults to `CODE_STATUS[code]`). It's used by all three handlers and by the 401/413 middleware (D1); a Starlette `Response` is an ASGI app, so `_send_413` awaits it as one rather than serializing separately. No second serializer.

### D6: What does a validation 422 carry?

**Deciding factor:** never echo rejected input, and don't freeze pydantic's error-dict shape into the contract.

| | A: string `detail` summarizing each error's `loc` + `msg`, no extension members | B: A plus pydantic's `errors()` list as an extension member | C: keep FastAPI's list-typed `detail` |
|---|---|---|---|
| Echoes rejected input | no | yes (`input`): `/api/auth/session` would echo a pasted token | yes |
| Contract | five standard members | pydantic's untyped `ctx`, version-pinned `url` become permanent | list `detail` contradicts D2 |
| Field-level detail for clients | prose only | structured | structured |
| Later | a typed per-field list can be added without breaking anyone | can never be narrowed | n/a |

**Recommendation:** A, because B and C leak input and freeze an unowned shape, and A can grow a typed list later.
**Pick B instead if** a client needs field-level errors now, and it would then be a typed list, not raw dicts.
**Reversibility:** easy toward a typed list; hard otherwise
**Ratified:** Chose a string summary from `loc` and `msg` with no extension members over pydantic's raw error list, to achieve no input echo and a narrow contract, accepting prose-only field errors. (Carried.)

Format: `"Validation failed: query.limit: Input should be less than or equal to 1000"`, multiple errors joined by `"; "`. Hassette's own request-model validators must never interpolate the validated value into their message (it would reach `detail`); this rule goes in `.claude/rules/web-api.md`.

### D7: What does an unhandled exception return?

**Deciding factor:** never leak exception text; don't add machinery for a consumer that doesn't exist.

| | A: `internal_error`, constant `detail: "Internal Server Error"`, handler in `ServerErrorMiddleware` (no CORS headers) | B: A but `detail = str(exc)` | C: A plus a pure-ASGI catch-all inside `CORSMiddleware` |
|---|---|---|---|
| Leaks internals | no | yes | no |
| CORS on 500s | none (same as today's text/plain 500) | none | yes |
| Who's affected by CORS-less 500s | only the cross-origin frontend dev server (production SPA is same-origin; HA integration and CLI aren't browsers) | same | nobody |
| Extra machinery | none | none | a second catch-all |

**Recommendation:** A, because C solves a problem nobody has and B leaks.
**Pick C instead if** a real cross-origin browser consumer appears.
**Reversibility:** easy
**Ratified:** Chose a constant-detail `internal_error` without CORS headers, logged via `LOGGER.exception` with method and path, over an inner ASGI catch-all, to achieve no leakage and a traceback with request context in hassette's own log, accepting that unhandled 500s stay CORS-less (affects only the cross-origin frontend dev server).

The handler logs `LOGGER.exception("Unhandled exception on %s %s", method, path)` before returning, so hassette's own log has a single record with the request context and the traceback. That's needed because Starlette re-raises after the handler and uvicorn logs the traceback, but `WebApiService` builds `uvicorn.Config` without a `log_config` (`src/hassette/core/web_api_service.py`), so uvicorn's default config sends its `uvicorn` logger to its own stderr handler with `propagate: False` (`uvicorn/config.py`, `LOGGING_CONFIG`). That copy never reaches hassette's log handlers or the web UI log view, and it carries no method or path. `debug=True` (unset in hassette) would bypass this handler; an exception after the response has started still sends no body. Both are existing behavior and stay that way.

### D8: What does an unknown `/api` path return?

Today the GET-only SPA catch-all `/{path:path}` partially matches every path, so with the SPA served `POST /api/nonexistent` is 405 (`Allow: GET`) and `GET /api/nonexistent` is 404 `"/api/nonexistent not found"`; with `run_ui` off both are Starlette's 404 `"Not Found"`.

**Deciding factor:** the same answer regardless of `run_ui`, without breaking real 405s.

| | A: keep the catch-all off `/api` via a custom path convertor (regex `(?!api(?:/\|$)).*`, registered once at module import under the key `hassette_spa_path` with `starlette.convertors.register_url_convertor`) | B: leave routing as is | C: a full-match `/api/{path:path}` fallback route |
|---|---|---|---|
| Unknown `/api` path | always 404 `not_found`, `"Not Found"` | 404 or 405 depending on `run_ui` and method | 404 |
| Wrong method on a real `/api` route | 405 `method_not_allowed` with `Allow` | same | shadowed: becomes 404 |
| Breaking | non-GET unknown `/api` with SPA served: 405 → 404 | none | real 405s lost |
| Dead code removed | the catch-all's `path.startswith("api/")` branch | none | none |

**Recommendation:** A, because it's the only option where `run_ui` stops changing API semantics and real 405s survive.
**Pick B instead if** you'd rather not ship the 405 → 404 change in this PR.
**Reversibility:** easy
**Ratified:** Chose a catch-all convertor registered once at import under `hassette_spa_path` with its global scope declared, over the current routing, to achieve run_ui-independent 404s for unknown API paths, accepting a declared process-global registration and a 405 → 404 change for non-GET unknown paths with the SPA served.

`register_url_convertor` writes into Starlette's module-level `CONVERTOR_TYPES` dict, shared by every Starlette/FastAPI app in the interpreter (`starlette/convertors.py`, `register_url_convertor`). There is no per-app registry. So the convertor is registered once, at import of the module that defines it (not inside `create_fastapi_app()`, which tests call many times), under the hassette-specific key `hassette_spa_path`, with a comment stating the global scope. That's acceptable because the key is unique to hassette, re-registration is idempotent, and the convertor affects only routes that name it.

The catch-all's static-extension 404 stays and raises `WebApiError(ProblemCode.NOT_FOUND, f"/{path} not found")`.

### D9: How does OpenAPI describe problem responses?

FastAPI always files `model=` schemas under `application/json` and emits its own `HTTPValidationError` 422 on every route with parameters.

**Deciding factor:** every error response documented correctly without per-route drift, and success-model 503s left alone.

| | A: post-process the generated document (FastAPI's documented `app.openapi = fn` recipe) | B: per-route `responses={422: ...}` | C: app-level `responses=` |
|---|---|---|---|
| Edits | one function, `install_problem_openapi(app)` | ~25 route edits that drift | one |
| Accuracy | exact: rewrites only responses referencing `ProblemDetail`/`HTTPValidationError` | exact while maintained | documents 422 on parameterless routes that can't return one |
| Precedent in repo | none (new post-processor) | n/a | n/a |

**Recommendation:** A, because it's one place, exact, and it's FastAPI's documented extension point.
**Pick B instead if** a post-processor is unacceptable in principle.
**Reversibility:** easy
**Ratified:** Chose a post-processor via FastAPI's documented `app.openapi` recipe, plus a `run_ui`-independent schema (catch-all excluded, pinned by a test), over per-route or app-level 422 overrides, to achieve exact docs with no drift on every install, accepting a new mechanism with no repo precedent.

Behavior: (a) every response whose schema references `ProblemDetail` is under `application/problem+json` only; (b) every response referencing `HTTPValidationError` becomes a `ProblemDetail` problem+json response keeping `description: "Validation Error"`; (c) the `HTTPValidationError` and `ValidationError` components are gone. Matching is on references, never on status ranges: a status-range rewrite would corrupt the `/api/health/ready` and `/api/telemetry/status` 503s, which keep `ReadinessResponse`/`TelemetryStatusResponse` under `application/json`. No `title` or response `description` is derived from `http.HTTPStatus`/`http.client.responses` (413 and 422 text differs between 3.11 and 3.13+), so the document is identical when generated on 3.11 and 3.14. A function assignment, not a `FastAPI` subclass.

**The schema doesn't depend on `run_ui`.** This change adds `include_in_schema=False` to the SPA catch-all in `web/app.py`, which doesn't set it today. It's an HTML route, not an API operation, and leaving it in would put a `/{path}` GET operation (with an auto-422 the post-processor rewrites) into the schema served by default installs (`run_ui` defaults to `True`, `src/hassette/config/models.py`). Schema export and the freshness check build the app with `run_ui = False` (`scripts/schema_helpers.py`), so that operation would never be exercised in CI. A test pins that the generated OpenAPI document is identical with `run_ui` on (SPA directory present) and off. #2433 may restructure SPA serving later; this invariant holds under any of its candidate directions.

### D10: Does each route document which codes it can raise?

**Deciding factor:** a developer reading `/api/docs` can see an endpoint's possible codes, without schema tricks codegen mishandles.

| | A: `problem_responses(*codes)` on every route; each error status gets `x-problem-codes: [...]` listing every specific code that route can raise there | B: `ProblemDetail` schema only; per-route codes live only in the docs catalog | C: per-route `oneOf`/`allOf` narrowing of `code` |
|---|---|---|---|
| `/api/docs` shows per-route codes | yes | no | yes |
| Codegen | ignores `x-*` silently (verified, see Assumed) | n/a | `allOf` enum overrides don't narrow reliably; `oneOf` multiplies schemas |
| Maintenance | each route lists its codes, including shared-helper codes (`invalid_app_key` via `_validate_app_key`, `action_failed` on every action route), composed from constants kept next to the helpers that raise them; a test-time check fails when a route raises a code it doesn't list | none | high |
| Prior art | OAI issue #567 vendor-extension workaround; declare-plus-test-time-conformance is the practical norm for Python frameworks (Schemathesis `status_code_conformance`); AWS/Smithy's split of a service-wide common-error tier from operation-specific errors | Zalando, Stripe (catalog only) | rare; codegen support inconsistent |

**Recommendation:** A, because it serves the developer scenario at modest cost and the test-time check keeps it accurate.
**Pick B instead if** you'd rather not maintain per-route code lists and the catalog is enough.
**Reversibility:** easy
**Ratified:** Chose per-route `x-problem-codes` for operation-specific codes (global codes catalog-only), kept accurate by helper code constants and a test-time check, over catalog-only documentation, to achieve per-endpoint code visibility in `/api/docs`, accepting per-route code lists to maintain.

**Global codes are never listed per route:** `not_found`, `method_not_allowed`, `http_error`, `internal_error`, `not_authenticated`, `body_too_large`, and `validation_failed`. These come from routing, middleware, the fallback branch, or request validation (which D9 already documents as a 422 on every route with parameters), so any route can produce them. The catalog documents them once. Every other code is operation-specific and appears in `x-problem-codes` on exactly the routes that can raise it, 5xx codes included (`action_failed`, `source_unavailable`, `telemetry_unavailable`). This follows the AWS common-errors / operation-errors split (`design/research/2026-10-02-error-declaration-drift/research.md`).

**Keeping lists accurate:** each shared helper in `routes/apps.py` exports a tuple constant of the operation-specific codes it raises (e.g. the codes from `_validate_app_key`/`_require_known_app`), defined next to the helper. Routes compose their `problem_responses(...)` from those constants plus their own codes. A test-time check fails any test in which a route raises an operation-specific code missing from that operation's `x-problem-codes` for the raised status. It doesn't run in production. Global codes are exempt from the check. Deriving the lists from the AST (as fastapi-docx does) is not used: it's incomplete for dependency-injected and dynamically dispatched raises, and checks nothing.

`problem_responses()` groups codes by status and gives each status an explicit `description` with one clause per code, never derived from `http.HTTPStatus`. Routes that declare nothing today (`get_app_manifest`, `get_app_config`, `get_app_source`, logs, executions) get it too. The hand-written description-only `responses=` dicts in `routes/apps.py`, `auth.py`, `scheduler.py` are replaced; the success-model 503 declarations in `health.py` and `telemetry.py` are not.

### D11: How is "no bypassing the mechanism" enforced?

**Deciding factor:** runs on every CI leg.

| | A: pytest AST scan | B: `tools/check_*.py` prek hook |
|---|---|---|
| Runs on every CI leg | yes | only the lint job |
| Self-testable | yes | yes |

**Recommendation:** A.
**Pick B instead if** you want it to fail before commit rather than in tests.
**Reversibility:** easy
**Ratified:** Chose a pytest AST scan over a prek hook, to achieve enforcement on every CI leg, accepting it only fails at test time. (Carried; user decision.)

Behavior to pin: any module under `src/hassette/web/` other than `errors.py` that constructs an `HTTPException` (from `fastapi` or `starlette.exceptions`, in every import form: bare, aliased `from fastapi import HTTPException as E`, and module attribute access `fastapi.HTTPException(...)`) or builds a `{"detail": ...}` error body by hand fails it. The scanned set includes `web/app.py`, `web/middleware.py`, `web/body_limit.py`, and every `web/routes/*.py`. A second check fails if any `ProblemCode` member is missing from `docs/pages/web-ui/api-errors.md`.

### D12: How does it ship?

**Deciding factor:** external consumers see the break.

**Recommendation:** `feat!:` with exactly one `BREAKING CHANGE:` footer covering: the error content-type change, the 422 `detail` changing from a list to a string, and unknown `/api` paths returning 404 instead of 405 with the SPA served (D8). `CHANGELOG.md` isn't hand-edited.
**Pick otherwise if** never: every external client sees a content-type change.
**Reversibility:** easy
**Ratified:** Chose `feat!:` with one `BREAKING CHANGE:` footer, to achieve visible notice for external consumers, accepting a major-change changelog entry. (Carried; user decision.)

### D13: Do degraded-payload 503s become problem bodies?

**Deciding factor:** these are data, not errors, and the CLI already reads them as data.

| | A: unchanged success models | B: convert to problem bodies |
|---|---|---|
| Sites | `db_degrades_to` routes, the inline 503 in `routes/executions.py` (`LogsByExecutionResponse`), `/api/health/ready` (`ReadinessResponse`), `/api/telemetry/status` (`TelemetryStatusResponse`) | same |
| CLI (`tolerate_503`) and readiness contract | unchanged | broken |

**Recommendation:** A.
**Pick B instead if** never: the bodies are payloads callers render.
**Reversibility:** hard
**Ratified:** Chose to leave degraded-payload 503s as success models, to achieve unchanged readiness and CLI contracts, accepting that not every non-2xx `/api` response is a problem body. (Carried.)

### D14: What stability does the code set promise?

**Deciding factor:** clients can tell when a code change affects them, without a stability promise hassette doesn't make before 1.0.

| | A: codes follow the wire contract's pre-1.0 policy; any change other than an addition ships as a flagged breaking change | B: permanent add-only contract from first publish |
|---|---|---|
| Matches the rest of `hassette_wire` | yes: same treatment as removing a field | no: a stronger promise than any other wire type |
| Room to fix a bad code before 1.0 | yes, as a flagged break | no |
| Clients see breaks | yes: `feat!:`, `BREAKING CHANGE:` footer, `tools/wire_compat_ignore.txt` entry | n/a (no breaks allowed) |

**Recommendation:** A, because codes are wire contract like everything else in `hassette_wire`, and hassette promises no stability before 1.0.
**Pick B instead if** you want codes to be the one part of the wire contract that's frozen before 1.0.
**Reversibility:** easy (a policy statement)
**Ratified:** Chose the wire contract's pre-1.0 policy over a permanent add-only promise, to achieve room to fix codes before 1.0 while every break stays visible, accepting that clients get no stability guarantee before 1.0.

Behavior and wording:
- Renaming or removing a code, or changing a code's status in `CODE_STATUS`, is a breaking change. It ships as `feat!:` with a `BREAKING CHANGE:` footer, plus a `tools/wire_compat_ignore.txt` line if the wire-compat check flags it. Adding a new code instead of editing an existing one's status is the gentler path, recommended but not required.
- Adding a code is additive, like any new wire enum member. Clients using #2386's lenient parsing see an unknown code as `UNKNOWN`. Until that ships, a strict parser of `ProblemDetail` fails validation on a newly added code.
- The catalog page and the `.claude/rules/web-api.md` section state this: no stability guarantee before 1.0, how breaks are flagged, and that routing-error `detail` text is not stable.

## Assumed

- #2385 has landed: wire models live in `hassette_wire` and are imported from the package root. Evidence: PR #2449 merged 2026-09-30; `wire/src/hassette_wire/__init__.py`.
- New wire modules may import only the standard library, `pydantic`, and `hassette_wire`. Evidence: `wire/src/hassette_wire/REVIEW.md` ("Package Isolation").
- A new enum member is safe for old clients only through `hassette-client`'s lenient parsing, which #2386 builds (context-gated `UNKNOWN` on every wire enum). This change doesn't build it. Evidence: #2386 body and acceptance criteria; `tools/check_wire_compat.py` docstring (`response-property-enum-value-added` is allowed).
- `tools/check_wire_compat.py` (pre-push/CI) will flag this PR's deliberate breaks (error media types moving to `application/problem+json`, `HTTPValidationError` removed). Each reported line goes into `tools/wire_compat_ignore.txt` as its header describes. Evidence: `tools/check_wire_compat.py`, `tools/wire_compat_ignore.txt`.
- openapi-typescript (the repo's 7.13.0) emits `"application/problem+json": components["schemas"]["ProblemDetail"]` per response, renders `ProblemCode` as a string-literal union, and silently ignores `x-problem-codes`. Evidence: probe run on 2026-10-02 against a minimal document with this shape.
- No frontend code references `HTTPValidationError` or `paths` from the generated types, so removing those components is safe for the UI. Evidence: research §5.
- httpx and fetch `.json()` ignore content-type; aiohttp's `json()` accepts `application/(...+)?json`. Evidence: `aiohttp/client_reqrep.py:90`; research §5.
- `DefaultDenyMiddleware` counts auth failures by `response.status_code == 401`, so changing only the body keeps counting and rate limiting intact. Evidence: `src/hassette/web/middleware.py`.
- Starlette calls HTTP exception handlers for WebSocket scopes too. No WS route raises `HTTPException`, and returning a `Response` there is Starlette's documented denial path. Evidence: research §1.
- FastAPI passes extra keys in a `responses=` entry (e.g. `x-problem-codes`) into the OpenAPI response unchanged. Evidence: `fastapi/openapi/utils.py`; research §3.
- `tests/integration/web_api/test_endpoints.py` is over the 800-line file-size limit, so edits there must be line-neutral, and new coverage goes elsewhere. Evidence: `wc -l` (870 lines at research time); the `file-sizes` check.
- `tests/integration/web_api/test_body_limit.py` asserts the exact dict `{"detail": "Request body too large"}`, and that assertion must change. Every other error-status assertion in the suite checks status only. Evidence: research §4.
- The hassette-side mapping from code to HA translation key (`bootstrap_not_released` → `not_bootstrapped`, `app_blocked` → `blocked_by_filter`, `app_not_found` → `not_found`, `action_failed` → `action_failed`) lives in the `hass-hassette` repo, not here. Evidence: `design/specs/113-hacs-companion-integration/brief.md`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [ ] Ship-time challenge

**Calls made during the build:**

- The stop routes don't declare `bootstrap_not_released` or `app_blocked`: `stop_app`/`stop_instance` never await bootstrap release or check the `--app` filter, so listing those 409s would document an impossible response. The D1 cases for those two codes use start and reload.
- The hand-raised 422 rows (executions, logs) don't assert `x-problem-codes`: their code, `validation_failed`, is global under D10 and listed only in the catalog. D1's per-operation assertion applies to operation-specific codes.
- The FastAPI 400 row is triggered by a request body that isn't valid UTF-8: malformed JSON is FastAPI's own `json_invalid` validation error, so it returns `validation_failed` (422), not the 400.
- The helper code tuples (`APP_KEY_CODES`, `ACTION_CODES`, ...) sit at the top of `routes/apps.py`, each with a docstring naming its helper, not beside the helpers: house lint HSL004 requires module constants at the top.
- `STATUS_TITLES[418]` is "I'm a Teapot": RFC 9110 only marks 418 unused and gives no phrase.
- The test-time code check lives in `tests/support/problem_codes.py` and runs through an autouse fixture in `tests/integration/web_api/conftest.py`, which wraps the `HTTPException` handler before each test builds its app. It covers the web API integration tests, where routes are exercised.

## Addendum
