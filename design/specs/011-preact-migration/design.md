# Design: Migrate Web UI from htmx/Alpine to Preact SPA

**Date:** 2026-03-20
**Status:** archived
**Spec:** N/A (design-first — problem well-established from prior research)

## Problem

The htmx + Alpine.js + idiomorph stack fundamentally conflicts with the UI's need for client-side state preservation during real-time updates. The specific failures:

1. **Idiomorph destroys Alpine state on morph** — expanding a handler row, then receiving a WebSocket `app_status_changed` event, collapses the row because `morph:innerHTML` overwrites `x-data` state.
2. **`htmx.ajax()` bypasses the extension system** — programmatic swaps can't use alpine-morph; the proposed two-morph-engine strategy (`design/specs/010-alpine-morph-fix/`) is unimplementable as designed.
3. **Dual source of truth** — server-rendered HTML and 70 lines of manual DOM-patching JS (`live-updates.js:146-218`) compete to update the same handler row stats, using brittle CSS class and text-substring matching.
4. **Dead polling partial** — a hidden `#app-handler-stats` div polled every 5 seconds returns `data-*` attributes that JavaScript reads and manually patches into DOM, because morphing would destroy Alpine state.

These aren't bugs — they're paradigm mismatches. The UI needs persistent client-side state, targeted re-renders from WebSocket events, and composable interactive components. That's what React-style virtual DOM rendering was invented for.

## Non-Goals

- **UI redesign** — the existing layout, information hierarchy, visual direction (`design/direction.md`), and design tokens (`tokens.css`) are preserved. This is a rendering technology swap. **`design/direction.md` and `tokens.css` are the canonical design specifications. `design/interface-design/system.md` is superseded and should be archived or deleted as part of this migration.**
- **Backend API rewrite** — the existing `/api/*` JSON endpoints and WebSocket protocol stay. Only thin JSON wrappers are added for telemetry data currently served as HTML-only partials.
- **React ecosystem** — no `preact/compat`, React Router, or TanStack Query. Preact's native APIs (signals, hooks) and a lightweight router suffice for 5 pages.
- **SSR/hydration** — the SPA serves a shell `index.html` and renders client-side. No server-side rendering of Preact components.

## Architecture

### Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| UI framework | **Preact 10.x** | 3KB gzipped, same JSX/hooks API as React, huge AI training data overlap |
| State management | **@preact/signals** via context injection | Fine-grained reactivity; factory function + Context Provider pattern for testability (no global singletons) |
| Routing | **wouter** | 1.2KB, framework-agnostic, supports both hash and history routing (important for HA add-on subpath deployments), broader community adoption than preact-iso |
| Build | **Vite** with `@preact/preset-vite` | Sub-second HMR, native ESM, simple config. Replaces the custom `dev_reload` WS message and CSS cache-busting |
| Styling | **CSS Modules** + global design primitives + existing design tokens | Component-scoped `.module.css` for component-local styles; shared design primitives (`.ht-card`, `.ht-btn`, etc.) stay in `global.css` |
| Type generation | **openapi-typescript** against FastAPI's `/api/openapi.json` | Generates TS types from the existing OpenAPI contract — no Python dependency in the frontend build, actively maintained |
| Testing | **Playwright** (e2e) + **Vitest** (unit) | Vitest for component/hook unit tests; Playwright for user-visible behavior |

### Directory Structure

