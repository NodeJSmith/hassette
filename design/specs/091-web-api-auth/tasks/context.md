# Context: Web API Authentication and Safe Default Bind

## Problem & Motivation

Hassette's web API has no authentication of any kind. Mutation endpoints (start/stop/reload an app,
trigger a scheduled job, change log level), source-disclosure endpoints (`/source`, `/config`), and
the WebSocket feed are all reachable by any network peer that can reach the port — which, on the
default `0.0.0.0` bind, is anyone on the same LAN, Docker bridge network, or (for a VPS deployment)
potentially the wider internet. Hassette holds a long-lived, typically full-admin Home Assistant
token, so an unauthenticated peer can force hassette to execute the operator's own automation code
on demand — indirect actuator control of the operator's home mediated through hassette's own
credential. Filed as GitHub issue #1117 (`priority:high`, `release:v1.0.0`, `size:large`).

The fix adds two independent, composable trust mechanisms — a trusted-proxy peer check (for
operators running a forward-auth gateway) and a bearer-token/session-cookie fallback (for everyone
else) — behind a single default-deny ASGI middleware, plus startup guards against the
no-auth-and-non-loopback misconfiguration.

## Visual Artifacts

None.

## Key Decisions

1. **Two independent trust mechanisms, checked in order**: trusted-proxy peer match (no credential
   needed) first, then bearer token / session cookie. Both are first-class, not primary/fallback in
   a value sense — an operator with a forward-auth gateway uses only the first; everyone else uses
   only the second.
2. **`trusted_proxies` compares only the raw ASGI `scope["client"]`** — never `X-Forwarded-For` or
   any other client-suppliable header. This is the single most consequential control in the design;
   do not implement header-based trust as a shortcut.
3. **Uvicorn's own `proxy_headers` stays `False` unconditionally.** Enabling it would let
   `ProxyHeadersMiddleware` rewrite `scope["client"]` from `X-Forwarded-For` before hassette's own
   middleware ever sees the real peer, silently breaking the trusted-proxy check.
4. **Cookie `Secure` flag is decided by hassette's own auth code**, not uvicorn's proxy machinery —
   it reads `X-Forwarded-Proto` directly, and only trusts it when that same request's raw
   `scope["client"]` already matched `trusted_proxies` (the identical check reused, not duplicated).
5. **Session cookie is stateless** — HMAC-derived, keyed by the auth token, with an embedded
   issuance timestamp checked against a TTL at validation time. No server-side session table, so it
   survives `WebApiService`'s `RestartType.TRANSIENT` restarts.
6. **`trusted_proxies` hostname entries resolve via DNS at startup and periodically thereafter**
   (via `Scheduler.run_every()`), never per-request — per-request resolution was rejected as a
   DNS-rebinding risk.
7. **Token resolution order**: explicit config/env value → existing `<data_dir>/.web_api_token` file
   → freshly generated (`secrets.token_urlsafe(32)`), written atomically. Whichever branch fires is
   logged at INFO so an operator who lost a token file sees a distinguishable event, not silence.
8. **No password accounts, hashing, or setup wizard.** Explored in depth and reverted during
   design — see design.md's Alternatives Considered. Do not reintroduce this shape.
9. **Health endpoints and the login route are the only default-deny exemptions.** `/api/docs` and
   `/api/openapi.json` are explicitly NOT exempted (closes an existing unauthenticated
   schema-fingerprinting surface).
10. **Default `host` bind stays `0.0.0.0`.** Safety comes from auth-on-by-default plus the startup
    guards, not from changing the bind address — flipping it would silently break existing
    `docker run -p`/Compose deployments.

## Constraints & Anti-Patterns

- Do not implement `trusted_proxies` matching against any header — `scope["client"]` only.
- Do not reuse `InvalidAuthError` (`exceptions.py:140-141`) for any new auth-failure exception — it
  is a `FatalError` subclass wired into `websocket_service.py`'s `NON_RETRYABLE` tuple and means "HA
  rejected hassette's own outbound token," an unrelated failure mode. New exceptions are plain
  `HassetteError` subclasses under different names.
