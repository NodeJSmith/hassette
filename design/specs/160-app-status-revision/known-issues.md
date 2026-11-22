# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A load pass that bumps `status_revision` and then defers or raises sends no `apps_changed`

Status: open
Recorded: 2026-11-22 (4147)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_changes.py
- docs/pages/web-ui/python-client.md

Issue:
Writes that bump `status_revision` without a delta (block/unblock, `set_manifests`, registration) reach clients only through the `apps_changed` refetch that ends a completed load pass. Two paths bump and never send it: a config change handled while bootstrap release is still closed (`refresh_config` has already replaced the manifests, then the handler defers), and an `apply_changes` that raises inside `_reconcile_changes`. Clients keep the old status row (for example a disabled app still reading stopped) until some later refetch. The first path behaved the same on main.

Why deferred:
Both paths are rare, the consequence is a stale badge that any refetch or reconnect repairs, and the ratified posture leaves loss detection to #4217. The bootstrap-failure path the critics named ends the process, so clients reconnect and refetch anyway.

Recommended follow-up:
If stale badges are seen after a boot with HA unreachable or after a failed reload, send `apps_changed` from the deferral and failure paths, or carry `status_revision` on `AppsChangedWsMessage` so clients refetch only when behind.

Acceptance criteria:
- Every path that bumps `status_revision` without a delta is followed by an `apps_changed`, pinned by a test per path.

## KI-002: A delta lost to a publish bug leaves every client stale with only an ERROR log

Status: open
Recorded: 2026-11-22 (4147)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_instances.py

Issue:
`set_app_status` catches and logs a `publish_app_status` failure (D4). Revisions are ordered but not contiguous, so no client can tell it missed a delta, and a missed final transition stays on screen until the next refetch.

Why deferred:
It needs a bug in payload construction or serialization to happen (a full queue is handled by the too-slow close). D4 ratified log-only failure so that telemetry can't turn a start into a failure.

Recommended follow-up:
If such a failure is ever logged, fix the bug, and consider putting a resync signal on every client queue in the except branch.

Acceptance criteria:
- A caught publish failure makes every client refetch, or the failure mode is shown not to occur.

## KI-003: After a backwards clock step across a restart, old-boot rows outrank new deltas

Status: open
Recorded: 2026-11-22 (4147)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_registry.py
- docs/pages/web-ui/python-client.md

Issue:
`status_revision` is seeded from the wall clock (D1). If the host clock steps backwards across a restart (an RTC-less Pi before NTP sync, a VM resume), rows cached from the old boot carry higher revisions than the new boot's deltas, which are ignored until the next refetch. The frontend never reads `boot_id` and relies on clearing and refetching on reconnect.

Why deferred:
D1 accepted it, python-client.md documents the caveat, and the frontend clears and refetches on every reconnect.

Recommended follow-up:
If hass-hassette keeps rows across reconnects, document "refetch before applying deltas when `boot_id` changes" on `AppStatusChangedData` and in python-client.md.

Acceptance criteria:
- A consumer that follows the docs never applies a new-boot delta against an old-boot row.

## KI-004: A frontend older than its server rejects deltas carrying an unknown `AppStatus`

Status: open
Recorded: 2026-11-22 (4147)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- frontend/ws-schema.json
- frontend/src/hooks/use-websocket.ts

Issue:
`app_status` is open-typed for Python clients (`OpenAppStatus`), but the frontend's WS schema and generated validator use the closed `AppStatus` enum. A tab left open across an upgrade that adds a member rejects those deltas until it reloads. The sibling `status` field behaves the same way.

Why deferred:
The SPA ships with the server, and the window is one stale tab.

Recommended follow-up:
If `AppStatus` members start being added often, open the frontend's validation to unknown values and render them through the existing fallback, for `status` and `app_status` together.

Acceptance criteria:
- A delta with an unknown `app_status` is accepted and rendered by an older frontend.

## KI-005: Each status transition serializes its WS message inline on the lifecycle path

Status: open
Recorded: 2026-11-22 (4147)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/runtime_query_service.py

Issue:
`put_to_clients` round-trips each message through `json.dumps`/`json.loads`. This used to run in a bus listener task and now runs inside `set_app_status`.

Why deferred:
It's one small message per transition, and no trace shows a cost. performance-discipline says don't optimize without a measurement.

Recommended follow-up:
If a profile of a large multi-instance startup shows `put_to_clients` on the hot path, dump with `model_dump(mode="json")` at each publisher and skip the round-trip.

Acceptance criteria:
- A before/after trace shows the change reduced lifecycle-path time.

## KI-006: The sidebar groups an app in STOPPING under the warning group

Status: open
Recorded: 2026-11-22 (4147)
Source: pre-commit-review
Reason not fixed now: needs-decision
Affected files:
- frontend/src/components/layout/sidebar-groups.ts

Issue:
`STATUS_TO_GROUP` maps `stopping` to the warning group, a mapping that predates this branch. Now that the server rolls an app up to STOPPING whenever any instance is stopping (D7), a multi-instance app reloading one instance briefly appears under WARNING in the sidebar.

Why deferred:
Which group a transitional status belongs in is a UI design call, and UI work is parked until the redesign.

Recommended follow-up:
Decide whether STARTING and STOPPING belong with running (transitional, not a problem) or keep their own group, as part of the UI redesign.

Acceptance criteria:
- A reload of one instance of a healthy multi-instance app does not move the app into the warning group.
