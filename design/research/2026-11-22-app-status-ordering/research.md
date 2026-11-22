---
proposal: "Make the server own the app-level status rollup, and give REST snapshots and WS app_status_changed deltas a shared ordering so a client can tell which is newer (issue #4147)."
date: 2026-11-22
status: Draft
flexibility: Exploring
motivation: "The web UI can show a stale or wrong app status, and hass-hassette #73 will map app_status_changed onto HA entity availability, where a late `starting` after `running` marks entities unavailable for up to 30 s."
constraints: "Pre-V1: clean breaks, no compat shims. hassette, hassette-wire and hassette-client release in lockstep. Report client_compat impact. Keep it small and don't add guards for failures you can't name. The registry stays the single owner of app status (spec 154)."
non-goals: "Implementing anything. Redesigning the 159 ledger beyond naming which decisions are affected."
depth: deep
---

# Research Brief: Server-owned app status rollup and snapshot/delta ordering (#4147)

**Initiated by**: issue #4147 (from spec 154's ship-time challenge, Findings 6 and 9) and its 2026-11-22 comment naming hass-hassette #73 as a second consumer.

## Bottom line

Give `AppRegistry` one status counter, `status_revision`. `set_status` bumps it by exactly one on every change it returns, and stamps it on the `StatusChange` together with the app-level rollup computed in the same synchronous step. Two things carry it:

- **The delta.** `app_status_changed` carries `status_revision`, `boot_id` and `app_status`.
- **Every `AppSummary`.** Each summary carries the `status_revision` it was read at, which is the Kubernetes list-`resourceVersion` model.

A client keeps a delta only while `delta.status_revision > row.status_revision`. Otherwise the row wins, and ties go to the row. Publish the delta straight from `set_app_status` rather than through the PARALLEL bus listener, the same shape as 159 D2. The frontend's derivation then reduces to one comparison and can be deleted.

Don't reuse the listing's integration `revision`, and don't put a per-instance sequence on snapshot rows (the reasons are under Options). One question needs an answer before this is built: whether `AppStatus` gains `STARTING`/`STOPPING`. The UI shows those at the app level today, and the docs promise them (see Open Questions).

## Context

### What prompted this

Two copies of one rule, and two channels with no shared order:

1. **Two rollups.** `AppRegistry.build_manifest_info` (`src/hassette/core/app_registry.py:476-546`) derives DISABLED > BLOCKED > DEGRADED > RUNNING > FAILED > STOPPED. The frontend re-derives it in `appLiveStatus` (`frontend/src/utils/app-data.ts:125-145`), and the server's own comment at line 494 says the frontend "mirrors this rollup rule (#4147)". That is Direct evidence that the duplication is known and tracked.
2. **Unordered snapshot and delta.** Once the store holds an `app_status_changed` entry for an instance, that entry outranks every later snapshot (`instanceLiveStatus`, `app-data.ts:151-157`). The entry is dropped only on reconnect (`handleWsConnected`, `frontend/src/state/store.ts:231-255`). Spec 154 records the resulting staleness as an accepted limitation (`design/specs/154-registry-owns-app-status/design.md:229`). That line widens D2's limitation to every status event and files the fix as #4147.

### Current state

**Write path.** `AppInstanceLifecycleMixin.set_app_status` (`src/hassette/core/app_lifecycle_instances.py:181-214`) is the only lifecycle writer, with 14 call sites under `src/`. It calls `registry.set_status` (sync, returns `StatusChange | None`), writes a lifecycle row, then `await`s `hassette.send_event(HassetteAppStateEvent.from_change(change))`. If the send fails, it logs at ERROR and doesn't re-raise.

