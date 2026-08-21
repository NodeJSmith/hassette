---
task_id: "T03"
title: "file issues for deferred WS and observability gaps"
status: "planned"
depends_on: []
implements: ["FR#7"]
---

## Target Files

(No code changes — this task files GitHub issues only.)

## Prompt

File three GitHub issues for gaps identified in the research brief (`design/research/2026-08-21-status-exhaustiveness/research.md`) that are out of scope for this PR. Use `gh-issue create` with `--body-file` (write the body to a temp file first). Check for existing issues covering these topics before filing.

Before filing, run `gh-issue overview` to check repo milestones, labels, and conventions.

### Issue 1: WS connectivity refresh gap

**Title:** Surface HA connectivity changes in the UI via WS event consumption

**Body:** The backend correctly emits a `connectivity` WS event when the hassette-to-HA WebSocket link connects/disconnects. The frontend receives it but explicitly ignores it (`use-websocket.ts:151-153`). The aggregated `SystemStatus` (status, `websocket_connected`, `boot_issues`) is fetched via one-shot REST (`/health`) with `staleTime: 30_000` and no `refetchInterval`. If HA drops while viewing Diagnostics, the system health fields are frozen at page-load values.

**Acceptance Criteria:**
- [ ] `connectivity` WS events trigger a React Query invalidation of the system-status query
- [ ] System health banner updates within seconds of an HA connectivity change
- [ ] No polling — event-driven refresh only

**Labels:** `type:enhancement`, `area:ui`, `area:websocket`, `size:small`

### Issue 2: StateCacheFreshness observability gap

**Title:** Expose StateCacheFreshness to operators via API and UI

**Body:** `StateCacheFreshness` (FRESH/STALE/UNAVAILABLE) in `state_proxy.py` is never exposed outside that module. It's not in any REST response model, not in `SystemStatus`, and not in any WS payload. After a runtime HA disconnect marks the cache `STALE`, `get_system_status()` still reports a non-zero `entity_count` with no indication the data might be outdated. Operators cannot distinguish fresh from stale entity state.

**Acceptance Criteria:**
- [ ] `SystemStatus` response includes a `cache_freshness` field
- [ ] Diagnostics UI surfaces cache freshness state
- [ ] A stale cache is visually distinct from a fresh one

**Labels:** `type:enhancement`, `area:ui`, `area:core`, `topic:telemetry`, `size:medium`

### Issue 3: App resource-lifecycle transitions leak into service_status WS messages

**Title:** Filter app-role resources from service_status WS events

**Body:** Because `App` is a `Resource`, its lifecycle transitions (`handle_starting`/`handle_running` in `resources/lifecycle.py`) emit `HASSETTE_EVENT_SERVICE_STATUS` unconditionally. `RuntimeQueryService` subscribes with no role filter. App instances appear intermixed with framework services in the Diagnostics "Services" panel, and two instances of the same App class collide on the same `resource_name` key (keyed by class name, not `app_key+index`), silently overwriting each other's status.

**Acceptance Criteria:**
- [ ] App-role resources do not appear in the Diagnostics Services panel
- [ ] Multi-instance apps do not collide on `resource_name` in `mergeServices()`

**Labels:** `type:bug`, `area:core`, `area:ui`, `size:medium`

## Verify

- [ ] FR#7: Three issues exist on the repo with the correct labels and acceptance criteria
- [ ] No duplicate issues were created (checked before filing)
