# REVIEW.md — frontend/src/

## Schema Propagation Chain
After adding a field to a `BaseModel` in `src/hassette/web/models.py`, does the
full chain complete: `scripts/export_schemas.py` updates `frontend/openapi.json`
and `frontend/ws-schema.json`, then `npm run types` regenerates
`frontend/src/api/generated-types.ts` and `npm run ws-types` regenerates
`frontend/src/api/ws-types.ts`? A field absent from the generated TS type is
invisible to the frontend.

## WS Message Handler Completeness
`frontend/src/hooks/use-websocket.ts` dispatches on `message.type` to update the
Zustand store in `frontend/src/state/store.ts`. When a new `WsServerMessage`
variant is added to `src/hassette/web/models.py`, does `use-websocket.ts` have a
handler branch for it, and does `store.ts` have matching state and actions? An
unhandled type is silently dropped.

## Query Key and Endpoint Consistency
`frontend/src/lib/query-keys.ts` defines React Query cache keys, and
`frontend/src/api/endpoints.ts` defines the fetch functions. When a new endpoint
is added, does it get a corresponding query key? A fetch without a query key
won't be invalidated by `frontend/src/hooks/use-query-invalidator.ts`'s
WS-driven cache invalidation, causing stale data.

## Live-Status Overlay Sourcing
Components that display app or handler status should read from the Zustand
live-status overlay in `frontend/src/state/store.ts`, not from the cached
manifest snapshot returned by the initial REST fetch. Does a new or modified
status display read from the overlay, or does it show stale data that only
updates on a full page refresh?

## WS Validator Coverage
`frontend/src/api/ws-validator.generated.ts` is compiled from `ws-schema.json`.
When the WS schema adds a new message type, does `frontend/src/api/ws-validator.ts`
(the hand-written wrapper) correctly reject unknown types, or does validation
silently pass them through to `use-websocket.ts`?
