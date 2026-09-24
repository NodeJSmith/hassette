# Brief: HACS Companion Integration — Re-staged

**Date:** 2026-09-24
**Status:** explored — **every decision here is provisional** until `/mine-define` for the first
spec. Revised the same day after a challenge pass, prior-art research, and a
convention-alignment review.

## Idea

Hassette talks to Home Assistant as an external client, so it cannot create real HA registry
objects: `set_state` entities vanish on HA restart, and native services, devices, and webhooks
all need code inside HA's process. A companion HACS integration (`hass-hassette`, domain
`hassette`) closes that gap. None of the July/August design is built, and the tracker holds only
two stale issues (#45, #46). This brief re-stages the epic around what the maintainer wants
first (control of hassette's apps from HA, then app-declared entities) and aligns the design with HA/HACS convention.

**Terminology:** a running hassette process is a **hassette server**. "Instance" always means an
**app instance** (one configured copy of an app under an `app_key`).

**Governing constraint:** match HA/HACS conventions. Any divergence needs a very strong, stated
reason. That constraint is what reversed the transport decision (below).

## Key Decisions Made

- **Conventional transport: the integration is an API client of hassette** (ADR-0006, proposed;
  supersedes ADR-0004's T1). Every core integration backed by a separate server (zwave_js,
  esphome, matter, music_assistant) connects out to it. Custom `websocket_api` commands are
  documented as a frontend extension point, and hass-node-red is the only known external process
  that drives HA through them. This removes the custom `hassette/*` WS commands, `WebsocketService`
  subscription routing (July prereq-02), the pending-call/`service/result` machinery,
  `hassette/ready`, and the admin-token requirement.
- **Exactly one hassette server per HA.** `"single_config_entry": true` in the manifest (HA
  2024.3+) makes HA reject a second entry, which is the conventional way to enforce it. Linking
  multiple hassette servers has no expected users and only adds complexity. The config flow takes
  hassette's URL and API token and validates by connecting (`test-before-setup`). Reauth flow on
  401. Zeroconf and Supervisor add-on discovery come later. No per-server `instance_id` exists anywhere (July
  prereq-01 is dropped): its only purpose was telling hassette servers apart. v0.2 entity unique_ids
  only need to be unique within the `hassette` domain (`{app_key}_{instance_name}_{key}`).
- **v0.1 represents hassette's apps as devices and entities, not services.** HA's convention for
  a set of controllable things the integration knows about is devices and entities picked from
  the standard pickers, not a service with a typed identifier. A `DataUpdateCoordinator` polls
  hassette's existing `/apps` and `/apps/manifests` endpoints. Each configured app gets **one
  device** (`Hassette › motion_lights`, identified by `app_key`) with:
  - a `switch`: on = running; turning it on/off calls `/apps/{app_key}/start|stop`
  - a `button`: reload (`/apps/{app_key}/reload`)
  - a status `sensor` (running / failed / stopped / blocked)

  Apps are discovered automatically, so nobody types `app_key`s (this is the `dynamic-devices`
  rule). Devices for apps that leave hassette's config are removed. hassette's manifest list is
  authoritative, which satisfies `stale-devices`' "only when certain". Everything goes
  unavailable when hassette is unreachable (`entity-unavailable`). No custom services in v0.1.
  Actions are awaited REST calls with a normal timeout, and success means **accepted** (the
  REST API's `202`). The coordinator refresh then reflects the new state. No new hassette
  transport is needed. This supersedes the earlier "services first, no devices" slice: devices
  were cut when they meant a hand-built sync sweep under the old transport; under this one
  they're the stock coordinator pattern.
- **App-level only in v0.1; instances later.** Entities control the whole app (all its instances).
  hassette's instance routes address instances by positional index
  (`/apps/{app_key}/instances/{index}/…`, `routes/apps.py:292`), and default `instance_name`s are
  positional too (`f"{class_name}.{idx}"`, `config/classes.py:192`). Neither is stable enough for
  HA unique_ids. Per-instance entities need name-based instance routes first.
- **Fail fast, with conventional errors.** If hassette is unreachable or not ready, an entity
  action (switch toggle, button press) raises immediately (zwave_js precedent:
  `services.py:358`); HA's entry-retry machinery handles reconnecting. `ServiceValidationError` covers caller faults
  (`not_found`, `blocked_by_filter`); `HomeAssistantError` covers action failures
  (`not_bootstrapped`, timeout, `failed`). All carry `translation_key`s. A timeout reads as
  "outcome unknown". Start and stop converge on a target state and are safe to retry (start
  no-ops for already-running instances, `app_lifecycle_service.py:509-512`; stop of an app with
  no running instances returns quietly, `:663-665`). Reload is stop-then-start under the app-key lock
  (`:671-705`), so repeating it restarts the app again but still ends at "running". **Reload hides
  failures:** `reload_app` catches every exception except `AppBlockedError`, logs it, and returns,
  so the route still answers `202` (`:704-705`). The button therefore cannot report a failed
  reload itself; HA learns of it only when the next coordinator refresh shows the status sensor
  as `failed`. See Open Questions.
- **Integration idioms (quality scale):** state in `entry.runtime_data` (`runtime-data`);
  `has_entity_name` with the app device as the name owner; `ConfigEntryNotReady` at setup when
  hassette is unreachable; log-once-when-unavailable; any services added later are registered in
  `async_setup` (`action-setup`). Don't copy hass-node-red's older idioms.
- **A hassette API client library on PyPI** holds the wire logic: the conventional "library +
  thin integration" split. It lives in this repo with its own release-please package entry and
  publish workflow (`codegen/` is *not* a publishing precedent: it has never been published).
  The integration requires it as a **range**, never an exact pin, and the library itself must not
  exact-pin anything HA ships (core #173019; hassfest PR #181913). The same library could later
  serve the thin-CLI-client idea from the August revisit.
- **App-declared entities remain v0.2.** Entities that apps create through `self.entities`
  (with persistence and restore) are separate from the integration-owned app devices above.
- **Two repos:** hassette (plus the client library) and `hass-hassette` (HACS layout,
  `zip_release`, real GitHub Releases, in-repo `brand/icon.png`, which has satisfied HACS
  validation since Feb 2026).
- **Cross-repo CI pins a release.** hassette's system-test and demo-stack HA containers install a
  pinned `hass-hassette` release, bumped like the HA version. The client library stays 0.x until
  the integration's end-to-end test has exercised it.
- **Status is shown HA-side.** Config entry state (setup retry, auth failed, loaded) is the
  conventional surface. The hassette-side "integration connected" indicator is dropped: hassette
  is the server now and has nothing to report.
- **Out of the epic:** thin CLI client (adjacent: it may reuse the library, but tracked
  separately), retained availability, app-declared services (D8).
- **Tracker:** #45's body becomes the epic tracker; #46 stays as the `@template` leaf (entity stage).

### Proposed staging

| Stage | Scope |
|---|---|
| v0.1 | hassette: client library (0.x) + publish plumbing. hass-hassette: single-entry URL + token config flow with reauth; coordinator polling `/apps`; one device per app with running switch, reload button, and status sensor; dynamic add and stale removal; conventional errors; tests; HACS release. Docs both sides, including reverse-proxy/forward-auth guidance. |
| v0.2 | hassette: topic-subscription channel on its WS server (today broadcast-only), which also lets the coordinator switch from polling to push; name-based instance routes. hass-hassette: per-instance entities; app-declared persistent entities (sensor, binary_sensor, switch, button, number, select), coordinator-diff sync fed by the subscription, restore (`RestoreEntity` vs `RestoreDataUpdateCoordinator`, to decide), stale-device removal only when certain. `self.entities` app API. |
| v0.3 | Webhooks: the integration registers HA webhooks and forwards payloads to a hassette endpoint; unblocks #594. |
| v0.4+ | `@template` (#46); HACS default store; Supervisor add-on discovery (#71). |

### Spec decomposition (v0.1, provisional)

**One spec** covers v0.1. The hassette-side work is now just the client library (wrapping the
existing REST endpoints) and its release-please/PyPI plumbing, which is too small to be its own
spec. The spec covers: the client library; `hass-hassette`'s config flow, coordinator, app devices and entities, errors, and
tests with `pytest-homeassistant-custom-component` (whose version tracks HA core); the HACS
release; and the pinned install in hassette's system-test/demo HA containers for the end-to-end
test. The library stays 0.x until that end-to-end test passes. Later stages get their own specs.

## Open Questions

- **Client library name and home** (`hassette-client` in `client/`?), and whether it shares
  models with hassette's web layer or keeps its own.
- **Switch semantics edge cases:** what the switch shows for a failed app (off plus the status
  sensor saying failed?), for `autostart = false` apps, and for apps blocked by the `--app`
  filter (unavailable?). Also: a stop issued from HA doesn't survive a hassette restart if the app
  has `autostart = true`, so the switch flips back on. Document that, or decide it's wrong.
- **Poll interval** for the coordinator until v0.2's push channel exists.
- **`test-before-setup` check:** which endpoint the config flow calls to validate URL + token
  (likely `/health` plus an authenticated call).
- **Token type** for the integration: reuse hassette's existing web API token, or a dedicated
  per-client token.
- **Reachability docs:** the forward-auth bypass for token-authenticated API paths; LAN vs remote
  setups.
- **ADR-0005 interaction:** the add-on restricts clients to the ingress gateway when no host port
  is mapped (`web_api.allowed_client_ips`). The integration in HA core must be allowed, ideally
  via Supervisor discovery handing it the internal URL.
- **Minimum HA version** for `hacs.json`: derive it from the APIs actually used, and keep a
  release-checklist step so it doesn't drift (HACS enforcement has gaps).
- **Reload failure reporting:** fix `reload_app` so a failed reload surfaces as an error (non-2xx)
  instead of a `202`, or accept that the status sensor is the only failure signal. Fixing it is
  hassette-side work that belongs in v0.1 if chosen.
- **v0.2 WS subscription design** on hassette's server: topics, request ids, backpressure (today
  `RuntimeQueryService.broadcast()` drops on `QueueFull`, `core/runtime_query_service.py:413-425`).
- **ADR-0006 acceptance:** it stays Proposed until reviewed.

## Scope Boundaries

- **In (v0.1):** the v0.1 row above.
- **Deferred within the epic:** per-instance entities and app-declared persistent entities
  (v0.2), webhooks (v0.3), `@template`, the default store, and add-on discovery (v0.4+). The
  per-app devices and entities are in v0.1.
- **Out:** thin CLI client, retained availability, app-declared services, MQTT Discovery, custom
  `hassette/*` WS commands.

## Risks and Concerns

- **Reachability friction.** HA must reach hassette's API. Remote hassette behind forward-auth
  needs a proxy bypass. This is conventional, but it's real setup friction the old transport
  avoided. Docs have to carry it.
- **v0.2 carries the deferred cost.** Building a real subscription channel on hassette's WS server
  is new server work that the old transport avoided.
- **HA release churn.** Monthly HA releases can break the integration; its own CI should track
  HA versions, alongside hassette's `ha-version-bump` cadence.
- **Release choreography:** library → integration → hassette pin. Keep the library 0.x and make
  additive changes to keep this rare.
- **Platform issues outside our control:** requirements that install but won't import on HAOS
  2026.4+ (core #171055). Document in troubleshooting.

## Codebase Context

- **Built so far:** nothing for this epic.
- **Reusable:** REST app actions at app and instance level (`src/hassette/web/routes/apps.py`),
  `202` semantics and a 409 error taxonomy already defined (`:144-167`); health endpoints
  (`routes/health.py`: `/health`, `/health/live`, `/health/ready`); web API token auth
  (`src/hassette/web/auth/`); `AppLifecycleService` admission (`REJECT_IF_UNRELEASED`).
- **Needs building (v0.2):** the WS route at `src/hassette/web/routes/ws.py` accepts two
  client→server message types (`ping`, `subscribe`) and has no request ids; fan-out happens in
  `RuntimeQueryService.broadcast()` (`core/runtime_query_service.py:413`), which drops on
  `QueueFull`.
- **Design docs:** ADR-0006 (proposed), ADR-0004 (marked proposed-superseded), July research
  (marked superseded in part), August transport revisit (historical),
  `design/research/2026-09-24-hacs-integration-prior-art/research.md`.
- **Related issues:** #45 (tracker), #46 (`@template`), #594 (webhooks, v0.3), #71 (add-on,
  discovery in v0.4+).
