---
proposal: "Build hassette-client's async aiohttp transport (#2386): caller-owned session, explicit timeouts, typed exceptions mapped from status + ProblemCode, typed methods for 19 endpoint patterns, lenient parsing for version skew, and a cross-version CI job; port the CLI onto it."
date: 2026-10-02
status: Draft
flexibility: Exploring
motivation: "The HACS integration (hass-hassette, epic unit C) needs a typed client for hassette's API. The CLI should sit on the same shared typed transport. Version skew and wire breaks need to be safe."
constraints: "hassette is a framework with external callers. hassette, hassette-wire and hassette-client release in lockstep with exact pins. The client must fit HA conventions: injected aiohttp session, no blocking I/O, dependency floors compatible with HA core's pins."
non-goals: "WebSocket client (out of scope per spec 114). Server-side behavior changes beyond what lenient parsing needs in hassette_wire."
depth: deep
---

# Research Brief: hassette-client async transport, error mapping, and typed methods (#2386)

**Initiated by**: a request to research issue #2386 (milestone HACS v0.1). Exploring flexibility, open to splitting it into several PRs.

## Bottom line

#2386 is feasible and its blockers (#2382, #2385) are merged. It is four separable pieces of work with different risk. Split it into three PRs now and one later.

1. **A wire PR for lenient parsing.** This is the riskiest design piece, and the issue under-specifies it.
2. **A client-core PR.** Transport, exception hierarchy and the HA-path methods.
3. **A PR for the remaining CLI-path methods**, or fold them into #2387.
4. **The cross-version CI job, after the first client release that contains a transport.** Until that release exists, the job has nothing to install.