**WS path.** `RuntimeQueryService.on_app_state_changed` (`src/hassette/core/runtime_query_service.py:213-227`) is a bus listener. It builds `AppStatusChangedData` (`wire/src/hassette_wire/ws.py:10-26`) and `broadcast`s it to every client queue (`runtime_query_service.py:509-538`, `put_nowait` per queue, dropped and counted when a queue is full). Framework listeners run PARALLEL: `run_parallel` spawns a task per delivery (`src/hassette/execution_mode.py:374-393`, `src/hassette/bus/invoker.py:228-238`). The issue comment states that wire order matches event order only because nothing on that path suspends before `broadcast`, which is Direct from the author. The code reading supports it: `broadcast`'s `asyncio.Lock` is never held across an await, so acquiring it doesn't suspend.

**Snapshot path.** The frontend reads status from three REST surfaces, all built from `AppSummary`:

| Surface | Route | Frontend query | Status consumers |
|---|---|---|---|
| `AppListResponse` | `GET /api/apps` (`web/routes/apps.py:384-401`) | `useManifests` | sidebar, `app.tsx` failed-apps banner, command palette |
| bare `AppSummary` | `GET /api/apps/{app_key}` (`routes/apps.py:409-423`) | `useManifest` | app detail page |
| `AppGridResponse` | `GET /api/telemetry/app-grid` (`web/routes/telemetry.py:377-397`) | `appGrid` | apps page and table rows |

Each route awaits one DB read, then overlays registry state synchronously, so a counter read in that overlay step is consistent with the statuses it accompanies.

