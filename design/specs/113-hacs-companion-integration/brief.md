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
  hassette's existing `/apps/manifests` endpoint. Each configured app gets **one
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
  thin integration" split. Its design lives in spec 114
  (`design/specs/114-hassette-client/brief.md`): a `hassette-wire` package owns the wire
  models, `hassette-client` serves every consumer including the CLI, and both release in
  lockstep with hassette. The integration
  requires it as a **range**, never an exact pin, and the library itself must not exact-pin
  anything HA ships (core #173019; hassfest PR #181913).
- **App-declared entities remain v0.2.** Entities that apps create through `self.entities`
  (with persistence and restore) are separate from the integration-owned app devices above.
- **Two repos:** hassette (plus the client library) and `hass-hassette` (HACS layout,
  `zip_release`, real GitHub Releases, in-repo `brand/icon.png`, which has satisfied HACS
  validation since Feb 2026).
- **Cross-repo CI pins a release.** hassette's system-test and demo-stack HA containers install a
  pinned `hass-hassette` release, bumped like the HA version.
- **Status is shown HA-side.** Config entry state (setup retry, auth failed, loaded) is the
  conventional surface. The hassette-side "integration connected" indicator is dropped: hassette
  is the server now and has nothing to report.
- **Out of the epic:** retained availability, app-declared services (D8).
- **Tracker:** #45's body becomes the epic tracker; #46 stays as the `@template` leaf (entity stage).

### Proposed staging

| Stage | Scope |
|---|---|
| v0.1 | hassette: client library (spec 114). hass-hassette: single-entry URL + token config flow with reauth; coordinator polling `/apps/manifests`; one device per app with running switch, reload button, and status sensor; dynamic add and stale removal; conventional errors; tests; HACS release. Docs both sides, including reverse-proxy/forward-auth guidance. |
| v0.2 | hassette: topic-subscription channel on its WS server (today broadcast-only), which also lets the coordinator switch from polling to push; name-based instance routes. hass-hassette: per-instance entities; app-declared persistent entities (sensor, binary_sensor, switch, button, number, select), coordinator-diff sync fed by the subscription, restore (`RestoreEntity` vs `RestoreDataUpdateCoordinator`, to decide), stale-device removal only when certain. `self.entities` app API. |
| v0.3 | Webhooks: the integration registers HA webhooks and forwards payloads to a hassette endpoint; unblocks #594. |
| v0.4+ | `@template` (#46); HACS default store; Supervisor add-on discovery (#71). |

### Spec decomposition (v0.1)

v0.1 spans two repos, and `mine-orchestrate` runs inside one, so it splits along its
dependency edges (decided 2026-09-24 during `/mine-define`):

| # | Unit | Repo | Form | Depends on |
|---|---|---|---|---|
| A | Start/reload failures return `500` with the app's `error_message` instead of `202` | hassette | #2368 (done: PR #2370, merged 2026-09-25) | — |
| B | `hassette-wire` contract package and `hassette-client` library, with the CLI moved onto it | hassette | spec 114 (issues, then a slim spec) | — (parallel with A) |
| C | The integration: config flow, coordinator, platforms, errors, tests, hassfest/HACS CI, HACS release | hass-hassette | own spec, in that repo | B published (path dep during dev) |
| D | Pinned hass-hassette install in system-test and demo HA containers, one end-to-end system test, hassette docs page | hassette | own spec | A + C released |

### Decided in the v0.1 define interview (2026-09-24)

Scope mode **Hold**. Done means dogfooded: installed from a HACS custom repo on the maintainer's
own HA, every app a device, start/stop/reload used from dashboards and automations, and D's
end-to-end test green in CI.

- **Owned by A:** a start or reload where an instance this action tried to start ends up
  `FAILED` returns `500` with that instance's `error_message`, via `_run_app_action`'s existing
  500 path (`web/routes/apps.py`). Today `_start_app_unlocked` and `reload_app` swallow init
  errors, so both answer `202`. The CLI and frontend already surface non-2xx generically.
  RED-then-GREEN tests; the 202/409 paths stay green.
- **Owned by B:** see spec 114's brief, which supersedes the B decisions first recorded here.
- **Owned by C:**
  - Quality target **Silver**, plus the Gold rules the design already meets (dynamic-devices,
    stale-devices, exception-translations, entity-translations).
  - Config flow with a user step and reauth; fields URL, token (**optional**), `verify_ssl`.
    Without a token the client sends no `Authorization` header, so a hassette that lists HA's
    address in `web_api.trusted_proxies` admits it by peer trust. A 401 without a token asks
    for one. Docs recommend the token and explain the trade-off: trusting HA's IP trusts every
    process sharing it, such as add-ons on a host-networked HA. It validates with one
    `GET /api/health` (authenticated; returns `version`): `cannot_connect`, `invalid_auth`,
    and `unsupported_version` below a `MIN_HASSETTE_VERSION` constant set to the release that
    ships A. The version is re-checked at setup, not every poll. (hassette's trusted-peer
    bypass never admits a wrong token: a presented `Authorization` header is authoritative and
    fails closed, `web/auth/__init__.py:94-102`.)
  - Coordinator polls `GET /api/apps/manifests` every **30 s** (fixed, not an option; temporary
    until v0.2 push, after which a full fetch on (re)connect remains). **A `503` (DB unavailable,
    empty list) raises `UpdateFailed` and never counts as "apps removed".** 401 raises
    `ConfigEntryAuthFailed`.
  - Stale removal keys on `in_current_config: false` or a row disappearing, not on presence in the
    list: the endpoint also returns removed apps that still have DB rows.
  - Per app: `switch` (`{app_key}_running`), `button` (`{app_key}_reload`), and an enum `sensor`
    (`{app_key}_status`) with the six `ManifestStatus` values (disabled, blocked, degraded,
    running, failed, stopped). The unique_id format is a one-way door.
  - Switch on = `running` or `degraded`; off = `stopped` or `failed`. For `disabled` and
    `blocked` apps, switch and button are unavailable and the sensor stays available.
    `autostart = false` needs no special handling. A stop from HA lasts until hassette restarts,
    documented, not fixed.
  - Every action requests an immediate refresh (no optimistic state). Errors: 404 raises
    `ServiceValidationError(not_found)`; 409 blocked raises
    `ServiceValidationError(blocked_by_filter)`; 409 bootstrap raises
    `HomeAssistantError(not_bootstrapped)`; 500 raises `HomeAssistantError(action_failed)`;
    timeout raises `HomeAssistantError`, meaning the outcome is unknown.
  - Security: the single web API token is accepted for v0.1 and stored in the config entry, never
    logged. Min HA version is derived from the APIs used.
  - Tests use `pytest-homeassistant-custom-component` at **>95% coverage**, enforced in CI.
- **Owned by D:** `tests/system/docker-compose.yml` mounts the pinned release into
  `custom_components/` and adds `extra_hosts: host.docker.internal:host-gateway` so HA can reach
  hassette on the host. One system test sets up the entry, asserts devices and entities exist,
  toggles a switch, and sees the app stop. Docs cover setup, the token, reverse-proxy bypass,
  and stop-not-persisting. Known gap: nothing tests hass-hassette against unreleased hassette
  HEAD.
- **Out of v0.1:** diagnostics, a reconfigure flow, repair issues, zeroconf/Supervisor discovery,
  per-instance entities, the HACS default store, and per-client tokens.

## Open Questions

- **Reachability docs** (D): the forward-auth bypass for token-authenticated API paths; LAN vs
  remote setups.
- **ADR-0005 interaction** (C/D docs): the add-on restricts clients to the ingress gateway when no
  host port is mapped (`web_api.allowed_client_ips`). v0.1 documents allowing HA's address;
  Supervisor discovery handing over the internal URL is v0.4+.
- **Minimum HA version** (C) for `hacs.json`: derive it from the APIs actually used, and keep a
  release-checklist step so it doesn't drift (HACS enforcement has gaps).
- **v0.2 WS subscription design** on hassette's server: topics, request ids, backpressure (today
  `RuntimeQueryService.broadcast()` drops on `QueueFull`, `core/runtime_query_service.py:413-425`).
- **ADR-0006 acceptance:** it stays Proposed until reviewed.

## Scope Boundaries

- **In (v0.1):** the v0.1 row above.
- **Deferred within the epic:** per-instance entities and app-declared persistent entities
  (v0.2), webhooks (v0.3), `@template`, the default store, and add-on discovery (v0.4+). The
  per-app devices and entities are in v0.1.
- **Out:** retained availability, app-declared services, MQTT Discovery, custom
  `hassette/*` WS commands.

## Risks and Concerns

- **Reachability friction.** HA must reach hassette's API. Remote hassette behind forward-auth
  needs a proxy bypass. This is conventional, but it's real setup friction the old transport
  avoided. Docs have to carry it.
- **v0.2 carries the deferred cost.** Building a real subscription channel on hassette's WS server
  is new server work that the old transport avoided.
- **HA release churn.** Monthly HA releases can break the integration; its own CI should track
  HA versions, alongside hassette's `ha-version-bump` cadence.
- **Release choreography:** a hassette release (server and client together, in lockstep; see
  spec 114) → the integration widens its client range → hassette's system tests bump the
  `hass-hassette` pin. Because client versions track hassette's, a range the integration pins
  too narrowly goes stale on every hassette minor release.
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