The CLI port is already its own issue (#2387, blocked by #2386). Keep it separate.

Three findings change the issue as written:

- **`UNKNOWN` leaks into public app-author API.** `ExecutionMode`, `BackpressurePolicy`, `ResourceStatus` and `ExecutionStatus` are re-exported from `hassette`. An `UNKNOWN` member would make `ExecutionMode("unknown")` succeed in user-input validation (`src/hassette/execution_mode.py:61`, `src/hassette/bus/listeners.py:128`). It would also appear in OpenAPI unless it's excluded.
- **Literals are on the HA path.** `SystemStatusResponse.status` (`SystemHealthStatus`) and `BootIssueResponse.severity` are `Literal`s returned by `get_health()`, which HA calls at setup. The AC only covers enums. Spec 116 deferred open-Literal handling to #2386 explicitly (`design/specs/116-wire-models-to-hassette-wire/design.md:37,184`).
- **"Raise on 503 regardless of body" conflicts with the degraded-payload design.** Most 503s are success-model bodies by design (spec 118 D13, `docs/pages/web-ui/api-errors.md`), and the CLI reads them as data through `tolerate_503`. The rule works if the exception carries the parsed partial body.

## Context

### What prompted this

The HA companion integration (epic #45, unit C, in its own repo) needs a typed async client. Its requirements are load-bearing:

- an injected session;
- typed errors that map to HA translation keys;
- a `get_health()` version check against `MIN_HASSETTE_VERSION`;
- surviving a newer server.

The CLI (#2387) is the second consumer. The HACS v0.1 milestone Done-when is: hass-hassette installs from a HACS custom repo, every app is a device, start/stop/reload are usable, and an end-to-end system test against a pinned hass-hassette release is green in CI.

### Current state

- **`hassette-client` is an empty shell.** `client/src/hassette_client/__init__.py` is a single docstring. `client/pyproject.toml` depends only on `hassette-wire==0.55.0`, and `client/tests/test_import.py` is its only test. Version 0.55.0 is published on PyPI, also empty.
- **`hassette-wire` holds every response model, with no leniency machinery** (Direct, from grep).
  - All models are plain `BaseModel`. None sets `extra=`, so pydantic's default `extra="ignore"` already ignores unknown fields.
  - None of the following exist: `_missing_`, `UNKNOWN`, validators, or context use.
  - There are 5 `StrEnum`s (`wire/src/hassette_wire/enums.py`), 7 named Literal aliases (`literals.py`), and inline Literals such as `BootIssueResponse.severity`.
  - The package docstring promises that "the client package's lenient parsing is what makes that direction safe" (`wire/src/hassette_wire/__init__.py:17`). That promise is not implemented yet.
- **`ProblemCode`** (`wire/src/hassette_wire/problems.py`) has 19 members. `ProblemDetail` has exactly five fields (`type`, `title`, `status`, `detail`, `code`), and spec 118 D2 fixes that set.
  - The code-to-status table is server-side only: `CODE_STATUS` in `src/hassette/web/errors.py:32-51`. `http_error` carries a variable status.
  - Retryability exists only as docstring and catalog prose for `bootstrap_not_released` ("Retry later") and `app_blocked` ("Retrying won't help").
  - Nothing sets `Retry-After`, although `WebApiError` accepts `headers` (`errors.py:167`).
- **Not every 503 is a problem body.**
  - `db_degrades_to` (`src/hassette/web/dependencies.py:125-137`) returns the endpoint's success model, usually empty, with a 503. So do the inline 503 in `routes/executions.py:76-79`, `/api/health/ready` and `/api/telemetry/status`.
  - Only `telemetry_unavailable`, raised by `GET /api/apps/{key}/manifest` (not in #2386's list), is a problem-body 503.
- **The existing CLI client** (`src/hassette/cli/client.py`, 704 lines) mixes three jobs:
  - a sync `httpx2` transport;
  - error rendering, which prints and calls `sys.exit(1|2)`;
  - `--app`/`--instance` routing.

  It defines no exception types, ignores `code`, and reads only `detail` (`client.py:554`). It does not follow redirects, because that is httpx's default, and its 3xx forward-auth hint depends on that (`client.py:560`). About 90 tests (`tests/unit/cli/test_client*.py`) are coupled to `httpx2.MockTransport` and `SystemExit` codes.
- **Auth.** A presented `Authorization` header decides alone and fails closed. Without one, the server falls back to `trusted_proxies` peer trust, then a session cookie (`src/hassette/web/auth/__init__.py:55-90`).
- **Wire-compat CI already exists in static form.** `tools/check_wire_compat.py` runs oasdiff in both skew directions against the last `v*` tag (`.github/workflows/tests.yml:125-134`, plus a pre-push hook). Its forward run deliberately downgrades `response-property-enum-value-added` because "hassette-client's lenient parsing owns" it (`tools/check_wire_compat.py:18-21`). Until #2386 lands, that downgrade covers a hazard nothing actually handles.
- **Root already depends on aiohttp.** The root package has `aiohttp>=3.14.3` (`pyproject.toml:37`, a CVE-driven floor) and uses it in core and testing (`src/hassette/testing/_server.py`). The lock resolves pydantic 2.12.3. The wire floor is `pydantic>=2.7`.

### Key constraints

- **HA pins** (Direct, verified in `~/source/core` at tag 2026.9.4, which matches `codegen/ha-version.txt`):
  - `aiohttp==3.14.3` and `pydantic==2.13.4` (`homeassistant/package_constraints.txt:9,144`);
  - `yarl==1.24.5`, `async-timeout==4.0.3`, `packaging>=23.1`.

  The issue cites 2026.9.2. The aiohttp and pydantic pins are unchanged at 2026.9.4.
- **HA quality scale.** `inject-websession` is Platinum: the library accepts a caller-supplied `aiohttp` or `httpx` session. `async-dependency` and `strict-typing` are also Platinum, and `dependency-transparency` is Bronze (`script/hassfest/quality_scale.py:44,92-94`). Integrations pass `async_get_clientsession(hass)`, as hue, nextdns and tailscale do. The rule allows a dedicated session via `async_create_clientsession` when cookies are needed ([HA docs](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/inject-websession)).
- **Boundary rule.** `hassette_client` must not import `hassette` (spec 114; `check_module_boundaries.py`). So client tests can't use the root's FastAPI test harness. Running the client against the real server has to happen in root `tests/`.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|---|---|---|---|
| Lenient parsing in wire | `wire/src/hassette_wire/{enums,literals,problems,health}.py`, a new lenient helper module, wire tests | Med | **High.** Touches enums that are public app-author API and the committed OpenAPI/TS schemas. |
| Guard user-input enum construction | `src/hassette/execution_mode.py:61`, `src/hassette/bus/listeners.py:128` | Low | Med. `ExecutionMode("unknown")` must keep failing. |
| Transport + exceptions | new `client/src/hassette_client/{transport,errors}.py` | Med | Med. aiohttp defaults differ from httpx: redirects, content-type checks, timeouts. |
| Typed methods | new `client/src/hassette_client/client.py`; 19 patterns / 23 routes | Low–Med | Low. The methods are thin over wire models. |
| Client test infra | `client/pyproject.toml` dev group (pytest-asyncio, aiohttp test server), `ruff.toml` client-test ignores | Low | Low. `client/tests/**` only ignores S101 today (`ruff.toml:135`). |
| Real-server integration test | root `tests/integration/` using `tests/support/uvicorn.py:start_uvicorn_server` | Low–Med | Low |
| Deps | `client/pyproject.toml` (`aiohttp`, possibly `packaging`) | Low | Low, provided client floors are decoupled from the root's CVE floor. |
| Cross-version CI | new nox session + job in `tests.yml`; isolated venv like `noxfile.py:wheel_smoke` | Med | Med. Has nothing to exercise until a client with a transport is released. |
| CLI port (#2387, separate) | `src/hassette/cli/client.py`, `target.py`, ~15 `make_client` sites in 6 command modules, ~90 tests rewritten | High | High. Exit codes, redirects, timeouts, unclosed sessions, import time. |

### What already supports this

- **The models already exist and are shared.** Typed methods are thin wrappers, and nothing needs generating. Spec 114 rejected generated models (`design/specs/114-hassette-client/brief.md`, "Version skew" and layout sections).
- **`ProblemCode` is a closed `StrEnum` with one status per code**, so a code-keyed exception registry plus an exhaustiveness test is straightforward.
- **Every route declares its codes** through `problem_responses()`, which writes `x-problem-codes` into `frontend/openapi.json`. The committed schema can drive a coverage test: every operation has a client method or an explicit exemption, and every declared code maps to a typed exception.
- **`extra="ignore"` is already the default**, so half of "lenient parsing" only needs a guard test.
- **The CLI is already the caller-owned-session shape.** It runs one sync command per process, so `asyncio.run` with an `async with ClientSession()` per command satisfies "caller-owned" without a convenience constructor in the client.
- **The test and CI building blocks exist.** There is a pattern for isolated-venv installs (`noxfile.py:75-110`, `wheel_smoke`), a real-socket server helper (`tests/support/uvicorn.py`), and deterministic seeded DBs (`scripts/seed_db.py`).

### What works against this

- **`UNKNOWN` as a real enum member conflicts with spec 116's "one definition" decision.** The wire enums *are* the public `hassette.ExecutionMode` and friends. Spec 116 rules out mirror enums (`design.md:133`).
- **Literal aliases can't take an `UNKNOWN` member.** Spec 116 kept them as Literals to keep `openapi.json` byte-identical and said that converting them later "stays cheap" (`design.md:184`).
- **Exhaustive `match` statements in core** use `assert_never`, for example on `source_tier` (`src/hassette/core/telemetry/summary_queries.py:148-159`, `helpers.py:139-146`). Widening a wire type means the server code that matches on it has to handle the new case.
- **The 503 semantics are endpoint-specific**, so a single status rule doesn't fit them all (see the 503 decision under Q3).

## Options Evaluated: delivery shape

### Option A: Split into verifiable PRs (recommended shape)

**How it works**: four PRs in order. Each ends in a checkable state.

1. **PR 1, wire lenient parsing (`hassette-wire`).**
   - One context-gated fallback mechanism, defined once in wire, for all response-path enums, `ProblemCode`, and the open Literals.
   - A public constant or helper for the context.
   - JSON-schema exclusion, so `frontend/openapi.json` and the TS types stay byte-identical.
   - Explicit rejection of the fallback at the two user-input constructors.
   - A guard test that no wire model sets `extra="forbid"`.
   - **Verifiable by:** the schema-freshness check showing no diff (`tools/check_schemas_fresh.py`); wire tests showing strict mode rejects a novel value and lenient mode accepts it; and the existing hassette suite staying green.
2. **PR 2, client core.**
   - Transport, exception hierarchy, the code-to-exception registry, and the exhaustiveness test.
   - `get_health()` and a "server newer" signal.
   - The HA-path methods: `get_health`, `get_app_manifests`, and app `start`/`stop`/`reload`, optionally with the instance variants.
   - Dependency floors and test infrastructure.
   - A root integration test that runs the client against the real FastAPI app over a socket.
   - **Verifiable by** client unit tests against `aiohttp.test_utils.TestServer` fakes (HTTP is the boundary) plus the real-server test.
3. **PR 3, the remaining 14 CLI-path methods**, plus an OpenAPI coverage test (every operation in `frontend/openapi.json` is a client method or an exemption, and each `x-problem-codes` entry resolves). This could fold into #2387 so that each method lands with its first consumer.
4. **PR 4, the cross-version CI job**, after the first release whose `hassette-client` has a transport.

**Pros**
- The riskiest decision, enum and Literal representation, lands alone. Its pin is "the schemas didn't change", and that check already exists.
- HA's critical path (PR 1 and PR 2) can ship and release first, which unblocks unit C sooner.
- Each PR stays well under the file-size and `duplicate-code` gates.
- No CI job ships before it has anything to install.

**Cons**
- More PRs to choreograph. Because of lockstep releases, PR 1 and PR 2 should go out in the same release train.
- The issue's ACs span the PRs, so the issue needs to be re-scoped or split into sub-issues.

**Effort estimate**: Medium overall. PR 1 is Medium because of the design spike, PR 2 is Medium, PR 3 is Small–Medium, PR 4 is Medium.

**Dependencies**: `aiohttp` (client runtime), `pytest-asyncio` (client dev), and possibly `packaging` (version comparison; HA constrains `packaging>=23.1`).

### Option B: One PR as the issue is written

**How it works**: implement every AC in one branch, including the cross-version job.

**Pros**
- Matches the issue and the spec 114 work-split table (row 4) one-to-one, with no re-scoping.

**Cons**
- A large diff that mixes a public-API-adjacent wire change with new-package code.
- **The cross-version job is untestable at merge time.** The latest released client (0.55.0) is empty, so the job either installs nothing meaningful or has to be written against an API that doesn't exist on PyPI yet.
- It delays HA's path behind 14 methods that unit C doesn't call.

**Effort estimate**: Large.

**Dependencies**: same as Option A.

### Option C: Do less for HACS v0.1

**How it works**:

1. **Lenient parsing only on the HA path.** Cover `ProblemCode`, `ManifestStatus`, `ResourceStatus`, `SystemHealthStatus` and `BootIssueResponse.severity`.
2. **Transport, exceptions and about 5 HA methods.**
3. **Defer the CLI-only methods to #2387**, where each lands with its consumer.
4. **Defer the behavioral cross-version job** and rely on two things:
   - the existing oasdiff check, which already covers old-client/new-server for everything except enum and Literal additions;
   - the milestone's pinned hass-hassette system test (epic unit D), which is the same old-client/new-server direction with the real consumer.

**Pros**
- Smallest path to the Done-when.
- Every shipped method has a consumer.
- No speculative CI.

**Cons**
- The issue says "the client covers the whole API". The framework principle in `CLAUDE.md` ("in-repo usage is not evidence of demand") argues against shipping a partial client for external callers.
- Leniency on only some enums is a trap. The next model added to the HA path silently needs it too, unless the mechanism is general and only the *application* is staged.
- Unit D's system test catches skew later (at release) and for fewer endpoints than a PR-time job would.

**Effort estimate**: Small–Medium.

**Dependencies**: same as Option A.

**Note**: Option C's "defer methods" part is consistent with the issue's own reasoning: "Being 0.x and released in lockstep... adding or adjusting typed methods later doesn't freeze anything". Its "partial leniency" part is the weak half. Build the mechanism generally even if you take the rest of C.

## Design decisions by key question

### Q1. Where retryability lives

**Prior art** (Supported, from fetched source):

- **HA client libraries encode semantics in exception types and carry no retry metadata.**
  - python-matter-server keys exceptions by `error_code`, using an `ERROR_MAP` populated in `__init_subclass__`. `exception_from_error_code()` falls back to the base `MatterError`.
  - zwave-js-server-python splits `TransportError` (`CannotConnect`, `ConnectionFailed`) from `FailedCommand(error_code)` and has a separate `InvalidServerVersion`.
  - aioesphomeapi roots everything at `APIConnectionError`, with `InvalidAuthAPIError` and `TimeoutAPIError` among its subclasses.
  - None of the three has a retryable flag.
- **Retryability is a client-side policy keyed on codes.** gRPC and Google AIP-194 define retryable status codes in the client: UNAVAILABLE retries, INVALID_ARGUMENT doesn't.
- **Server-signaled retry is the exception.** Stripe's `Stripe-Should-Retry` header and HTTP's standard `Retry-After` are examples. RFC 9457 defines no retry member.
- **In HA, the integration does not retry in the client.** Spec 113 maps `bootstrap_not_released` to `HomeAssistantError(not_bootstrapped)` and `app_blocked` to `ServiceValidationError(blocked_by_filter)`. HA's machinery (coordinator polling, entry retry) does the retrying. What unit C needs is *classification*, and distinct exception types already provide it.

| Option | Pros | Cons |
|---|---|---|
| (a) `RETRYABLE_CODES` frozenset, or a per-code attribute, in `hassette_wire` | One authoritative list next to the codes | New contract surface (changing it is semantically breaking under spec 118 D14). Doesn't help an old client meeting a new code, because its copy of the set is old. The server never reads it. |
| (b) `ProblemDetail.retryable: bool`, or a `Retry-After` header | Server-signaled, so it works for codes the client doesn't know | Reopens spec 118 D2 ("exactly five members"). Needs a default per the skew rule. No consumer needs it yet. |
| (c) Class attribute on client exceptions (`retryable: ClassVar[bool]`), set per typed exception | No wire change. One place. Generic consumers can branch without a catalog. Matches prior art (client-owned classification). | Retryability of an *unknown* code is unknowable. Fall back by status: 503 retryable, other 4xx not. |
| (d) Encode it in the hierarchy (`RetryableError` mixin base) | `except RetryableError` reads well | Collides with the status-based hierarchy (a 409 can be either), so it needs multiple inheritance. More reader load than (c) for the same information. |

**Recommendation (Inferred)**: (c). Leave the wire contract alone and answer the #2386 comment with "left to the client". If the server ever wants to signal retry dynamically, use the standard `Retry-After` header through the existing `WebApiError(headers=...)` rather than a `ProblemDetail` member. That is additive and needs no model change.

Spec 113 shows no current consumer that needs a retry loop. Per the `feedback_prior-art-backed-decisions` memory, this rationale rests on the prior art above. No `design/research/` doc covers retry, so if the decision should be durable, record it in the spec or a short research note.

### Q2. Lenient parsing and version skew

**What exists**: the `extra="ignore"` default, and no enum leniency. The forward oasdiff run assumes leniency exists. Fields on the HA path that need it:

- `ProblemDetail.code`;
- `AppManifestResponse.status` (`ManifestStatus`);
- `instances[].status` and `services[].status` (`ResourceStatus`);
- `SystemStatusResponse.status` (`SystemHealthStatus` Literal);
- `boot_issues[].severity` (inline Literal).

**The gating mechanism** (Inferred; prototype it before committing):

- A pydantic validation context reaches validators through `info.context` ([pydantic validators docs](https://pydantic.dev/docs/validation/latest/concepts/validators/)). The docs don't state that context propagates into nested models. My understanding is that it does, because context is per-validation-call state, but **confirm it with a spike** on `list[AppManifestResponse]` and the `TypeAdapter` paths.
- A context-gated fallback has to be a wrap validator. Defining it once as `__get_pydantic_core_schema__` on a wire `StrEnum` base, using `core_schema.with_info_wrap_validator_function`, applies it to every field typed with that enum. Alternatively, it can go in an `Annotated[..., WrapValidator(...)]` alias per Literal.
- `Enum._missing_` can't see the context, so it would make `UNKNOWN` acceptance unconditional. That would affect server-side DB-to-model parsing and `ExecutionMode(mode)` user input. Avoid `_missing_`.
- Exclude the fallback from JSON schema with `__get_pydantic_json_schema__`. Otherwise `openapi.json`, the generated TS types and oasdiff all change.

**How unknown values are represented**:

| Option | How | Pros | Cons |
|---|---|---|---|
| L1: `UNKNOWN` member (the issue's plan) | Each wire StrEnum gets `UNKNOWN = "unknown"`, which validates only under the context. Open Literals are converted to StrEnums so they can take it too. | Keeps narrowing (`match status: case ManifestStatus.UNKNOWN`). Matches spec 114. Consumers get the "explicit unknown option" spec 114 asks for. | `UNKNOWN` becomes visible in the public `hassette.ExecutionMode`, `ResourceStatus` and so on (iteration, `ExecutionMode("unknown")`, the "must be one of" error text). It needs explicit rejection at `execution_mode.py:61` and `bus/listeners.py:128` and an exclusion from JSON schema. The raw unknown value is lost, which makes logging "server sent 'paused'" impossible. Converting Literals revisits spec 116 §"Literal wire fields". |
| L2: open union keeping the raw value (Stripe `Literal[...] \| str`, protobuf open enums; cited as Pattern 4 in `design/research/2026-09-25-shared-wire-models/research.md:36-40`) | Lenient-only fallback to a small wire type such as `UnknownValue(str)` that carries the raw string. Annotations become `ManifestStatus \| UnknownValue`. | Public enums stay closed. The raw value is preserved for logs. Literals need no conversion. | The type of every affected wire field widens, on the server too. Spec 116 put server and client on the same model classes, so server code that reads these fields must narrow. JSON-schema override needed. Consumers lose plain enum narrowing. |
| L3: separate lenient model set in the client | Mirror models with open types | Server untouched | Spec 114 rejected this explicitly ("two model sets"). Drift-prone. |
| L4: `_missing_` returning `UNKNOWN` unconditionally | Simplest | Ungated. Server-side parsing and user input would silently accept garbage. Fails the issue's "server never does" AC. |

**Recommendation (Inferred, needs the user's call)**: L1 for the StrEnums, with three mitigations: JSON-schema exclusion, rejection at the user-input constructors, and docs noting that `UNKNOWN` is client-only. For open Literals on response paths, the choice is between converting them to StrEnums (cheap per spec 116) and an L2-style alias.

L1 matches the ratified spec 114 and gives consumers the cleanest code. Its real cost is the public-enum leakage, which is a deliberate public-API change for app authors and needs a changelog entry. If that leakage is unacceptable, L2 is the principled alternative.

Either way:

- Put the gating mechanism in one place in wire.
- Expose one context constant or helper that the client applies to every parse, including `TypeAdapter` for list responses and the `ProblemDetail` parse on error bodies.
- Test that strict mode, used by the server, is unchanged.

**Pydantic floor**: wrap validators and validation context exist throughout pydantic 2.x, so `pydantic>=2.7` is plausible. No job tests at the floor, though. Add `uv run --resolution lowest-direct` for the wire and client sessions; it's a cheap guard that HA's 2.13.4 and the declared floor both work.

**Non-additive changes** (rename, retype, missing required field) still raise. The transport wraps `pydantic.ValidationError` into a client `ResponseValidationError` that carries the endpoint and model name, never the payload values.

### Q3. Transport shape

**Session and requests**:

- The constructor takes `session: aiohttp.ClientSession`, `base_url`, an optional `token` and a timeout. The client never creates or closes a session. Omit the header entirely when there's no token.
- Pass a per-request `aiohttp.ClientTimeout`.
- Set `allow_redirects=False`. aiohttp follows redirects by default; httpx doesn't. Following them would silently swallow the forward-auth redirect that the CLI turns into a hint (`client.py:560`).
- Read bodies explicitly and branch on content type. A non-problem error body, such as a proxy's 502 HTML page, maps by status alone, with the raw text truncated.
- Leave TLS to the caller's session. HA's `async_get_clientsession(hass, verify_ssl=...)` and the CLI's own connector own it.

**Exceptions**: `HassetteClientError` is the base.

- `HassetteConnectionError` wraps `aiohttp.ClientConnectionError`.
- `HassetteTimeoutError` wraps `asyncio.TimeoutError`.
- `ResponseValidationError` covers non-additive schema changes.
- `HassetteHTTPError(status, problem: ProblemDetail | None)` has status-family subclasses: `AuthenticationError` (401), `NotFoundError` (404), `ConflictError` (409), `InvalidRequestError` (400/422), `ServerError` (5xx) and `ServiceUnavailableError` (503).
- Code subclasses carry a `code: ClassVar[ProblemCode]`:
  - `AppNotFoundError` and `InstanceNotFoundError` under `NotFoundError`;
  - `BootstrapNotReleasedError`, `AppBlockedError` and `JobNotRegisteredError` under `ConflictError`;
  - `InvalidAppKeyError`;
  - `ActionFailedError`.
- A registry filled through `__init_subclass__` resolves a code to its class, then a status to its family class, then falls back to `HassetteHTTPError`. This is the python-matter-server pattern.
- The AC test iterates `ProblemCode` and asserts that every member maps to a specific class or is in an explicit `GENERIC_CODES` set (`http_error`, `internal_error`, `not_found`, `method_not_allowed`, `UNKNOWN`, ...). A new server code then fails the test until someone decides how to surface it.
- This hierarchy lines up with spec 113's mapping to HA `translation_key`s with no gaps.

**503 decision** (the one with real semantics):

- Raise `ServiceUnavailableError` on every 503, as the issue says. When the body parses as the endpoint's success model, attach it as `.partial`.
- HA's manifests poll then treats 503 as `UpdateFailed` ("never counts as apps removed").
- The CLI keeps today's `tolerate_503` behavior by catching the exception and rendering `.partial`.
- The alternative is a per-method `allow_degraded` flag that returns the body. It has the same power but two code paths and a weaker guarantee for HA.
- `/api/telemetry/status` is the awkward case: there, a 503 *is* the answer (`degraded=True`). That's an open question below.

**Methods**: one flat `HassetteClient` class of thin methods, with transport mechanics in a separate module. 23 one-to-five-line methods fit under the 800-line cap.

- The alternative is per-resource sub-clients (`client.apps.start(key)`, `client.telemetry.app_health(key)`, as aiogithubapi does). That mirrors the URL tree but adds a layer.
- Frenck-style HA libraries such as elgato and tailscale are flat. **Recommend flat**, and split by resource only if the file grows past about 400 lines.
- Expose a single `action(app_key, action, *, instance=None)` that dispatches to the three literal routes. Note that no `{action}` path parameter exists server-side (`routes/apps.py:342-418`).

**Generate or hand-write**: hand-write. The models are already shared (spec 114 rejected generated models), and 23 thin methods don't justify a generator ("Build the Lever": the transform doesn't repeat). Do use `frontend/openapi.json`, which the freshness check keeps current (`tools/check_schemas_fresh.py`, `tests.yml:92-96`), as a **test oracle**: a coverage test enumerates operations and `x-problem-codes`. That catches a new route or code the client hasn't covered, at PR time.

**Version signal**: `get_health()` returns `SystemStatusResponse`, whose `version` field defaults to `""` (`wire/src/hassette_wire/health.py:39`). The server may also send `"unknown"` (`utils/version_utils.py:9-14`).

- Expose something like `server_is_newer(health) -> bool | None` that compares against `importlib.metadata.version("hassette-wire")`, which equals the client version under lockstep.
- Return `None` for unparseable versions instead of guessing `False`.
- Comparing PEP 440 versions properly wants `packaging`. Its floor must stay at or below HA's constraint (`packaging>=23.1`).

### Q4. CLI port

- **It's #2387, not #2386.** #2386 lists #2387 as blocked by it.
- **What the CLI is today** (Direct): sync `httpx2`, no exception types, `sys.exit` inside the client, `detail`-only error parsing, ~15 `make_client` call sites in 6 command modules, and ~450 CLI unit tests. About 90 of those tests (`test_client.py`, `test_client_credentials.py`) are bound to `httpx2.MockTransport` and `SystemExit` codes.
- **What #2387 already includes**: the `target.py` credential split and DI (#1877). Those are larger than the transport swap.
- **Regressions to guard in #2387** (Inferred from code reading):
  - the exit-code 1/2 split (HTTP vs network), which must map from the new exception families;
  - redirect following;
  - aiohttp `ContentTypeError` on non-JSON bodies;
  - scalar `timeout=10.0` vs `ClientTimeout` semantics;
  - "Unclosed client session" warnings, which make session closing mandatory;
  - `--no-verify-ssl`, which moves to the CLI's connector;
  - the import-time cost of aiohttp against #1540's startup goal.
- **Recommendation**: keep it a separate PR. PR 2 should still include one real-server integration test from root `tests/`, so the transport is proven against the actual FastAPI app before #2387 depends on it.

### Q5. Cross-version CI

**What "cross-version" means under lockstep**: the released client N against HEAD, the N+1 server candidate. That is the old-client/new-server direction HA lives in: the integration's client range lags behind a user who upgrades hassette. The reverse direction (new client, old server) is covered by the optional-new-fields rule and oasdiff's reversed run.

**What it adds over oasdiff** (Inferred): oasdiff compares schemas. A behavioral job also catches:

- serialization changes that are invisible in the schema, such as datetime formats or custom serializers;
- bugs in the released client's leniency implementation;
- error-mapping drift, such as a code's status changing, where oasdiff's coverage of the `x-problem-codes` extension is unverified.

**Blocker**: the latest released client (0.55.0) has no transport. The job has nothing to exercise until the release after PR 2.

**Designs, cheapest first**:

1. **Response replay** (recommended first cut).
   - HEAD writes golden response fixtures per endpoint: success bodies from a seeded scenario (`scripts/seed_db.py`), plus representative problem bodies.
   - An isolated venv installs `hassette-client==<latest PyPI>` and validates each fixture through the client's public parse entry point.
   - No server boot and no ports. It tests the stated failure condition: "a wire response no longer parses".
   - It needs PR 2 to expose a stable public parse function, such as `hassette_client.parse_response(model, payload)`, which is cheap to decide now.
2. **Live server**. Boot HEAD's app with `tests/support/uvicorn.py:start_uvicorn_server` and a seeded DB, then run a smoke script from the isolated venv as a subprocess against the port.
   - It covers error mapping end to end.
   - Costs: two environments, port management, and seeded data rich enough that lists aren't trivially empty. A script written against the old client's API also breaks when method signatures change, which is arguably a valid signal.

**Path filter**: gate on `wire/**` *and* `src/hassette/web/**`. Route serialization changes can break responses without touching wire. `tests.yml`'s `changes` job has no wire-only output today, so this needs a new filter output.

**Recommendation**: ship it as PR 4 after the first transport-bearing release, starting with response replay. For the HACS v0.1 Done-when it's optional: unit D's pinned hass-hassette system test covers the same direction with the real consumer, at release time instead of PR time.

### Q6. Split and ordering

Option A's ordering is: PR 1 (wire leniency) → PR 2 (client core and HA methods, released together with PR 1) → PR 3 (remaining methods, or fold into #2387) → #2387 (CLI port) → PR 4 (cross-version job, after a release with PR 2). Option C is the do-less variant.

## Concerns

### Technical risks

- **Public-enum leakage under L1.**
  - `ExecutionMode("unknown")` would construct successfully (`execution_mode.py:61`, `bus/listeners.py:128`).
  - The "must be one of" messages would list `unknown`.
  - App-author code doing an exhaustive `match` on `ResourceStatus` gains a member.
  - This is a framework public-API change, and its callers are external.
- **Schema drift.** If JSON-schema exclusion is missed, `frontend/openapi.json`, the generated TS unions and the oasdiff baselines all change. Use the freshness check as the PR 1 pin.
- **Pydantic context propagation is unverified.** Context reaching nested models and `TypeAdapter(list[...])` is expected but not confirmed from docs. Spike first.
- **aiohttp defaults.** Redirect following, the content-type check in `resp.json()`, and `ClientTimeout` semantics differ from httpx. Write tests for 3xx, `application/problem+json`, `text/html` 502, and an empty 503.
- **The aiohttp floor coupled to the root's CVE floor.** Root's `aiohttp>=3.14.3` equals HA's pin today. If the root bumps it for a future CVE and the client copies that bump, installing into HA conflicts. Keep the client floor independent and tested against HA's pin.
- **`http_error` has no fixed status.** The registry must fall back by status, not assume one.

### Complexity risks

- **The fallback mechanism must not fork.** One gating mechanism must cover StrEnums, Literals and `ProblemCode`. Three ad-hoc ones would multiply reader load.
- **Exception taxonomy sprawl.** About 15 classes. Keep them in one module, with the registry as the single source of truth for code-to-class mapping.

### Maintenance risks

- **Every new `ProblemCode` now has three touchpoints**: server `CODE_STATUS`, the docs catalog, and the client registry. The exhaustiveness test enforces the client one. Document it in `.claude/rules/web-api.md`'s "adding a code" list.
- **Every new route needs a client method or an exemption**, which the OpenAPI coverage test enforces.
- **The cross-version job's fixtures must be regenerated** when scenarios change. Generate them in CI rather than committing them, to avoid drift.

## Open Questions

- [ ] **Enum representation**: accept `UNKNOWN` as a visible member of public app-author enums (L1), or use an open union that keeps the raw value (L2)? This is a product and API call that code can't settle.
- [ ] **Open Literals on response paths**: convert them to StrEnums (revisiting spec 116 §"Literal wire fields"), or use a lenient Literal alias?
- [ ] **`/api/telemetry/status` on 503**: raise `ServiceUnavailableError(partial=...)` like every other 503, or return the `degraded=True` body? `/api/health/ready` is not in the method list. Should it be?
- [ ] **Scope**: should #2386 still ship all 19 patterns, or should the CLI-only ones move into #2387 so each lands with a consumer? The issue's "covers the whole API" and the framework principle point one way; Option C points the other.
- [ ] **Cross-version job**: required for HACS v0.1, or deferred to after the first transport release, with oasdiff and unit D's system test covering v0.1?
- [ ] **`packaging` as a runtime dependency** for `server_is_newer`, or a hand-rolled comparison that returns `None` on anything that isn't simple `X.Y.Z`?
- [ ] **Unknown, not found**: whether pydantic-core calls `Enum._missing_` with any validation info. I found no doc stating it does and inferred that it doesn't. The spike should confirm.
- [ ] **Unknown**: whether oasdiff 1.32.1 diffs the `x-problem-codes` extension at all. I didn't read the oasdiff rules. This decides whether error-code drift is already caught statically.

## Recommendation

Take **Option A**, and apply Option C's discipline to methods if the user wants HACS v0.1 sooner.

1. Answer the #2386 retryability comment with **client-side classification** (`retryable` class attribute, status fallback, no wire change). This is Supported by the HA client-library prior art and the fact that unit C doesn't retry in the client.
2. **Spike the lenient mechanism before writing PR 1** (half a day):
   - a context-gated wrap validator on a StrEnum base and on a Literal alias;
   - nested and `TypeAdapter` propagation;
   - JSON-schema exclusion, with `openapi.json` unchanged.

   Use the spike to make the L1/L2 call with real code in hand.
3. Build the client core with a code-keyed exception registry, `allow_redirects=False`, explicit `ClientTimeout`, 503-with-`.partial`, and a public parse entry point that the later cross-version job can reuse.
4. Keep the CLI port in #2387. Defer the behavioral cross-version job until a release contains the transport, and make its first version a response-replay check.

Confidence: the code facts are Direct (file:line above). The prior-art claims about retry are Supported. The pydantic mechanics and the CI design are Inferred and should be validated by the spike.

### Suggested next steps

1. Run the lenient-parsing spike in a scratch branch, then decide L1 vs L2 and the Literal handling.
2. Re-scope #2386 into sub-issues (wire leniency, client core, remaining methods, cross-version job) or edit its AC. Fix two things in the issue body while doing so: the HA version cite (2026.9.4 is the current codegen target) and the "503 regardless of body" wording, which should say "carrying the partial body".
3. Write the design doc via `/mine-define` for PR 1 and PR 2. Include the exception taxonomy table mapped to spec 113's `translation_key`s.
4. Add `lowest-direct` resolution runs for the wire and client nox sessions.

## Sources

- [HA quality scale: inject-websession](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/inject-websession)
- [HA quality scale rules index](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules)
- [python-matter-server errors.py](https://raw.githubusercontent.com/home-assistant-libs/python-matter-server/main/matter_server/common/errors.py) (code-keyed `ERROR_MAP` registry)
- [zwave-js-server-python exceptions.py](https://raw.githubusercontent.com/home-assistant-libs/zwave-js-server-python/master/zwave_js_server/exceptions.py)
- [aioesphomeapi core.py](https://raw.githubusercontent.com/esphome/aioesphomeapi/main/aioesphomeapi/core.py)
- [Google AIP-194: automatic retry configuration](https://google.aip.dev/194)
- [Stripe low-level error handling (Stripe-Should-Retry)](https://docs.stripe.com/error-low-level)
- [Pydantic validators and validation context](https://pydantic.dev/docs/validation/latest/concepts/validators/)
- [fbenum (pydantic enum fallback prior art)](https://github.com/vadim-su/fbenum)
- [Python API clients: generated vs hand-written](https://scour.ing/@minezone/p/https://paulwrites.software/articles/python-api-clients)
- In-repo prior art: `design/research/2026-09-25-shared-wire-models/research.md` (open enums: Stripe and protobuf), `design/specs/114-hassette-client/brief.md`, `design/specs/113-hacs-companion-integration/brief.md`, `design/specs/116-wire-models-to-hassette-wire/design.md`, `design/specs/118-api-problem-details/design.md`

## Decisions (2026-10-02)

These resolve the Open Questions above. They were made with the user after the brief was written.

1. **Enum representation: L1.** Each wire StrEnum gets an `UNKNOWN` member that validates only under the client's lenient context. Mitigations:
   - exclude it from the JSON schema;
   - reject it at every `ExecutionMode` and `BackpressurePolicy` input boundary, whether it arrives as a string or as an enum member. Each enum gets one shared coercion helper that rejects `UNKNOWN`, and every registration path calls it: `resolve_execution_mode` (`execution_mode.py:58`, which also serves the scheduler), `ListenerOptions.__post_init__` (`bus/listeners.py:125-138`), and the backpressure coercion in `bus/bus.py:655-662` (which duplicates the one in `listeners.py`). Today those sites return early on an enum instance. An `UNKNOWN` that got through would fall back silently: `ExecutionModeGuard` treats it as `queued`, and `bus_service.py:454` treats it as `BLOCK`;
   - add a changelog entry for the public-enum change.
2. **Open Literals on response paths are converted to StrEnums**, so one leniency mechanism covers everything. This needs an addendum to spec 116 §"Literal wire fields".
3. **Degraded 503s follow convention**, per `design/research/2026-10-02-degraded-503-handling/research.md`.
   - **Server:** the `db_degrades_to` routes (and the inline variant in `executions.py`) return a 503 problem+json `telemetry_unavailable`, matching `get_app_manifest`. This ships as its own PR before the client, with an addendum reversing spec 118 D13 and a changelog entry.
   - **Client:** `get_ready()` and `get_telemetry_status()` return their status model on 200 or 503. Every other non-2xx raises. Drop `.partial` from the design.
   - **`/api/health/ready` gets a client method.**
4. **Scope:** every route gets a typed method under #2386 (client core plus the HA methods first, then the rest in a follow-up PR). The OpenAPI coverage test ships with no route exemptions. #2387 only ports the CLI.
5. **Cross-version CI job is required for HACS v0.1.** It starts with response replay and lands right after the first release that includes the transport. The client PR exposes a stable public parse entry point for the job to call.
6. **`packaging` becomes a runtime dependency** for `server_is_newer()`, with a floor at or below HA's (`>=23.1`). The helper returns `None` on `InvalidVersion`, `"unknown"`, or `""`. AwesomeVersion, which HA core uses far more, was considered and rejected. Our versions are always PEP 440 because they are our own package versions. HA pins `awesomeversion` exactly but leaves `packaging` loose, and the root package already depends on `packaging`.

Revised PR order:
1. Server degraded-503 → problem+json.
2. Wire leniency (the `UNKNOWN` mechanism and the Literal→StrEnum conversion).
3. Client core plus the HA methods.
4. The remaining methods.
5. Release.
6. Cross-version CI job.

#2387 (the CLI port) can follow PR 4.

Items 1 and 2 still need the pydantic spike: does the validation context reach nested models and `TypeAdapter(list[...])`, and does `openapi.json` stay byte-identical?