```
frontend/                          # New — Preact SPA source
  src/
    main.tsx                       # Entry point, router setup
    app.tsx                        # Root component (layout shell + error boundary)
    api/
      client.ts                   # Fetch wrapper (base URL, error handling)
      types.ts                    # Auto-generated from OpenAPI schema
      endpoints.ts                # Typed API functions (getApps, getHealth, etc.)
    hooks/
      use-websocket.ts            # WebSocket connection, reconnection, state reconciliation
      use-api.ts                  # Data fetching with signal-based caching
    state/
      create-app-state.ts         # Factory function returning all app signals (injectable via Context)
      context.ts                  # AppStateContext provider and useAppState() hook
    pages/
      dashboard.tsx               # KPI strip + app grid + error feed
      apps.tsx                    # Manifest list with status filter tabs
      app-detail.tsx              # Health strip + handler/job rows + logs
      logs.tsx                    # Global log viewer
      not-found.tsx               # 404 page
    components/
      layout/
        sidebar.tsx               # 56px icon-rail nav
        status-bar.tsx            # Top status bar with connection state machine
        alert-banner.tsx          # Failed apps alert
        error-boundary.tsx        # Page-level error boundary with retry
      dashboard/
        kpi-strip.tsx             # KPI cards
        app-grid.tsx              # App health grid
        app-card.tsx              # Single app health card
        error-feed.tsx            # Recent errors list
      apps/
        manifest-list.tsx         # App manifest table
        manifest-row.tsx          # Single manifest row
        status-filter.tsx         # Status tab bar
        action-buttons.tsx        # Start/stop/reload
      app-detail/
        health-strip.tsx          # 4 health KPI cards
        handler-list.tsx          # Handler row list
        handler-row.tsx           # Expandable handler row
        handler-invocations.tsx   # Lazy-loaded invocation history
        job-list.tsx              # Job row list
        job-row.tsx               # Expandable job row
        job-executions.tsx        # Lazy-loaded execution history
      shared/
        status-badge.tsx          # Status dot + label
        health-bar.tsx            # Success rate bar
        log-table.tsx             # Log viewer (filters, sort, WS streaming)
        spinner.tsx               # Loading indicator
    utils/
      format.ts                   # format_handler_summary, time formatting (display only)
  public/
    fonts/                        # Self-hosted Google Fonts (Space Grotesk, DM Sans, JetBrains Mono)
  vite.config.ts
  tsconfig.json
  vitest.config.ts

src/hassette/web/
  static/
    spa/                          # Vite build output (gitignored, built at package time)
      index.html
      assets/
        *.js
        *.css
  app.py                          # Modified — SPA catch-all route replaces template routes
  models.py                       # Updated — add typed WS message models + error response models
  dependencies.py                 # Unchanged
  routes/                         # Unchanged — all /api/* routes stay
    apps.py
    bus.py
    config.py
    events.py
    health.py
    logs.py
    scheduler.py
    services.py
    ws.py
  routes/telemetry.py             # New — JSON endpoints for data currently in HTML partials
```

### What Gets Deleted

| Path | Lines | Reason |
|------|-------|--------|
| `src/hassette/web/ui/` (entire directory) | ~400 | `router.py`, `partials.py`, `context.py`, `__init__.py` — all serve HTML templates. **Prerequisite: shared helpers extracted first (see Step 0 below).** |
| `src/hassette/web/templates/` (entire directory) | 1,359 | 26 Jinja2 templates — replaced by Preact components |
| `src/hassette/web/static/js/` (3 files) | 582 | `ws-handler.js`, `live-updates.js`, `log-table.js` — replaced by hooks/components |
| `src/hassette/web/static/css/style.css` | 1,695 | Replaced by CSS Modules + global.css (tokens.css is kept and moved to `frontend/src/`) |
| `tools/check_template_patterns.py` | ~100 | Jinja2 template linter — no longer applicable |
| `tests/integration/test_web_ui.py` | 1,036 | HTML assertion tests — replaced by JSON API tests + Playwright (deleted AFTER telemetry endpoint tests are written) |
| `design/interface-design/system.md` | — | Superseded by `design/direction.md`; archive to `design/interface-design/system.md.archived` |

**Total removed:** ~5,172 lines of templates, JS, CSS, and HTML-specific tests.

### What Gets Added

#### Typed WebSocket Protocol (`models.py` additions)

The current `WsMessage` model (`type: str, data: dict[str, Any]`) is untyped. Replace with discriminated union models:

