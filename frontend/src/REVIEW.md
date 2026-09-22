# REVIEW.md — frontend/src/

## Schema Propagation Chain
The REST and WebSocket schemas are independent: `build_openapi_schema()` derives
`frontend/openapi.json` from FastAPI routes, while `build_ws_schema()` derives
`frontend/ws-schema.json` from `WsServerMessage`. When a new field is added to a
response model in `src/hassette/web/models.py`, does the matching transport's
chain complete? REST: `scripts/export_schemas.py` → `npm run types` →
`frontend/src/api/generated-types.ts`. WS: `scripts/export_schemas.py` →
`npm run ws-types` → `frontend/src/api/ws-types.ts` and separately
`npm run validators` → `frontend/src/api/ws-validator.generated.ts`.

## WS Message Handler Completeness
`frontend/src/hooks/use-websocket.ts` dispatches on `message.type` with an
exhaustive `never` check at the end. When a new concrete `WsServerMessage`
variant (with a literal `type` field) is added to `src/hassette/web/models.py`,
does `use-websocket.ts` have a handler branch for it? Not every variant needs
Zustand state — some trigger React Query invalidation instead — but every
variant needs a dispatch branch or the `never` check will fail at compile time.

## Query Key and Endpoint Consistency
`frontend/src/lib/query-keys.ts` defines React Query cache keys, and
`frontend/src/api/endpoints.ts` defines the fetch functions. When a new
*cached query* endpoint is added (not a mutation or non-cached direct load),
does it get a corresponding query key? A cached fetch without a query key
won't be invalidated by `frontend/src/hooks/use-query-invalidator.ts`'s
WS-driven cache invalidation, causing stale data.

## Live-Status Overlay Sourcing
The Zustand overlay in `frontend/src/state/store.ts` holds live app and service
status (`appStatus`, `serviceStatus`, `executionCompleted`), not handler or job
status. Components that display app or service status should read from the
overlay, not the cached manifest snapshot. Handler and job data refreshes via
React Query invalidation instead. Does a new or modified app/service status
display read from the overlay?
