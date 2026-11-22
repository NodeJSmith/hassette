# Design: Server-owned app status rollup and `status_revision` ordering

**Date:** 2026-11-22
**Status:** built
**Mode:** sketch
**Issues:** #4147
**Prior art:** design/research/2026-11-22-app-status-ordering/research.md

## Summary

App status reaches clients two ways, with nothing ordering one against the other:

- **REST snapshots:** `AppSummary` on `GET /api/apps`, `GET /api/apps/{app_key}` and `GET /api/telemetry/app-grid`.
- **WS deltas:** `app_status_changed`, broadcast by a PARALLEL bus listener, `RuntimeQueryService.on_app_state_changed`.

Once the frontend has seen a delta for an instance, that delta beats every later snapshot until the next reconnect. A missed or late delta therefore stays on screen. The frontend also runs a second copy of the app-level rollup (`appLiveStatus`, `configStatusOverride` in `frontend/src/utils/app-data.ts`). hass-hassette #73 will soon apply `app_status_changed` to HA entity availability through `hassette-client` `listen()` (spec 159). There, a late `starting` arriving after `running` marks entities unavailable for up to 30 s.

The change:

- **One counter.** `AppRegistry` (`src/hassette/core/app_registry.py`) owns a single `status_revision`; its seeding and every write that bumps it are defined in D1.
- **Stamped on changes.** `set_status` records the revision, with the app-level rollup computed in the same step, on each `StatusChange` it returns.
- **Delta fields.** The delta carries `status_revision`, `boot_id` and `app_status`.
- **Read-at on every snapshot.** Every `AppSummary` carries the `status_revision` it was read at.
- **Apply rule.** A delta applies only when it is strictly newer than the row, so ties go to the snapshot.
- **Direct publish.** The delta goes out from `set_app_status` (`src/hassette/core/app_lifecycle_instances.py`) through a new `RuntimeQueryService.publish_app_status`, which replaces the bus listener.
- **Rollup moves to the server.** The rollup gains STARTING/STOPPING, and the frontend derivation is deleted.
- **Rename.** The integration counter (on the listing and on spec 159's entity messages) becomes `entity_revision` (D5).

Homes of new state and behavior:

- **Counter and rollup function:** `AppRegistry` (`_status_revision`, and one `app_status(app_key)` rollup extracted from `build_manifest_info`). It is the single rollup used by the write-time `StatusChange` and by every `overlay_runtime_state` branch, including the no-manifest case, where only the DISABLED and BLOCKED checks are skipped, so a removed app reads STOPPING while its instances shut down and FAILED or DEGRADED while a flagged entry remains. The existing `set_status` DEBUG line gains the revision, and `publish_app_status` logs at DEBUG with the revision and client count. Its agreement with the delta is specified in D2.
- **Per-change revision and rollup:** `StatusChange`.
- **Snapshot field:** `AppManifestInfo.status_revision` (`src/hassette/schemas/app_snapshots.py`), mapped to `AppSummary.status_revision` (`wire/src/hassette_wire/apps.py`) by `app_summary_from` (`src/hassette/web/mappers.py`).
- **Delta fields:** `AppStatusChangedData` (`wire/src/hassette_wire/ws.py`).
- **Publish:** `RuntimeQueryService.publish_app_status` and the shared synchronous `put_to_clients` (`src/hassette/core/runtime_query_service.py`).
- **Enum members:** `AppStatus.STARTING`/`STOPPING` (`wire/src/hassette_wire/enums.py`).
- **Frontend apply rule:** one shared helper in `frontend/src/utils/app-data.ts`; the store (`frontend/src/state/store.ts`) keeps a per-instance and a per-app entry, each with its revision.

**Out of scope:**
- The app row's `error_message` lagging a recovery until the next refetch.
- A frontend gap check (#4217, which closes slow `/ws` clients, is being built in parallel).
- Any change to the user-facing `HassetteAppStateEvent` / `AppStateChangePayload`.
- hass-hassette's own code. #73 consumes the rule this ledger documents.

## Posture

- **Failure handling:** happy path with loud failure, except that a WS-delta publish failure is logged so it can't change a lifecycle outcome (D4). The direct publish is a synchronous `put_nowait` loop. A full queue behaves as it does today until #4217 lands. No retries.
- **Compatibility:** break freely, apart from the release-skew bookkeeping. This is pre-V1. `boot_id`, the listing `revision` and the new fields are unreleased under schema 7, and hassette, hassette-wire and hassette-client release in lockstep. Reversed-run wire diffs go in `tools/wire_compat_ignore.txt`; `tools/client_compat_ignore.txt` needs no entries. No shims.
- **Scope:** minimal and complete for #4147's ACs. Included: what D1–D9 specify. Out: the items under Summary's out-of-scope list.
- **Rollout:** ships outright. #4220 (spec 159) builds and merges first, then this change, and both ship in the same release. No flag.
- **Hardening:** project defaults. Tests pin the behaviors the decisions specify, including the ordering invariant. DEBUG log lines carry the revision. No new metrics.
- **Altitude:** build. One session builds it right after #4220 merges, against that code.

## Decisions

D1–D6 were settled with the user on 2026-11-22, while resolving the research brief's open questions (research.md, Open Questions and Options), and amended during the sketch's challenge; their options and evidence are in the brief. D7–D9 were drafted and ratified in the sketch.

### D1: What orders a snapshot against a delta?

**Situation:** Nothing orders the two channels. Three candidates were evaluated:
- a per-instance sequence on the registry entry
- reusing the listing's integration `revision`
- one global counter owned by the registry

**Deciding factor:** an ordering that survives STOPPED removing the entry (spec 154 D3) and covers every REST surface.

| | A: global `status_revision` on `AppRegistry` | B: per-instance sequence | C: reuse listing `revision` |
|---|---|---|---|
| Survives STOPPED removing the entry | yes | resets; synthetic STOPPED rows have none | yes |
| Gap detection possible | no; ordered only, since visible writes without a delta also bump | per instance only | no; declaration commits bump silently |
| Reaches detail and grid routes | yes, via `AppSummary` | needs a field per instance | listing only |
| Couples registry to integration | no | no | yes |
| Orders a snapshot against a delta across a process restart | yes, by the wall-clock seed; a clock stepping backwards across the restart breaks it until the next refetch | no; resets on restart | only paired with `boot_id` |

**Recommendation:** A.
**Reversibility:** hard once released (wire contract).
**Ratified:** Chose A, one `AppRegistry`-owned `status_revision`, seeded at construction from a microsecond wall-clock reading (so a restarted process starts above the previous one's last value and no epoch is needed to compare a snapshot against a delta), rising by exactly one for each change `set_status` returns and also on every other write that changes a snapshot's status fields (`block_app`/`unblock_apps`, manifest replacement through `set_manifests`, and NOT_STARTED registration onto a missing entry; `clear_all` runs only at exit and is excluded; `set_debug_capture` and `set_only_apps` change no status and are excluded too), never reset within a process, so two reads at one revision report identical status, over B and C, so that one counter orders all three REST surfaces against the deltas, accepting a second counter beside the entity counter and revisions that are ordered but not contiguous per delta, and accepting that a host clock stepping backwards across a restart (an RTC-less Pi before NTP sync) leaves old-boot rows outranking new deltas until the next refetch.

### D2: Where does `status_revision` travel?

**Situation:** A client compares numbers only when both channels carry one.

**Deciding factor:** every surface the frontend reads status from must be comparable.

**Recommendation:** On both channels:
- **Each delta:** `AppStatusChangedData` gains `status_revision` (the change's own revision), `boot_id`, and `app_status` (that app's rollup after the write). `boot_id` identifies the server process, as it does on the listing and spec 159's entity messages, so a consumer can tell a restart happened and reset state it keys by process; ordering doesn't need it (D1).
- **Each snapshot:** every `AppSummary` carries `status_revision`, the registry's value at the moment the route overlaid runtime state, including DB-only rows.
- **Not on `AppInstance`:** a synthetic STOPPED row has no change revision of its own.
- **No `boot_id` on `AppSummary`:** only the listing carries it.
- **Types and defaults:** `app_status` is `OpenAppStatus`, matching the sibling `status: OpenResourceStatus`, so a future member doesn't fail an older client's parse. `status_revision` (on both models), `boot_id` and `app_status` are required with no default; a default of 0 would let every delta beat an unstamped row. Hand-built `AppSummary`/`AppStatusChangedData` in tests, fixtures, `tools/client_compat_live_state.py` and `tools/generate_client_compat_fixtures.py` get updated, and `tools/check_client_floor.py` is confirmed to treat a HEAD client against a schema-6 server as unsupported.
- **`StatusChange` fields:** `status_revision` and `app_status` are required on `StatusChange`, and its existing `previous` field drops its harness-only `| None` (`src/hassette/core/app_registry.py:75-77`), since `set_status` always sets all three. The harness stops faking a registry `StatusChange` to build a bus event: `HassetteAppStateEvent` gains a field-level factory alongside `from_change` (the shape `HassetteServiceEvent.from_service_status` already has, `src/hassette/events/hassette.py`), and `simulate_app_state_changed` (`src/hassette/testing/_simulation.py:568`) calls it. The user-facing `AppStateChangePayload.previous_status` stays optional. Hand-built `StatusChange(...)` calls in tests pass real values.
- **Rollup agreement:** a delta's `app_status` equals the snapshot `status` at the same revision, pinned for a removed-with-orphan app, a disabled app and a blocked app.

**Pick instead if:** a per-instance revision becomes necessary, which would require tombstones for stopped names (spec 154 D3's rejected option C).
**Reversibility:** hard once released.
**Ratified:** Chose `status_revision` + `boot_id` + `app_status` (typed `OpenAppStatus`) on each delta and a read-at `status_revision` on every `AppSummary` (no `boot_id` there), all required with no default, with every `StatusChange` field required and the harness building its event through its own `HassetteAppStateEvent` factory, over putting the number on instances, so every status surface is comparable and skew-tolerant, accepting one repeated int per listing row and updating every hand-built construction site.

### D3: How does a client combine a snapshot and a stored delta?

**Situation:** Today a seen delta always wins, and `configStatusOverride` patches the case where a disable or block sends no delta.

**Deciding factor:** writes that produce no `StatusChange` must come out right without a special case. These are block/unblock, manifest replacement, and registration onto a missing entry.

**Recommendation:** A stored delta applies only when `delta.status_revision > row.status_revision`; otherwise the row wins, so ties go to the snapshot. The rule is the same for the web UI and hass-hassette. It covers the instance status, error, and needs-restart overlays, and the app-level badge. `configStatusOverride`, the degraded derivation and the priority reduce in `appLiveStatus`, and the `??` "flag never clears" special case are deleted. `app-detail.tsx`'s inline WS-first lookup moves to the shared helper. Writes that bump the counter without a delta (block/unblock, manifest replacement, registration; see D1) are delivered by `apps_changed`, which every such write path already ends in and which the web UI already refetches on (see Assumed), so the rule is: refetch app status on `apps_changed`, and apply a stored delta only when strictly newer than the row. The rule goes in `AppSummary.status_revision`'s docstring and in `docs/pages/web-ui/python-client.md`, which also says revisions strictly increase and may skip, so they must not be used for loss detection until #4217 specifies it.

**Pick delta-always-wins instead if** every write that changes visible status also sent a delta; it doesn't for block, disable or registration, which is why `configStatusOverride` exists today.
**Reversibility:** easy in the frontend, hard as a documented client contract.
**Ratified:** Chose strictly-newer-delta-wins with ties to the snapshot over delta-always-wins, so config and registration changes without events need no special case, accepting that consumers must write `>`, not `>=` and must refetch on `apps_changed`, and accepting that a delta sent between the page's first REST read and its first WS registration is lost until the next refetch (the same race exists on main today).

### D4: How does a status change reach `/ws` queues?

**Situation:** The bus listener runs PARALLEL. Wire order matches write order only because nothing on that path suspends before `broadcast`, and a failed `send_event` drops the WS delta (spec 154 D2's accepted limitation).

**Deciding factor:** wire order equals write order, enforced by structure rather than by luck.

**Recommendation:** `set_app_status` calls `RuntimeQueryService.publish_app_status(change)` right after `set_status` returns a change, before `record_app_change` and the `await send_event(...)`. The publish builds `AppStatusChangedData` from the change plus `IntegrationService.boot_id` (read the way `runtime_query_service.py:347` already does) and hands it to a new synchronous `RuntimeQueryService.put_to_clients(message)`, which puts it on every client queue with no await and owns the full-queue handling (the `WS_BROADCAST_CLIENT_QUEUE_FULL` counter and rate-limited warning) that today lives inside `broadcast` (`src/hassette/core/runtime_query_service.py:509-540`). `broadcast` and spec 159's `publish_entity_state` call the same helper, so drop accounting has one owner. The put loop takes no `_lock`, because it runs on the one event loop without suspending, so `broadcast` no longer holds the lock around it; `register_ws_client`/`unregister_ws_client` keep theirs. With no `RuntimeQueryService` wired (harness, web API disabled), there are no clients and nothing is sent, as in spec 159 D2. A publish failure is caught and logged with `logger.exception` inside `set_app_status`, as its existing send failure is, so it costs only the WS delta: the status, the `lifecycle_events` row and the bus event still land (this departs from spec 159 D2's no-catch because this publish runs inside the framework's start/stop decisions, where a raised bug would become an app failure). The `on_app_state_changed` listener and its subscription (`runtime_query_service.py:132-133`) are deleted. `HassetteAppStateEvent` still goes on the bus for user apps, unchanged.

**Pick the bus listener instead if** wire order stopped mattering to any consumer; hass-hassette's availability mapping is the one that needs it.
**Reversibility:** easy.
**Ratified:** Chose direct publish from `set_app_status` over the PARALLEL bus listener, so wire order equals write order and a bus send failure no longer costs the WS delta, accepting a lifecycle → `RuntimeQueryService` call (as in spec 159 D2) and that a publish bug is only logged rather than raised.

### D5: Rename the listing's integration counter?

**Situation:** `AppListResponse.revision` (from spec 158 D4) counts `IntegrationService` writes only. Spec 159 adds `EntityStateChangedData.revision` carrying the same counter. A bare `revision` next to `status_revision` invites comparing the wrong pair. Both are unreleased.

**Deciding factor:** a name that says which counter it is, while renaming is still free.

**Recommendation:** Rename both to `entity_revision`, including their docstrings, hassette-client attribute access, the frontend generated types and tests, and the `wire/src/hassette_wire/apps.py` docstring that says it "doesn't order availability". Point that docstring at `status_revision` instead. This change makes the rename after #4220 lands, so spec 159's build needs no coordination. After the rename, `rg -w revision` over `src`, `wire`, `client`, `frontend/src`, `docs` and `tests` has every remaining hit justified, and spec 159's `design.md` gets a dated `## Addendum` entry recording the rename and D4's move of `publish_entity_state` and `broadcast` onto `put_to_clients`.

**Pick keeping `revision` instead if** either name had already shipped in a release; neither has.
**Reversibility:** hard once released.
**Ratified:** Chose renaming the listing and entity-message `revision` to `entity_revision` over keeping `revision`, so the two counters can't be confused, accepting a rename across code #4220 just landed, gated by an `rg -w revision` sweep and recorded in a spec 159 Addendum (with D4's `put_to_clients` move).

### D6: Does `AppStatus` gain transitional members?

**Situation:** The UI shows STARTING/STOPPING at the app level today (frontend single-instance passthrough), and `docs/pages/web-ui/manage-apps.md:108` promises it. A server rollup over the six current members would report RUNNING while an app's only instance is in `on_initialize`.

**Deciding factor:** the server rollup must not report a state that is false.

**Recommendation:** Add `AppStatus.STARTING` and `AppStatus.STOPPING`. The cascade:
- `tally_app_statuses`/`status_counts`
- frontend `Record<AppStatus, …>` maps (`frontend/src/utils/status.ts`)
- `STATUS_STYLES` in `src/hassette/cli/output.py` (add `stopping`), with a test that every `AppStatus` member has an entry
- the `AppStatus` member docstrings in `wire/src/hassette_wire/enums.py`, rewritten to D7's order: NOT_STARTED counts toward STARTING, "running" in DEGRADED means any live instance, and RUNNING means every tracked instance is running (configured instances that aren't tracked, shown as stopped, don't count)
- the docs, including a python-client.md sentence that availability consumers use per-instance `status`, not the app-level rollup

**Pick keeping six members and editing the docs instead if** the app-level badge should never show a transitional state, leaving transitions to the per-instance rows.
**Reversibility:** hard once released.
**Ratified:** Chose adding STARTING and STOPPING over keeping six members and editing the docs, so the server rollup stays truthful during init and shutdown, accepting the enum cascade (`STATUS_STYLES`, member docstrings, docs).

### D7: How do transitional instances roll up into the app status?

**Situation:** With D6, the server rollup needs a precedence rule. Today's server rule is DISABLED > BLOCKED > DEGRADED (failed + any non-failed tracked) > RUNNING > FAILED > STOPPED, where "non-failed tracked" already counts NOT_STARTED, STARTING and STOPPING as live. The frontend's current multi-instance behavior has two problems:
- **Worst-by-priority (`STATUS_PRIORITY`):** `[running, stopping]` gives `running`, and `[running, starting]` gives `starting`. That is arbitrary and asymmetric.
- **Single-instance passthrough:** a lone `not_started` shows as `not_started`, which isn't an `AppStatus`.

The open choice is whether one transitional instance colors the whole app, or only an app with no settled RUNNING instance.

**Deciding factor:** a rule a user can predict from the instance list, identical for single- and multi-instance apps.

| | A: any transition wins over RUNNING | B: transitional only when nothing is RUNNING | C: keep the frontend's worst-by-priority |
|---|---|---|---|
| Single instance in `on_initialize` | STARTING | STARTING | STARTING |
| 3 running + 1 restarting | STARTING | RUNNING | STARTING |
| 3 running + 1 stopping | STOPPING | RUNNING | RUNNING (priority 6 > 5) |
| Symmetric for start vs stop | yes | yes | no |
| Predictable from the instance list | yes: one ordered list | yes: one ordered list plus a RUNNING exception | no: depends on priority numbers |
| Signals "something is in flux" in multi-instance apps | yes | no; the badge hides a restarting instance | partly |
| What peers do | Kubernetes Deployment reports Progressing while any replica rolls | HA groups report `on` if any member is on | none known |

Full order under A: DISABLED > BLOCKED > DEGRADED (failed + any live) > FAILED (failed, none live) > STARTING (any NOT_STARTED or STARTING) > STOPPING (any STOPPING) > RUNNING > STOPPED (nothing tracked).

**Recommendation:** A, because it is one ordered list with no exceptions. It matches single-instance behavior, and it keeps a restarting instance visible, the way DEGRADED already lets a minority condition win.
**Pick B instead if** a multi-instance app's badge should read RUNNING whenever it is serving, with per-instance rows carrying the transitions. **Pick C instead if** preserving today's exact UI output matters more than one rule.
**Reversibility:** easy (one function, plus tests and docs wording).
**Ratified:** Chose A (any transitional instance wins over RUNNING, in the single ordered list above) over B and C, to get one predictable rule for single- and multi-instance apps that keeps in-flux instances visible, accepting that a multi-instance app reads STARTING/STOPPING while one instance restarts.

### D8: What drives the app-level badge between snapshots?

**Situation:** With the rollup on the server, the frontend needs an app-level value between refetches. Today it recomputes one from instance entries.

**Deciding factor:** no rollup logic left in the frontend, with the badge current as soon as a delta lands.

| | A: store the delta's `app_status` per app | B: show `row.status`; invalidate the app queries on each delta | C: recompute from instance entries (today) |
|---|---|---|---|
| Rollup logic in the frontend | none | none | a second copy (what #4147 removes) |
| Badge latency after a change | immediate | one refetch round trip | immediate |
| Extra REST traffic | none | one refetch per delta, across up to 3 queries | none |
| Store shape | per-app `{app_status, status_revision}` beside the per-instance entries | per-instance entries only | per-instance entries only |
| Apply rule (D3) | same comparison against `row.status_revision` | n/a (row only) | n/a |

**Recommendation:** A, because it deletes the derivation without adding refetch traffic, and the per-app entry uses the same D3 comparison as the instance entries. The store clears both on reconnect, as today.
**Pick B instead if** a refetch burst per lifecycle transition is acceptable and a smaller store matters more.
**Reversibility:** easy.
**Ratified:** Chose A (store each delta's `app_status` per app with its `status_revision`, applied by the D3 comparison) over B and C, to delete the frontend rollup without adding refetch traffic, accepting a second store map cleared on reconnect.

### D9: Does the apps-page stats strip count STARTING/STOPPING apps?

**Situation:** The strip (`frontend/src/pages/apps.tsx`, `statusCounts`) counts the live app status into running, failed, degraded, stopped and disabled cells. A transitional app value isn't a key there, so today it isn't counted. With D6, the server's `status_counts` also gains STARTING/STOPPING keys.

**Deciding factor:** a strip whose cells add up without adding noise for states that last seconds.

**Recommendation:** Keep today's behavior. Transitional apps aren't counted in any strip cell, the apps-page filter chips (`FILTER_OPTIONS`, `frontend/src/pages/apps.tsx:40`) gain no starting/stopping chip so transitional apps show only under "all", and `status_counts` simply carries the two new keys.
**Pick instead if** the strip's total should always equal the app count. In that case, count transitional apps under running.
**Reversibility:** easy.
**Ratified:** Chose leaving transitional apps out of every stats-strip cell (today's behavior) over counting them under running, to keep the strip free of seconds-long states, accepting that the cells don't always sum to the app count.

## Assumed

- **Synchronous registry mutators.** Every registry write that changes what a snapshot reports is synchronous: `set_status` (the only per-instance status writer, apart from `clear_all`), `block_app`, `unblock_apps` and `set_manifests`. A counter bumped inside each mutator therefore matches stored state. Evidence: the `AppRegistry` docstring, `set_status` (`src/hassette/core/app_registry.py:85-185`) and the block/manifest mutators (`app_registry.py:324-365`); spec 154 D1.
- **The web UI already refetches on `apps_changed`.** `use-websocket.ts` invalidates the `manifests`, `manifest.prefix`, `appGrid` and `systemStatus` queries on it, and every write path that bumps without a delta runs inside a load or reload pass that ends in `HASSETTE_EVENT_APP_LOAD_COMPLETED`, which becomes `apps_changed`. Evidence: `frontend/src/hooks/use-websocket.ts:174-181`; `src/hassette/core/app_lifecycle_changes.py:450-455`; `src/hassette/core/app_lifecycle_service.py:203-228`; `src/hassette/core/runtime_query_service.py:244-251`.
- **Every lifecycle write goes through `set_app_status`**, which calls `set_status`, then `record_app_change`, then `await send_event(HassetteAppStateEvent...)`. Evidence: `src/hassette/core/app_lifecycle_instances.py:181-214`.
- **REST overlays are synchronous.** All three REST routes await one DB read, then overlay registry state with no await, so a read-at revision matches the statuses beside it. Evidence: `src/hassette/web/routes/apps.py:384-423`, `src/hassette/web/routes/telemetry.py:377-397`; research.md "Snapshot path".
- **Today's rollup lives in `build_manifest_info`**, with a comment saying the frontend mirrors it. Evidence: `src/hassette/core/app_registry.py:476-546` (comment at 494).
- **The bus listener this replaces** is `RuntimeQueryService.on_app_state_changed`. Evidence: `src/hassette/core/runtime_query_service.py:212-226`.
- **Wire models parse leniently** (pydantic default `extra="ignore"`, `OpenAppStatus`), so the released v0.65.0 client accepts the new fields and enum members, and `client_compat` passes with no ignore entries. Evidence: research.md, Option A's "client_compat" paragraph.
- **Schema 7 is unreleased.** `boot_id` and the listing `revision` are new in it, so no client-floor bump is needed if this ships in the same release. Evidence: `client/src/hassette_client/version.py`; #4392.
- **Spec 159 is ratified and builds first.** It adds the "not wired → no clients" publish path in `RuntimeQueryService`, `EntityStateChangedData.revision`, and `listen()`. Evidence: `design/specs/159-app-entities-ws-stream/design.md` D2, D5 and D8, on branch `4220`.
- **One live `Hassette()` per process**, so a process-wide counter needs no concurrency guard. Evidence: CLAUDE.md, "Rules that bite everywhere".

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- `AppRegistry.app_status` takes an optional `manifest` (defaulting to the loaded one), like `resolve_instance_infos`: `build_manifest_info` is handed a manifest, and the rollup must use the same one.
- `block_app` bumps `status_revision` only when the block reason changes, and `unblock_apps` only when it unblocked something: a write that changes nothing needs no new revision.
- `publish_entity_state` became synchronous and `IntegrationService.set_job` calls it without `await`, so both publishes share `put_to_clients` with no suspension point (D4).
- The harness factory is `HassetteAppStateEvent.from_app_status`, and `from_change` delegates to it, so the payload is built in one place.
- The D5 rename covers `IntegrationService.revision` and `AppListingSnapshot.revision` too, so the counter has one name end to end.
- The frontend keeps both delta maps in one store field, `appStatus: LiveAppStatus = {instances, apps}`, so they are written and cleared together; every helper takes the row (`app_key`, `status_revision`) instead of an app key.
- `AppStatus` members are declared in D7's rollup order, so the enum's docstring states the rule once.
- #4420 (closing a too-slow `/ws` client, the #4217 work) merged during the build; its close-and-signal handling lives in `put_to_clients`, so app-status and entity deltas get it too.
- Ship-time challenge: `app_status` without a manifest skips only the DISABLED and BLOCKED checks, replacing the Summary's earlier "STOPPED, or FAILED while flagged" rule, so a removed app still shutting down reads STOPPING rather than STOPPED (a flagged instance is stored FAILED, so FAILED/DEGRADED still fall out of the one list).
- Ship-time challenge: `RuntimeQueryService.broadcast` is deleted. `broadcast_envelope` and `build_and_broadcast` are synchronous over `put_to_clients`, and the log-hint handler and dev-reload watcher call `put_to_clients` directly, so the client-queue path has one name and one synchronous contract.
- The client-compat live state reports the busy app as STARTING (true of an app mid-start under D7) and the escaping app as STOPPING, so every `AppStatus` still appears in the fixtures.