- No new third-party dependencies — `fastapi.security`, stdlib `secrets`/`hmac`/`ipaddress`/`socket`
  cover the entire design.
- Do not build password-based accounts, hashing, or a claim/setup wizard.
- Do not change the default `host` bind from `0.0.0.0`.
- `trusted_proxies` hostname entries resolve periodically via `Scheduler.run_every()` — never
  per-request.
- Do not implement RBAC, multi-user accounts, OAuth/OIDC, rate limiting on mutation endpoints, or
  multiple individually-revocable tokens — all explicit Non-Goals.
- Do not fold issue #708 (secret redaction hardening for `/api/config`) into this work — separate
  follow-up issue.
- Do not edit the HA add-on epic's design artifacts (ADR-0005, prereq-03, prereq-04) as part of
  implementation — those are sequenced as a documented follow-up (see design.md Replacement
  Targets), not part of any task here.

## Design Doc References

- `## Problem` — why hassette needs auth now (indirect actuator control via HA token).
- `## Goals` / `## Non-Goals` — scope boundaries; read before adding anything not explicitly listed.
- `## User Scenarios` — four flows: forward-auth-gateway operator, no-gateway/bare-Docker operator,
  CLI/script access, and the non-loopback-no-proxy misconfiguration warning.
- `## Functional Requirements` — FR#1 through FR#21, the authoritative numbered requirements.
- `## Edge Cases` — DNS resolution failure, sibling proxy container recreated mid-run, token file
  write failure, corrupt token file, bad `trusted_proxies` entry, health endpoints must always be
  reachable.
- `## Acceptance Criteria` — AC#1 through AC#19, each mapped to one or more FRs.
- `## Key Constraints` — the non-negotiable technical constraints (peer-only trust, no
  `InvalidAuthError` reuse, no new deps, no password accounts, periodic not per-request DNS, don't
  change the bind).
- `## Architecture` — the full mechanism design: Credential model, Cookie `Secure` flag, Middleware
  and routing, WebSocket auth, Startup guards, CORS validator, Misuse-visibility logging, CLI.
- `## Implementation Preferences` — exact patterns to mirror (`AuthDep` shape, `SecretStr` field
  shape, exception hierarchy shape, config field shape).
- `## Test Strategy` — required test types, existing tests to adapt, new test coverage mapped to
  FR#/AC#, confirms nothing needs removal.
- `## Documentation Updates` — the four docs pages needing rewrites plus the schema regeneration.
- `## Impact` — the authoritative Changed Files list and Behavioral Invariants that must not break.

## Convention Examples

### Dependency injection accessor pattern

**Source:** `src/hassette/web/dependencies.py:46-71`

```python
def get_hassette(request: Request) -> "Hassette":
    return request.app.state.hassette


def get_runtime(request: Request) -> "RuntimeQueryService":
    return request.app.state.hassette.runtime_query_service


# Shared dependency type aliases — import these instead of re-defining locally.
HassetteDep = Annotated["Hassette", Depends(get_hassette)]
RuntimeDep = Annotated["RuntimeQueryService", Depends(get_runtime)]
```

`AuthDep` follows this exact shape: a plain accessor function plus an `Annotated[X, Depends(...)]`
alias, added to the same "Shared dependency type aliases" block. Verified during Phase 2 exploration:
the actual block (`web/dependencies.py:67-71`) has five aliases today (`HassetteDep`, `RuntimeDep`,
`TelemetryDep`, `SchedulerDep`, `ApiDep`), not two — the design doc's quote is abbreviated for
brevity, not a count.

### `SecretStr` + masking pattern

**Source:** `src/hassette/config/config.py:142-151`, `auth_headers` property at lines 248-256
(verified during Phase 2 exploration — the design doc cites 255-257, off by ~7 lines)