**The listing `revision` (the one at `app_snapshots.py:198`).** It counts `IntegrationService` writes only: a declaration commit (`integration_service.py:204`) and a changed `set()` (`integration_service.py:299`). It never moves on a status change. Its own wire docstring says so: "It doesn't order availability: starting or stopping an instance changes its `status`, not `revision`" (`wire/src/hassette_wire/apps.py:152-156`). It goes out only on `GET /api/apps`, per spec 158 D4. `boot_id` and `revision` are **unreleased**: `v0.65.0` reports API schema 6 and has no `boot_id`, while HEAD is at schema 7 (#4392). Both can still be renamed or redefined at no compat cost.

**Frontend consumers of the derivation:** `utils/app-data.ts` (`appLiveStatus`, `instanceLiveStatus`, `instanceLiveError`, `instanceLiveNeedsRestart`, `appNeedsRestart`, `configStatusOverride`), `pages/apps.tsx`, `pages/apps-table-row.tsx`, `pages/app-detail.tsx` (lines 160-165 use their own inline WS-first lookup), `components/app-detail/multi-instance.tsx`, `components/app-detail/app-detail-header.tsx`, `components/layout/sidebar.tsx`, `sidebar-groups.ts`, `palette-items.ts`, `app.tsx`, and `utils/status.ts`.

### What the frontend's extra logic does beyond the server rule

The degraded test itself matches the server. Failed plus any status other than failed or stopped is DEGRADED on both sides. A "stopped" instance on the server is an untracked configured name (`build_manifest_info`'s synthetic STOPPED), so it doesn't count. Three behaviors go beyond the server rule:

1. **Transitional app-level states.** With one instance, `appLiveStatus` returns that instance's live `ResourceStatus`: `starting`, `stopping`, `not_started`. With several and no degradation, it returns the worst by `statusPriority` (`utils/status-priority.ts`). The server's `AppStatus` has no transitional members, so the server reports RUNNING while an instance is STARTING (spec 154 D4, Direct). The docs promise the frontend's behavior: "The parent badge can also briefly show a transitional state such as `STARTING` or `STOPPING`" (`docs/pages/web-ui/manage-apps.md:108`). The priority reduce also gives arbitrary answers, such as `[running, stopping]` → `running` and `[not_started, not_started]` → `not_started`.
2. **Config states override live data.** `configStatusOverride` lets the cached `row.status` DISABLED/BLOCKED beat any WS entry, because a disable or block sends no delta. Block changes go through `reconcile_blocked_apps` (`core/app_lifecycle_config.py:144-168`), and manifest changes through `set_apps_configs` (line 79). Neither touches `set_status`. Both run inside load passes that end in `apps_changed`.
3. **Membership comes from the row.** Store entries for names the row doesn't list are ignored. This keeps working unchanged.

## Feasibility Analysis

### What would need to change (Option A, recommended)

| Area | Files affected | Effort | Risk |
|---|---|---|---|
| Registry counter and rollup | `core/app_registry.py` (counter, `set_status` bump, `app_status()` extracted from `build_manifest_info`, stamping `AppManifestInfo`); `schemas/app_snapshots.py` (`AppManifestInfo.status_revision`) | Low | High fan-in: every app response goes through `build_manifest_info`/`overlay_runtime_state` |
| `StatusChange` → wire | `StatusChange` gains `status_revision`, `app_status`; `core/app_lifecycle_instances.py` (`set_app_status` publishes directly); `core/runtime_query_service.py` (a `publish_app_status(change)` replaces the `on_app_state_changed` listener and its registration) | Low–Med | The direct publish must not suspend between `set_status` and the queue puts (the same invariant 159 D2 states) |
| Wire models | `wire/src/hassette_wire/ws.py` (`AppStatusChangedData` + `status_revision`, `boot_id`, `app_status`); `wire/src/hassette_wire/apps.py` (`AppSummary.status_revision`; rewrite `AppListResponse.revision`'s "doesn't order availability" docstring); `wire/.../enums.py` only if `AppStatus` grows | Low | Wire contract once released |
| Web mapping | `web/mappers.py` (`app_summary_from`) | Low | — |
| Frontend | `utils/app-data.ts` (derivation deleted, revision compare added), `state/store.ts` (entries carry `status_revision`; per-app rollup map), `hooks/use-websocket.ts`, plus the ten cascade files listed under Current state | Med | Many small call-site edits; the exhaustive switch and generated types catch misses |
| Generated | `frontend/openapi.json`, `frontend/ws-schema.json`, `frontend/src/api/generated-types.ts`, `ws-types.ts`, `ws-validator.generated.ts` (via `uv run python scripts/export_schemas.py --types`) | Low | CI git-diff checks |
| Compat bookkeeping | `tools/wire_compat_ignore.txt` (reversed-run "removed the required property `status_revision`" for `GET /api/apps`, `GET /api/apps/{app_key}`, `GET /api/telemetry/app-grid`, plus the WS schema's new required fields); `tools/client_compat_live_state.py` / `tools/generate_client_compat_fixtures.py` if their mocked registry must now provide the counter | Low | See client_compat below |
| Python tests | `tests/unit/core/test_app_registry_set_status.py`, `test_app_registry_snapshot.py`, `test_runtime_query_service.py`, `tests/unit/test_ws_models.py`, `tests/unit/web/test_mappers.py`, `tests/support/web_manifest_helpers.py`, `tests/integration/web_api/test_ws_endpoint.py`, `tests/e2e/test_websocket.py`, `tests/e2e/mock_fixtures/manifests.py`, `wire/tests/` | Med | Constructors of `AppSummary`/`AppManifestInfo` need the new field |
| Frontend tests | `utils/app-data.test.ts`, `state/store.test.ts`, `hooks/use-websocket.test.ts`, `pages/apps.test.tsx`, `apps-table-row.test.tsx`, `app-detail.*.test.tsx`, `components/layout/sidebar*.test.*`, `palette-items.test.ts`, `app.test.tsx`, `test/factories.ts` | Med | — |
| Docs | `docs/pages/web-ui/python-client.md` (apply rule for availability, next to 159's streaming section); `docs/pages/web-ui/manage-apps.md:108` (transitional badge; depends on the open decision) | Low | — |

New tests the ACs need:

- **Registry:** two back-to-back changes get consecutive revisions, and a snapshot read afterwards carries the second.
- **Direct publish:** two back-to-back `set_app_status` calls reach a registered client queue in revision order. This pins the invariant.
- **Frontend (AC 3):** a store entry at revision 4 (`starting`) and a refetched row at `status_revision` 6 (`running`) render `running` without a reconnect.

### What already supports this

- **`set_status` is synchronous and the single writer** (spec 154 D1). A counter bumped inside it is monotonic and consistent with the stored state at no cost, because there is one event loop and one live `Hassette()` per process (CLAUDE.md, core-startup rule).
- **`StatusChange` is already the frozen record** of each transition that gets an event (`app_registry.py:69-82`). Adding the revision and rollup there keeps their derivation in the registry. The bus listener can't compute the rollup, because by the time it runs the registry may have moved past the change.
- **Read-then-overlay with no await.** All three REST routes overlay the registry synchronously after their DB read, so a read-at revision is exact.
- **159 D2 sets the precedent for direct publish.** `IntegrationService.set_job` calls a `RuntimeQueryService` publish method inline, and the method finds no clients when the service isn't wired.
- **The schema-7 bump is unreleased.** If this lands before the next release, the client floor needs no further bump (`client/src/hassette_client/version.py:11-30`, "one bump per release").
- **Lenient parsing.** Wire models use pydantic's default `extra="ignore"`, and `AppStatus` is `OpenAppStatus` (lenient), so added fields and enum values don't break a released client.

### What works against this

- **STOPPED removes the entry** (spec 154 D3). Any per-instance counter stored on the entry is lost at a stop, and a configured name with no entry is served as a synthetic STOPPED row with no history. That rules out per-instance sequence numbers on snapshot rows (Option variants, below).
- **Some writes change visible state without a `StatusChange`.** Registration onto a missing entry (STOPPED → NOT_STARTED, spec 154 D4), block/unblock, and manifest replacement are examples. Under the revision model these are visible only through snapshots. That is correct as long as ties go to the snapshot, but the tie rule has to be stated wherever consumers read it.
- **Two counters on adjacent messages.** The listing's `revision` (entities) and the new `status_revision` live side by side, and 159's `EntityStateChangedData.revision` is a third place carrying the entity counter. Without careful naming, hass-hassette code will compare the wrong pair.

## Options Evaluated

All options share one requirement. The app-level rollup must be computed in `set_status`, in the same synchronous step as the write, and carried on the change. If a bus listener computes it later, it can stamp revision N with state from N+1.

### Option A: Registry-owned `status_revision`, read-at on every `AppSummary`, stamped on each delta, published directly (recommended)

**How it works.**

- **Server.** `AppRegistry` holds `_status_revision: int` (0 at construction, never reset by `clear_all`). `set_status` increments it once for each change it returns and puts it on `StatusChange`, together with `app_status`, the rollup for `app_key` after the write. `build_manifest_info`, `build_orphaned_flag_info`, and the DB-only branch of `overlay_runtime_state` stamp `AppManifestInfo.status_revision` with the current value. The mapper copies it onto every `AppSummary`. `set_app_status` calls `RuntimeQueryService.publish_app_status(change)` before its `await send_event(...)`. The publish builds `AppStatusChangedData` from the change plus `IntegrationService.boot_id` and puts it on every queue without suspending. The bus event still goes out for user apps, unchanged.
- **Apply rule, the same for both consumers.** A snapshot row read at R reflects every change with `status_revision ≤ R`, plus later changes that carry no revision (config, block, registration). So when rendering, use a stored delta only if `delta.status_revision > row.status_revision`, and let ties go to the row. hass-hassette applies the same rule to availability per instance, within one `boot_id`.
- **Frontend.** The store keeps the latest delta per instance and the latest `app_status` per app, each with its revision. `appLiveStatus` reduces to "store entry if newer than the row, else `row.status`". Its degraded derivation, priority reduce and `configStatusOverride` branch are deleted. `instanceLiveStatus`, `instanceLiveError` and `instanceLiveNeedsRestart` use the same comparison, which also removes the "flag never clears" `??` special case. `app-detail.tsx:160-165` switches to the shared helper. The reconnect clear stays.

**Where the number lives (desired outcome 1):**

- **On both.** On the event it is the revision of that change. On the snapshot it is the read-at value, on `AppSummary`, because `GET /api/apps/{app_key}` returns a bare `AppSummary` and the grid nests one. A single field covers all three surfaces and flows into `AppRow` through `toAppRow` without new plumbing.
- **Not on `AppInstance`.** A synthetic STOPPED row has no last-change revision. A stored STOPPING delta at revision 5 would then outrank the snapshot's STOPPED forever, unless the registry kept tombstones. That is option C of spec 154 D3, which was rejected.

**Gap detection and resync (desired outcome 3):**

- **Contiguity.** The revision moves by one per broadcast change, and every `/ws` client gets every `app_status_changed` (no subscribe filter, 159 D3). So a client that sees N+2 after N knows it missed one, and refetches its status queries or the listing.
- **The resync step.** The revision compare is the resync: any later snapshot heals a miss with no reconnect (AC 3). After a reconnect, clients clear as today: the frontend clears its store, and hass-hassette re-runs `on_connected` (159 D5).
- **What can still drop a delta.** With direct publish, a bus send that raises no longer affects `/ws`. That was spec 154 D2's limitation, and its cause leaves the WS path. The one cause left on an open socket is a full client queue, which #4217 turns into a disconnect, as HA does. A client-side gap check therefore guards only against queue overflow, and only until #4217 lands. It is about five lines in `use-websocket.ts`. Build it only if #4217 isn't landing in the same window; otherwise leave the contiguity documented and skip the check.

**Pros:**
- Ordering lives in the data, not in a scheduling invariant. Out-of-order or missed deltas are harmless for any consumer that applies the rule.
- Config and registration changes without events resolve correctly through the tie rule, so the `configStatusOverride` special case goes away.
- The same rule serves the web UI and hass-hassette, and matches the listing's existing equal-or-newer / strictly-newer semantics (spec 158 D4).
- Direct publish keeps `AppStateChangePayload`, a user-facing bus payload, unchanged, so no public surface grows. It also gives `app_status_changed` the same wire-order guarantee that 159 D2 gives entity messages.

**Cons:**
- Adds a second counter beside the listing's `revision`, so naming has to keep them apart (Open Questions).
- `status_revision` repeats on every `AppSummary` of a listing: the one-int-per-response redundancy spec 158 D4 avoided for `revision`. The detail route's bare `AppSummary` is why.
- `AppSummary` on detail and grid carries a revision with no `boot_id` beside it, which is the asymmetry spec 158 D4 rejected for the entity counter. This is harmless for the frontend, which clears on reconnect, apart from a few seconds after a server restart when a REST refetch can beat the WS reconnect. hass-hassette reads only the listing, which carries `boot_id`.
- `set_app_status` gains a call into `RuntimeQueryService`. The harness and the disabled web API need the "not wired, no clients" path that 159 adds.

**Effort estimate:** Medium. The server side is small (one counter, one extracted function, one moved publish). Most of the work is the frontend cascade and its tests.

**Dependencies:** None new.

**client_compat:** `uv run nox -s client_compat` replays HTTP fixtures through the newest released client (v0.65.0). It ignores the extra `status_revision` field, so the check passes with no `client_compat_ignore.txt` entries. If `AppStatus` gains members, the lenient `OpenAppStatus` reads them as unknown values, which also passes. `check_wire_compat`'s reversed run (new client, old server) does flag the new required fields, on three routes and on `AppStatusChangedData`, so those go into `tools/wire_compat_ignore.txt` under a `# #4147:` comment, like #4219's entries. If a release is cut before this lands, the client floor moves to schema 8. Nothing tests a released client's parsing of WS messages (159 D8), so WS skew is handled by landing order (below).

### Option B: Snapshot inside the WS stream (HA `subscribe_entities` / zwave-js `start_listening` shape)

**How it works.** On connect, the `/ws` route registers the client queue and, in the same synchronous step, reads every instance's status and app rollup into a new `app_status_snapshot` message, which is queued first. Deltas follow on the same queue. Clients replace their store on each snapshot, as HA's `subscribe_entities` init message does (home-assistant-js-websocket sets `replace` on reconnect), and take live status only from the stream. HA's handler is the model: it snapshots states and attaches the listener with no `await` between, and uses no sequence numbers.

**What it needs to be correct here.** The deltas must also be published directly. With today's bus path, a change made before the snapshot read can be broadcast after it, and the old delta then overwrites the newer snapshot. So B needs A's direct publish anyway. It also needs #4217, because an ordered socket that drops silently has no gap signal.

**Pros:**
- Matches HA, zwave-js-server and matter, whose servers own both ends. No counters on the wire.
- Fixes 159 D5's Finding 10 window for status: snapshot and deltas share a socket, so no old-boot delta can land on a new-boot listing.

**Cons:**
- REST still carries status. The CLI, `hassette-client.get_apps`, and hass-hassette's 30 s poll all read it. Either clients ignore REST status for display, leaving two sources whose disagreement is invisible, or they need an ordering rule between REST and stream, which is A again.
- Config and block changes send no delta, so the stream snapshot goes stale for DISABLED/BLOCKED unless those writes also start emitting.
- It is the new WS snapshot message that spec 154 D2 rejected. It adds a message type, a wire model, validator regeneration, a store replace action, and route logic, and it conflicts with the AC wording ("a refetched snapshot newer than the last WS event").
- For hass-hassette it duplicates what the listing already delivers.

**Effort estimate:** Medium to Large.

**Dependencies:** #4217 for drop handling.

**client_compat:** The new WS message type passes the WS forward run (adding a type is allowed). HTTP is unchanged.

### Option C: Do less. Direct publish, rollup on the delta, "delta wins" kept, rely on #4217

**How it works.** Move the publish out of the bus listener (A's direct publish) and add `app_status` to `AppStatusChangedData`, computed in `set_status`. Add no counter. Keep the frontend's rule that a seen delta outranks snapshots. Once wire order equals write order and #4217 turns queue overflow into a reconnect, no nameable way remains to miss a delta on an open socket, so "latest delta wins" is correct. That is HA's position: no sequence numbers, and a drop means disconnect and resync.

**Pros:**
- Smallest wire change: one field. Server rollup becomes the only rollup, which meets AC 1.

**Cons:**
- Correctness rests on two invariants written nowhere in the data: no suspension before the queue put, and drop means disconnect. A later change to either brings the bug back silently.
- AC 2 and AC 3 as written ("a refetched snapshot newer than the last WS event replaces it") can't be met. The snapshot is never trusted over a delta.
- `configStatusOverride` has to stay, because config changes send no delta.
- hass-hassette's listing poll can never correct availability once a delta has been seen. Its "poll repairs" role (parent spec 155 D3) is lost for status.

**Effort estimate:** Small.

**Dependencies:** #4217 has to land first, or this is wrong under load.

### Variants considered and set aside

- **Per-instance monotonic sequence (issue candidate a), stored on the entry.** Spec 154 D3 removes the entry on STOPPED, so the sequence resets on restart, and synthetic STOPPED rows have none. Keeping it needs a tombstone map, which is spec 154 D3's rejected option C. A single counter stamped per change gives each instance a monotonic value anyway, the way etcd's global revision backs each Kubernetes object's `resourceVersion`. None of the prior art uses per-entity sequences to order a snapshot against deltas.
- **Reuse or extend the listing `revision` (issue candidate b).** Bumping the integration counter on status writes would technically work, since both bump sites run on the event loop. Four costs count against it:
  1. **Cross-kind reordering.** Status deltas and entity deltas would share one number but leave by different paths. A consumer keeping one watermark per instance would drop a valid status delta at 6 that arrives after an entity delta at 7, so hass-hassette would need a watermark per instance per kind.
  2. **No contiguity.** Declaration commits bump without publishing (159 D4), so gap detection is impossible.
  3. **Coupling.** The registry (no dependencies, spec 154 Assumed) would be tied to the integration subsystem.
  4. **Reach.** The number appears only on the listing, not on the detail or grid responses the UI uses.

  The only thing gained is one fewer field on the listing.

## Concerns

- **The tie rule is the contract.** Snapshot-wins-on-ties is what makes config, block, and registration changes, which carry no revision, come out right. A consumer that writes `>=` for deltas shows stale DISABLED/BLOCKED rows. Put the rule in `AppSummary.status_revision`'s docstring and in `python-client.md`, and pin it with a frontend test.
- **Direct publish invariant.** `publish_app_status` must not suspend between `set_status` returning and the last `put_nowait`, or concurrent writers on different instances reorder on the wire. This is harmless under A's rule, but it breaks gap detection with false gaps and breaks Option C outright. 159 D2 states the same invariant for entity messages, so one test pattern covers both.
- **Rollup computed at write time.** If `app_status` were computed in a bus listener or at publish time from live registry state, revision N could carry N+1's rollup. Keep it on `StatusChange`.
- **App-level fields beyond status stay client-aggregated.** `appNeedsRestart` counts flags from instance overlays, and the app row's `error_message` comes from the cached row. Neither is a status rule, so AC 1 doesn't cover them. The app row's error text can still lag a recovery until the row is refetched, as it does today. This is out of scope; mention it in the PR.
- **Maintenance.** Option A adds one concept for every consumer to learn ("compare `status_revision`; ties go to the row"), which is about the size of the two rules it deletes. Option B adds a second source of status that has to be kept consistent with REST. Over time A costs less.

## Open Questions

- [x] **Does `AppStatus` gain `STARTING` and `STOPPING`?** **Answered (2026-11-22): yes, add both.** The server rollup reports transitional app states (candidate priority: DISABLED > BLOCKED > DEGRADED > FAILED > STARTING > STOPPING > RUNNING > STOPPED), consistent with `manage-apps.md:108`. Cascades into `tally_app_statuses`/`status_counts`, the stats strip, frontend `Record<AppStatus, …>` maps (`utils/status.ts:33`) and docs.
- [x] **Naming.** **Answered: rename.** The new counter is `status_revision`; the unreleased `AppListResponse.revision` becomes `entity_revision`, and 159's unbuilt `EntityStateChangedData.revision` follows the rename.
- [x] **Does `AppSummary` carry `boot_id` too?** **Answered: no.** Only the listing carries it (for hass-hassette); the frontend clears on reconnect.
- [x] **Frontend gap check: now or never?** **Answered: skip it.** Any later snapshot repairs a miss, and #4217 (close slow `/ws` clients instead of dropping messages) turns a full queue into a disconnect; #4217 should land in the same window.
- [x] **Milestone.** **Answered: #4147 joins *HACS App Entities*** — the Done-when's "a stopped instance's entities are unavailable" depends on ordered availability through hass-hassette #73.
- [ ] **Not verified:** whether every step on today's bus path (`BusService` dispatch task → `run_parallel` → `CommandExecutor._execute`) is really free of suspension before `broadcast`. Moot under Option A's direct publish; left open only as a fact about today's code.

## Recommendation

**Option A.** The evidence supports it strongly on three counts:

- **The writer.** The registry is the single synchronous writer (spec 154), so one counter is exact at no cost.
- **The prior art.** The Kubernetes list+watch and Binance REST+WS algorithms both handle a snapshot arriving from a separate path by putting one global counter on the snapshot and on each event.
- **The tie rule.** It removes the config-override special case the frontend carries today.

Direct publish is part of the recommendation, not an extra. It keeps the user-facing bus payload unchanged, moves spec 154 D2's send-failure limitation off the WS path, and gives `app_status_changed` the same guarantee 159 D2 gives entity messages. Option B is right for systems with no REST snapshot. Here it adds a second source of status. Option C works only while two unwritten invariants hold, and it contradicts the issue's ACs.

**Composition with 159 and `listen()` (desired outcome 4):**

- **Landing order.** Build #4220 first, then #4147, both before the next release is cut. There are four reasons:
  1. 159 introduces the "`RuntimeQueryService` not wired → no clients" publish path that A's direct publish reuses.
  2. Both land under the unreleased schema-7 floor, so no second bump is needed.
  3. `listen()` never ships in a release whose `app_status_changed` lacks `status_revision`. Otherwise a newer client would raise on an older server's message, since 159's Posture ends the stream on a parse failure of a requested type, and the client floor checks only `openapi.json`, not WS.
  4. hass-hassette #73 can then use the apply rule from its first release.

  If #4147 slips past a release, bump the floor to schema 8 in its PR.
- **159 D2 needs no change.** Entity messages keep the integration revision and direct publish. Its closing note ("`app_status_changed` keeps its coincidental ordering … #4147 owns that") becomes resolved. If 159's `design.md` is `built` by then, record that as an Addendum entry, not as an edit to the body.
- **Affected but not reopened:**
  - 159 D5's accepted Finding 10 is partly mitigated: status deltas carry `boot_id`, so #73 can drop old-boot status deltas. `connected` still has none.
  - 159 D8 is unchanged: `AppStatusChangedWsMessage` only gains fields, parsed leniently.
  - 158 D4's `AppListResponse.revision` docstring ("doesn't order availability") must be rewritten to point at `status_revision`.
  - 159's planned `python-client.md` streaming section should state the availability apply rule.
- **client_compat:** no `client_compat_ignore.txt` entries for any option. A, and B's HTTP side, need `wire_compat_ignore.txt` entries for the new required fields.

### Suggested next steps
1. Settle the `AppStatus` STARTING/STOPPING question and the naming question. They change the wire shape, so they come first.
2. Sketch the change via `/mine-sketch` once #4220 has merged. The decisions above (number placement, tie rule, direct publish, rollup members, gap check) interact, and the build should reuse 159's publish path.
3. Decide on #4217's timing alongside it, since it determines whether the frontend gap check is worth writing.

## Sources

- HA `handle_subscribe_entities` (snapshot and listener with no await between them; no sequence numbers): https://github.com/home-assistant/core/blob/dev/homeassistant/components/websocket_api/commands.py
- home-assistant-js-websocket `subscribeUpdates` (replace on reconnect): https://github.com/home-assistant/home-assistant-js-websocket/blob/master/lib/states.ts
- HA `DataUpdateCoordinator` (`async_set_updated_data`, last writer wins, no versioning): https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/update_coordinator.py
- zwave-js-server `start_listening` (state in the result, then events on the same socket): https://github.com/zwave-js/zwave-js-server
- Kubernetes list+watch, `resourceVersion`, 410 Gone, bookmarks: https://kubernetes.io/docs/reference/using-api/api-concepts/
- Phoenix Presence `presence_state`/`presence_diff` with pending-diff buffering: https://phoenix.hexdocs.pm/Phoenix.Presence.html, https://github.com/phoenixframework/phoenix/blob/main/assets/js/phoenix/presence.js
- MQTT retained messages and LWT ordering caveats: https://docs.aws.amazon.com/iot/latest/developerguide/mqtt.html
- Binance snapshot + diff stream (`lastUpdateId`, `U`/`u` gap rule): https://www.binance.com/en/academy/articles/local-order-book-tutorial-part-3-keeping-the-websocket-connection, https://github.com/binance/binance-toolbox-python/blob/master/manage_local_order_book.py
- HA `websocket_api` closing slow clients (`MAX_PENDING_MSG`, `PENDING_MSG_PEAK`), as quoted in issue #4217; I didn't re-verify it against source.

All web research used `exa-search`; no fallback was needed.