```python
class AppStatusChangedPayload(BaseModel):
    """Mirrors events.hassette.AppStateChangePayload exactly."""
    app_key: str
    index: int
    status: str  # ResourceStatus serialized as string
    previous_status: str | None = None
    instance_name: str | None = None
    class_name: str | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None

class AppStatusChangedWsMessage(BaseModel):
    type: Literal["app_status_changed"]
    data: AppStatusChangedPayload
    timestamp: float

class LogWsMessage(BaseModel):
    type: Literal["log"]
    data: LogEntryResponse
    timestamp: float

class ConnectedWsMessage(BaseModel):
    type: Literal["connected"]
    data: ConnectedPayload  # includes session_id, entity_count, app_count

class StateChangedPayload(BaseModel):
    entity_id: str
    new_state: str
    old_state: str

class StateChangedWsMessage(BaseModel):
    type: Literal["state_changed"]
    data: StateChangedPayload  # normalized to use data envelope like all other messages
    timestamp: float

class ConnectivityWsMessage(BaseModel):
    type: Literal["connectivity"]
    data: ConnectivityPayload  # { connected: bool }
    timestamp: float

class ServiceStatusWsMessage(BaseModel):
    type: Literal["service_status"]
    data: ServiceStatusPayload  # mirrors actual broadcast shape
    timestamp: float

# Discriminated union for all server-to-client messages
WsServerMessage = Annotated[
    AppStatusChangedWsMessage | LogWsMessage | ConnectedWsMessage
    | ConnectivityWsMessage | StateChangedWsMessage | ServiceStatusWsMessage,
    Field(discriminator="type")
]
```

This gives TypeScript proper discriminated union types — `msg.type === 'app_status_changed'` narrows `msg.data` to `AppStatusChangedPayload` automatically.

**Enforcement at the broadcast site:** `RuntimeQueryService._on_app_state_changed` must construct `AppStatusChangedPayload.model_validate(raw_dict)` and serialize via `.model_dump()` instead of using the generic `_serialize_payload(asdict(raw))`. This validates the shape at the server, not just in the type system. A test asserts that every broadcast payload conforms to its Pydantic model.

**WS types and OpenAPI:** WebSocket message models are NOT part of the OpenAPI spec. The TypeScript WS types are **hand-authored** (~30 lines for 6 message types) rather than auto-generated, because `json-schema-to-typescript (CI conformance testing only)` does not generate true discriminated unions from Pydantic's `discriminator` metadata ([open issue since 2020](https://github.com/bcherny/json-schema-to-typescript (CI conformance testing only)/issues/239)). A CI conformance test validates that the hand-authored TS types match the Pydantic JSON Schema exported via `WsServerMessage.model_json_schema()`, catching drift without relying on broken codegen.

**All messages use a consistent envelope:** `{ type, data, timestamp }`. The `state_changed` broadcast is normalized to wrap `entity_id`/`new_state`/`old_state` in a `data` field (matching every other message type) rather than using flat top-level fields. This normalization happens at the broadcast site in `_on_state_change`.

#### Typed Error Response Models

`get_recent_errors()` currently returns `list[dict]` with polymorphic handler/job shapes. Add typed models:

```python
class HandlerErrorEntry(BaseModel):
    kind: Literal["handler"] = "handler"
    listener_id: int
    topic: str
    handler_method: str
    error_message: str
    error_type: str
    timestamp: float
    app_key: str

class JobErrorEntry(BaseModel):
    kind: Literal["job"] = "job"
    job_id: int
    job_name: str
    error_message: str
    error_type: str
    timestamp: float
    app_key: str

RecentErrorEntry = Annotated[HandlerErrorEntry | JobErrorEntry, Field(discriminator="kind")]
```

#### New Telemetry JSON Endpoints (`routes/telemetry.py`)

The following data is currently only available via HTML partials. Each needs a thin JSON endpoint wrapping the existing `TelemetryQueryService` method. **All telemetry endpoints resolve `session_id` server-side** via the existing `safe_session_id(runtime)` pattern — the SPA never needs to know or pass a session ID.