```python
token: SecretStr | None = Field(
    default=None,
    validation_alias=AliasChoices("token", "hassette__token", "ha_token", "home_assistant_token"),
)
"""Access token for Home Assistant instance.

Stored as a :class:`~pydantic.SecretStr` so the value is masked in logs
and string representations.  Unwrap with ``token.get_secret_value()`` when
the plaintext is required (e.g. HTTP auth headers, WebSocket auth payload).
"""

@property
def auth_headers(self) -> dict[str, str]:
    if self.token is None:
        return {}
    return {"Authorization": f"Bearer {self.token.get_secret_value()}"}
```

`auth_token` on `WebApiConfig` mirrors this exactly — `SecretStr | None`, a docstring explaining the
masking rationale, `.get_secret_value()` called only at the point of use.

### Exception hierarchy

**Source:** `src/hassette/exceptions.py:36-37` (`HassetteError`), `40-44` (`FatalError`), `89-94`
(`RetryableConnectionClosedError`), `140-141` (`InvalidAuthError` — do NOT reuse), `152-169`
(plain-`HassetteError`-subclass, mostly-docstring-only examples: `InvalidInheritanceError`,
`UndefinedUserConfigError`, `EntityNotFoundError`)

```python
class HassetteError(Exception):
    """Base exception for all Hassette errors."""


class FatalError(HassetteError):
    """Custom exception to indicate a fatal error in the application.

    Exceptions that indicate that the service should not be restarted should inherit from this class.
    """


class RetryableConnectionClosedError(ConnectionClosedError):
    """Custom exception to indicate that the WebSocket connection was closed but can be retried."""

    def __init__(self, msg: str, *, close_code: int | None = None) -> None:
        super().__init__(msg)
        self.close_code = close_code
```

New auth exceptions are plain `HassetteError` subclasses (not `FatalError` — an auth failure should
not crash or block-restart the service), mostly docstring-only, with a custom `__init__` only if
structured data needs to travel (unlikely here). Insert as a new block after `InvalidAuthError`
(~line 142) or appended at file end (after line 427).

### Router pattern

**Source:** `src/hassette/web/routes/health.py` (full file, 31 lines — verified identical to design
doc's quoted excerpt during Phase 2 exploration)

```python
"""Health and status endpoints."""

from fastapi import APIRouter, Response

from hassette.web.dependencies import RuntimeDep
from hassette.web.mappers import readiness_response_from, system_status_response_from
from hassette.web.models import LivenessResponse, ReadinessResponse, SystemStatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=SystemStatusResponse)
async def get_health(runtime: RuntimeDep) -> SystemStatusResponse:
    """Return the full system status. Always HTTP 200 while the process can serve."""
    return system_status_response_from(runtime.get_system_status())
```

New `web/routes/auth.py` follows this shape: `APIRouter(tags=["auth"])`, `response_model=` on the
route, registered in `web/app.py` with `app.include_router(auth_router, prefix="/api")` alongside the
existing routers (`scheduler.py` confirmed the same shape for a more complex router, including
`db_degrades_to(response)` for DB-backed handlers — not needed here since auth has no DB dependency).

### Test fixture pattern

**Source:** `tests/integration/web_api/conftest.py:16-46` (`mock_hassette`), `55-66` (`app`/`client`
— verified during Phase 2 exploration; the design doc's "61-66" citation for the `app` fixture is
off by ~6 lines, the correct range is 55-58)

```python
@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance for the FastAPI app."""
    return create_hassette_stub(
        run_web_ui=False,
        states={...},
        old_snapshot=AppStatusSnapshot(running=[instance], failed=[]),
        app_action_mocks=True,
    )


@pytest.fixture
def app(mock_hassette, runtime_query_service):
    """Create a FastAPI app with mocked dependencies."""
    return create_fastapi_app(mock_hassette)
```

`create_hassette_stub()` gains an `auth_enabled` parameter, defaulting to `False`, so the existing
~211 integration and ~165 e2e tests pass unchanged; `tests/integration/web_api/test_auth.py`
explicitly passes `auth_enabled=True` to exercise the new behavior.
