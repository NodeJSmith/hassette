# Frontend State Management Audit

**Date:** 2026-09-04
**Scope:** `frontend/src/` — state management architecture, data transport, cache coherence

## Summary

The frontend uses three competing state management systems — React Query (REST snapshots), Zustand (WS live data), and manual `setInterval` polling (telemetry health) — with no shared abstraction for resolving "current truth." Every component that displays app status, service status, or logs must manually merge sources. The merge pattern is implemented 3 times with completely different mechanics.

The `useQueryInvalidator` bridge (WS → Zustand → debounced React Query invalidation) shows what a unified approach looks like, but it's only wired for `execution_completed` events — not `app_status_changed`, `service_status`, or logs.

## Architecture Diagram

```
WS messages                              REST endpoints
    │                                         │
    ▼                                         ▼
Zustand store                         React Query cache
 • appStatus (per-instance)            • manifests list
 • serviceStatus                       • per-app manifest
 • logBuffer (RingBuffer)              • dashboard grid
 • executionCompleted batch            • recent logs
 • connection, uptime                  • listeners/jobs/activity
    │                                         │
    └──────────────┬──────────────────────────┘
                   ▼
          Derived overlays (in components)
           • appLiveStatus() merges appStatus + grid row
           • mergeServices() merges serviceStatus + health
           • useLogData() merges logBuffer + REST logs
           • useQueryInvalidator() bridges WS→RQ (execution only)
```

## Findings

### 1. CRITICAL — No unified state resolution layer (#1893)

Three state systems, no shared abstraction. Every consumer manually merges. Root cause of 6 tracked issues (#1611, #1610, #1609, #1601, #1400, #1373) that each patch individual symptoms.

### 2. HIGH — Three independent query paths for app manifest data (#1894)

`useManifests()`, `useManifest(key)`, and `dashboardGrid` cache the same app's data under different query keys with different invalidation triggers. Sidebar, detail page, and grid can disagree at any moment.

### 3. HIGH — `app_status_changed` has no query invalidation bridge (#1895)

`execution_completed` has a 6-consumer `useQueryInvalidator` bridge. `app_status_changed` and `service_status` update Zustand only, never invalidating React Query caches. Overlay pattern compensates where used; sidebar and command palette read stale manifests directly.

### 4. MEDIUM — Telemetry health polling bypasses React Query (#1896)

`useTelemetryHealth()` reimplements polling, backoff, abort, and navigation-reset in ~100 lines when React Query's `refetchInterval` provides all of this natively. Third transport pattern, invisible to devtools.

### 5. MEDIUM — `appStatus` selector too broad in apps.tsx (#1897)

Subscribes to the entire status map, re-rendering the full grid on every WS status change for any app. `app-detail.tsx` correctly narrows to a primitive. Performance ceiling worsens linearly with app count.

### 6. TENSION — Uniform 30s stale time (deferred)

Config and manifests use the same 30s default despite very different change frequencies. Deferred — better invalidation signals (#1895, #1611) are the right fix before tuning stale times.

## What's working well

- **Zustand store design** — clean domain grouping, atomic `handleWsConnected`, factory-based `initialState()` for test isolation
- **`useQueryInvalidator` pattern** — the execution-completed bridge is well-designed with scoped filtering and debounce; it just needs to be extended to other message types
- **`useScopedQuery`** — centralizes time-window logic cleanly; components don't manage their own time-scoping
- **`useScopedExecution`** — good Zustand selector discipline, keeps unrelated components off the render path
- **No derived-in-local-state anti-patterns** — components compute inline or via `useMemo` correctly
- **WS validation** — generated validators, exhaustive switch, proper error handling

## Existing issue landscape

| Issue | What it tracks | Status |
|---|---|---|
| #1611 | Broadcast config/lifecycle changes over WS | Open |
| #1610 | Fix stale WS appStatus surviving reconnect | Open |
| #1609 | Enforce live-status helpers over direct reads | Open |
| #1601 | Consolidate app status vocabulary | Open |
| #1400 | Use live WS status in sidebar grouping | Open |
| #1373 | Eliminate dual-path log assembly | Open |
| #1893 | Define unified data resolution architecture (this audit) | **New** |
| #1894 | Coordinate manifest cache invalidation (this audit) | **New** |
| #1895 | Add query invalidation bridge for status events (this audit) | **New** |
| #1896 | Migrate telemetry health to React Query (this audit) | **New** |
| #1897 | Narrow appStatus selector in apps.tsx (this audit) | **New** |