| Endpoint | Wraps | Returns |
|----------|-------|---------|
| `GET /api/telemetry/app/{app_key}/health` | `get_listener_summary` + `get_job_summary` + `compute_health_metrics` | Health strip metrics including server-computed `health_status` and `error_rate_class` labels |
| `GET /api/telemetry/app/{app_key}/listeners` | `get_listener_summary` | Listener metrics with handler summaries |
| `GET /api/telemetry/app/{app_key}/jobs` | `get_job_summary` | Job summaries |
| `GET /api/telemetry/handler/{listener_id}/invocations` | `get_handler_invocations` | Invocation history |
| `GET /api/telemetry/job/{job_id}/executions` | `get_job_executions` | Execution history |
| `GET /api/telemetry/dashboard/kpis` | `get_global_summary` | KPI strip metrics with server-computed classification labels |
| `GET /api/telemetry/dashboard/app-grid` | `get_all_app_summaries` + manifests | Per-app health cards with computed `health_status` |
| `GET /api/telemetry/dashboard/errors` | `get_recent_errors` | Recent errors as typed `RecentErrorEntry` union |

**Dashboard data is 3 separate endpoints**, not a single god-endpoint. The SPA fetches them in parallel with `Promise.all`. Each panel renders as its data arrives, preserving the progressive loading behavior of the current partial architecture.

**Classification stays server-side.** `classify_error_rate` and `classify_health_bar` return classification labels (`"good"`, `"warn"`, `"bad"`, `"excellent"`, `"critical"`) alongside raw numbers. The server owns the thresholds; the client maps labels to CSS classes. No business logic duplication.

**`instance_index` defaults to 0** on all endpoints and is an optional query parameter. The SPA doesn't need to understand instance topology unless on an instance-specific detail page.

#### State Architecture (Context-Based Signal Injection)

Signals are NOT global singletons. They are created by a factory function and provided via Preact Context:

```typescript
// state/create-app-state.ts
function createAppState() {
  return {
    appStatus: signal<AppStatusMap>({}),
    connection: signal<ConnectionState>({ status: 'disconnected' }),
    logs: { buffer: new RingBuffer<LogEntry>(1000), version: signal(0) },
    theme: signal<'dark' | 'light'>('dark'),
    sessionId: signal<number | null>(null),
  };
}

type AppState = ReturnType<typeof createAppState>;

// state/context.ts
const AppStateContext = createContext<AppState>(null!);
const useAppState = () => useContext(AppStateContext);

// app.tsx — root
function App() {
  const state = useMemo(() => createAppState(), []);
  return (
    <AppStateContext.Provider value={state}>
      <ErrorBoundary><Layout><Router /></Layout></ErrorBoundary>
    </AppStateContext.Provider>
  );
}
```

Benefits:
- **Testable**: each test creates fresh state via `createAppState()` — no leaking between tests
- **Fine-grained**: signal updates still trigger only subscribing components
- **Injectable**: WebSocket hook receives state as a parameter, not an import

#### WebSocket Hook (`use-websocket.ts`)

Replaces `ws-handler.js` (127 lines) + `live-updates.js` (240 lines):

```typescript
function useWebSocket(state: AppState) {
  useEffect(() => {
    const socket = new WebSocket(`${wsProtocol}//${location.host}/api/ws`);

    socket.onopen = () => {
      state.connection.value = { status: 'connected' };
    };

    socket.onclose = () => {
      state.connection.value = { status: 'reconnecting' };
      // Exponential backoff reconnection (carry over from ws-handler.js)
    };

    socket.onmessage = (e) => {
      const msg: WsServerMessage = JSON.parse(e.data);
      batch(() => {
        switch (msg.type) {
          case 'connected':
            state.sessionId.value = msg.data.session_id;
            break;
          case 'app_status_changed':
            // Type-narrowed: msg.data is AppStatusChangedPayload
            state.appStatus.value = {
              ...state.appStatus.value,
              [msg.data.app_key]: msg.data.status,
            };
            break;
          case 'log':
            // Mutable ring buffer + version signal (O(1), not O(n) array copy)
            state.logs.buffer.push(msg.data);
            state.logs.version.value++;
            break;
        }
      });
    };

    return () => socket.close();
  }, [state]);
}
```

Key design decisions:
- **`batch()`** wraps all signal updates to coalesce rapid messages into a single render pass
- **Ring buffer + version signal** for logs: `push()` is O(1), `version++` triggers re-render without copying 1000-element arrays
- **Typed message dispatch** via discriminated union — TypeScript narrows `msg.data` by `msg.type`
- **State reconciliation on reconnect**: after WebSocket reconnects, refetch all active page data via REST endpoints (the `onReconnect` callback triggers page-level data refresh). The htmx approach self-healed via partial re-fetches; the SPA must do the same explicitly.
- **Connection state machine**: `connected | reconnecting | disconnected` — rendered in the status bar

#### CSS Migration Strategy

1. **`tokens.css`** — moves to `frontend/src/tokens.css`, imported globally in `main.tsx`. All `--ht-*` custom properties preserved exactly.
2. **`global.css`** — contains reset, font-face declarations, layout scaffolding, AND shared design primitives (`.ht-card`, `.ht-btn`, `.ht-status-badge`, `.ht-item-row`, etc.). These are design system classes that multiple components share — keeping them global preserves the design token cascade.
3. **Component `.module.css`** — for styles truly local to a single component (internal layout, animation states, component-specific overrides). Drop the `ht-` prefix in module files since CSS Modules scope automatically.
4. **Fonts** — self-hosted in `frontend/public/fonts/` instead of CDN-loaded from Google Fonts.

The split: design system primitives in `global.css`, component internals in `.module.css`. When uncertain, prefer `global.css` — premature scoping is worse than consistent global classes.

#### Error Boundary and Loading States

A monitoring UI that crashes when the monitored system crashes is worse than useless. The SPA includes:

1. **`<ErrorBoundary>`** — wraps each page. On component error, displays the last good state with a "Retry" button. Does not blank the entire app.
2. **Connection state machine** — `connected | reconnecting | disconnected` rendered in the status bar. During `reconnecting`, the UI shows stale data with a visible indicator (not blank).
3. **Loading strategy** — inline spinners for initial data fetch; stale-while-revalidate for subsequent updates. Never show a blank page when stale data is available.

### Build Pipeline

```
frontend/ ─── vite build ───→ src/hassette/web/static/spa/
                                  index.html
                                  assets/*.js
                                  assets/*.css
```

**Development:** `vite dev` runs a dev server with HMR, proxying `/api/*` and `/api/ws` to the FastAPI backend (`uvicorn`). Two terminal tabs: one for `vite dev`, one for `uvicorn`.

**Production/packaging:** `vite build` outputs to `src/hassette/web/static/spa/`. The Python package includes these built assets. A `uv` build hook or Makefile target ensures `vite build` runs before `uv build`.

**CI:** `npm ci && npm run build` before `uv run nox`. The built SPA is a build artifact, not checked into git.

**Docker:** Multi-stage build with a Node.js frontend stage:

```dockerfile
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# Vite outputs to frontend/dist/ by default (configured via vite.config.ts outDir)

# In the Python builder stage:
COPY --from=frontend /app/frontend/dist/ /app/src/hassette/web/static/spa/
```

The final image remains Node-free. End users pull a Docker image — they never touch Node, npm, or Vite.

### FastAPI Changes (`web/app.py`)

```python
def create_fastapi_app(hassette: "Hassette") -> FastAPI:
    app = FastAPI(...)
    # ... middleware, API routes (unchanged) ...

    # New: telemetry JSON endpoints (available even without UI)
    app.include_router(telemetry_router, prefix="/api")

    # SPA serving (replaces template routes)
    if hassette.config.run_web_ui:
        spa_dir = Path(__file__).parent / "static" / "spa"
        if spa_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(spa_dir / "assets")), name="spa-assets")

            @app.get("/{path:path}")
            async def spa_catch_all(path: str) -> FileResponse:
                """Serve index.html for SPA client-side routing.

                Returns 404 for API paths and static asset requests to prevent
                the catch-all from swallowing legitimate 404s.
                """
                # Reject API paths and known static asset extensions.
                # Uses explicit extension list (not "any dot") because SPA routes
                # may contain dots (e.g., entity IDs like light.kitchen).
                _STATIC_EXTENSIONS = {".js", ".css", ".ico", ".png", ".svg", ".map", ".json", ".woff", ".woff2", ".txt"}
                last_segment = path.rsplit("/", 1)[-1]
                is_static = any(last_segment.endswith(ext) for ext in _STATIC_EXTENSIONS)
                if path.startswith("api/") or is_static:
                    raise HTTPException(status_code=404, detail=f"/{path} not found")
                return FileResponse(spa_dir / "index.html")

    return app
```

Key changes from the original draft:
- **`run_web_ui` guard preserved** — headless mode continues to work
- **Catch-all guards** — returns 404 for `api/*` paths (prevents `SyntaxError: Unexpected token '<'` on mistyped API calls) and paths ending in known static extensions like `.js`, `.css`, `.ico`, `.json` (prevents serving `index.html` for `favicon.ico`, `robots.txt`, etc.). Uses an explicit extension list instead of "any dot" to avoid false positives on SPA routes containing entity IDs (e.g., `light.kitchen`)
- **Telemetry endpoints outside the UI guard** — available even in headless mode (useful for external monitoring)

### Type Generation

**Two type sources, two strategies:**

1. **REST API types** — auto-generated from the OpenAPI schema via `openapi-typescript`
2. **WebSocket message types** — hand-authored TypeScript discriminated union (~30 lines), validated against Pydantic JSON Schema in CI

`openapi.json` is **committed to the repo**. This avoids the bootstrap problem of needing a running Hassette instance to generate the schema.

```bash
# Generate OpenAPI schema (run in CI or manually during development)
# Uses a lightweight script that imports the FastAPI app without connecting to HA
python scripts/export_schemas.py  # outputs frontend/openapi.json

# Generate TypeScript types from OpenAPI schema
# IMPORTANT: schema export must run BEFORE the frontend build
npx openapi-typescript frontend/openapi.json -o frontend/src/api/types.ts
```

The `export_schemas.py` script creates a minimal `Hassette` stub (mock config, no HA connection) to get `app.openapi()`. It also exports `ws-schema.json` from `WsServerMessage.model_json_schema()` for CI conformance testing (not for codegen). This runs in CI without external dependencies.

WebSocket types are hand-authored in `frontend/src/api/ws-types.ts` because `json-schema-to-typescript (CI conformance testing only)` [cannot generate true discriminated unions](https://github.com/bcherny/json-schema-to-typescript (CI conformance testing only)/issues/239). A CI test validates the hand-authored types match the exported JSON Schema, catching drift without broken codegen.

Benefits over `pydantic2ts`:
- **No abandoned dependency** — `openapi-typescript` has weekly releases and broad adoption
- **No Python in the frontend build** — schema is a committed artifact
- **Generates more than models** — OpenAPI types include endpoint paths, parameters, and response types
- **Uses the actual deployed contract** — not source-code introspection

CI pipeline ordering: schema export → type generation → frontend build → Python tests. CI validates drift: regenerate schema + types, then `git diff --exit-code` catches any uncommitted changes.

### Test Strategy

| Layer | Tool | Replaces | Coverage |
|-------|------|----------|----------|
| Component unit tests | **Vitest** + `@testing-library/preact` | Nothing (new) | Hook behavior, signal updates, component rendering |
| API integration tests | **pytest** + `httpx` | `test_web_ui.py` HTML assertions | JSON response shape, status codes, query params |
| E2e tests | **Playwright** | Existing 10 e2e files | User-visible behavior (navigation, expand/collapse, filtering, live updates) |

**Signal isolation in Vitest**: Each test creates fresh state via `createAppState()` and wraps the component under test in `<AppStateContext.Provider value={freshState}>`. No global signal leaking between tests.

**E2e WebSocket testing**: The e2e test server must enable WebSocket (`ws="auto"` instead of the current `ws="none"`). The `mock_hassette` fixture's `runtime_query_service.broadcast()` sends real messages through the WebSocket, testing the full pipeline: server broadcast → WS → client signal → component re-render. This replaces the current DOM event simulation approach.

**Migration sequencing**: Telemetry endpoint tests are written BEFORE `test_web_ui.py` is deleted. The sequence:

0. **Extract shared helpers** — move `safe_session_id`, `classify_error_rate`, `classify_health_bar`, `compute_health_metrics`, `format_handler_summary`, `compute_app_grid_health`, `extract_entity_from_topic`, and `alert_context` from `web/ui/context.py` to `src/hassette/web/telemetry_helpers.py`. Update existing imports in `partials.py` and `router.py` to point to the new module. Both old partials and new endpoints import from the same place during the transition. This is a pure refactor — no behavior changes, existing tests pass unchanged.
1. Add typed WS message models to `models.py` + enforce at broadcast site + `ws-schema.json` export
2. Add `routes/telemetry.py` + integration tests (no frontend yet)
3. Build Preact components consuming the endpoints + Vitest component tests
4. Rewrite Playwright e2e tests with new selectors and real WS
5. Delete old HTML routes, templates, and `test_web_ui.py`

At no point does a function lose test coverage.

### Nox Integration

The `e2e` nox session must build the frontend before running tests:

```python
@nox.session(python=False)
def frontend(session):
    """Build the Preact SPA."""
    session.run("npm", "ci", "--prefix", "frontend", external=True)
    session.run("npm", "run", "build", "--prefix", "frontend", external=True)
```

The `e2e` session calls `frontend` as a prerequisite. The `dev` session checks for `src/hassette/web/static/spa/index.html` and fails fast with a clear message if the SPA isn't built.

### WebSocket Protocol: Data-Carrying vs Notification

Each WS message type has a clear contract:

| Message type | Payload carries | SPA action |
|-------------|----------------|------------|
| `connected` | session_id, entity_count, app_count | Store session_id; refetch all page data (initial hydration) |
| `app_status_changed` | app_key, status, error info | Update status signal directly (badge updates); refetch telemetry for affected app only |
| `log` | Full log entry | Push to ring buffer (data-carrying, no refetch needed) |
| `connectivity` | connected boolean | Update connection indicator |
| `service_status` | service name, status | Update service status signal |

WS events that carry full data update signals directly. WS events that carry partial data (status change without telemetry metrics) update what they can directly AND trigger a targeted endpoint refetch for the rest. No message triggers a full-page refetch.

## Alternatives Considered

### Keep htmx/Alpine, fix incrementally (Option C from research)

Continue with the alpine-morph fix (spec 010) and Alpine store pattern for stats. Accept ongoing morph-engine management.

**Rejected because:** the fundamental paradigm mismatch remains. Every new interactive element in a morphed container requires evaluating which morph engine to use. The dual-morph-engine strategy adds cognitive overhead for every future feature. The research brief's own adversarial critique found three implementation issues with the alpine-morph approach before any code was written.

### Preact with preact/compat (React ecosystem access)

Same SPA approach but with React compatibility for TanStack Query, React Router, etc.

**Rejected because:** overkill for 5 pages and ~15 API endpoints. Preact's native signals are more ergonomic than TanStack Query for this scale. The compat layer can always be added later if needed.

### Full React (not Preact)

Use React directly for maximum ecosystem access and AI training data.

**Rejected because:** the 45KB bundle size difference doesn't buy anything for this application. Preact's API is 99% identical to React — AI models handle it equally well.

### preact-router for routing

**Rejected because:** unmaintained (no active development since 2023).

### preact-iso for routing

**Rejected because:** while maintained by the Preact core team, it has very low community adoption (~10 npm dependents) and no hash routing support. Hash routing matters for Home Assistant add-on subpath deployments where the SPA may run behind a reverse proxy at a non-root path. wouter supports both hash and history routing, has broader adoption, and is 1.2KB gzipped.

### Svelte or Solid

Modern reactive frameworks with even smaller bundles.

**Not evaluated in depth** because: smaller ecosystems mean less AI assistance quality, fewer community resources. Preact's React-compatible API is the pragmatic choice.

## Open Questions

None — all architecture decisions have been made through the planning interrogation and adversarial challenge.

## Impact

### Files Modified

| File | Change |
|------|--------|
| `src/hassette/web/app.py` | Remove template routes, add SPA catch-all (with guards) and telemetry router |
| `src/hassette/web/models.py` | Add typed WS message models (discriminated union), error entry models, classification labels |
| `src/hassette/web/routes/ws.py` | Add `session_id` to the `connected` message payload |
| `src/hassette/core/runtime_query_service.py` | Use typed WS message models for broadcast payloads |
| `pyproject.toml` | Remove `jinja2` dependency, add build hook for Vite |
| `package.json` | Add Preact, wouter, @preact/signals, Vite, Vitest, openapi-typescript |
| `Dockerfile` | Add Node.js multi-stage frontend builder |
| `noxfile.py` | Add `frontend` session; `e2e` session depends on it; `dev` checks for built SPA |
| `.gitignore` | Add `src/hassette/web/static/spa/`, `frontend/node_modules/` |
| `tests/integration/test_web_api.py` | Add tests for new telemetry JSON endpoints |
| `tests/e2e/conftest.py` | Enable WebSocket (`ws="auto"`), add broadcast test helpers |
| `CLAUDE.md` | Update frontend development instructions |

### Files Deleted

| Path | Reason |
|------|--------|
| `src/hassette/web/ui/` (entire directory) | Replaced by SPA |
| `src/hassette/web/templates/` (entire directory) | Replaced by Preact components |
| `src/hassette/web/static/js/*.js` | Replaced by Preact hooks/components |
| `src/hassette/web/static/css/style.css` | Replaced by CSS Modules + global.css |
| `tests/integration/test_web_ui.py` | Replaced by JSON API tests + Playwright (deleted after replacements exist) |
| `tests/e2e/*.py` (10 files) | Rewritten with new selectors and real WS |
| `tools/check_template_patterns.py` | No longer applicable |
| `design/specs/010-alpine-morph-fix/` | Superseded by this migration |

### Files Created

| Path | Purpose |
|------|---------|
| `frontend/` (entire directory) | Preact SPA source (~30 files) |
| `src/hassette/web/telemetry_helpers.py` | Shared helpers extracted from `ui/context.py` (Step 0) |
| `src/hassette/web/routes/telemetry.py` | New JSON endpoints for telemetry data |
| `scripts/export_schemas.py` | OpenAPI + WS schema export for type generation |
| `tests/e2e/*.py` (rewritten) | Playwright tests with real WS and updated selectors |
| `tests/frontend/` | Vitest component/hook tests |

### Blast Radius

- **Backend:** Small — API routes untouched; `models.py` gains typed WS models; `ws.py` adds `session_id` to connected message; one new route file; `app.py` simplified.
- **Frontend:** Complete replacement — every template, JS file, and CSS file changes.
- **Tests:** Significant — e2e tests rewritten (with real WS), HTML integration tests replaced, new component test layer added. Migration sequenced to maintain coverage.
- **Build:** New Vite build step added; Dockerfile gains Node.js builder stage; nox gains `frontend` session.
- **Dependencies:** `jinja2` removed from Python deps; `preact`, `wouter`, `@preact/signals`, `vite`, `vitest`, `openapi-typescript`, `json-schema-to-typescript (CI conformance testing only)` added to JS dev deps.
