# ADR-0006: Companion integration connects to hassette as an API client

**Status:** Proposed (2026-09-24) · supersedes ADR-0004 once accepted
**Relates to:** #45, #46, #594, #71 · `design/specs/113-hacs-companion-integration/brief.md`
· `design/research/2026-09-24-hacs-integration-prior-art/research.md`

## Context

ADR-0004 chose T1: hassette connects into Home Assistant's WebSocket API and the companion
integration registers custom `hassette/*` commands plus a connection-scoped subscription for
callbacks. It rejected T3 (the integration connects out to hassette) on reachability, pairing,
and reconnect-cost grounds. The August revisit reaffirmed that, and its decisive argument was
that hassette's WS server has no command channel to reuse.

A new constraint changes the weighing. The HA-facing design must follow HA/HACS conventions
unless there is a very strong reason not to. Prior-art verification on 2026-09-24 found:

- Every core integration backed by a separately running server has **HA connect out as the
  client**: zwave_js, esphome, matter, music_assistant. It's set up by URL (plus token) in the
  config flow, or via zeroconf / Supervisor add-on discovery.
- `websocket_api.async_register_command` is documented as a **frontend** extension point. The
  only known external process that drives HA through it is hass-node-red (HACS, not core).
- T1 also forced machinery with no core precedent: services that block on an external client's
  reply, hand-rolled pending-call correlation, and an admin-token requirement.

## Decision

The `hass-hassette` integration is a conventional API client of hassette:

- **Setup:** the config flow takes hassette's URL and API token. **Exactly one hassette per HA**:
  `"single_config_entry": true` in the manifest. Supporting several hassette servers has no
  expected users.
  Reauth flow on 401. Zeroconf and Supervisor add-on discovery are later additions.
- **Transport:** the integration calls hassette's web API (REST for actions, and in v0.2 a
  subscription channel on hassette's WebSocket for pushed state). A shared **hassette API client
  library** on PyPI holds the wire logic (the conventional "library + thin integration" split),
  declared in `manifest.json` `requirements` as a range.
- **Liveness:** the integration's own connection state drives availability: `ConfigEntryNotReady`
  at setup, entities unavailable on disconnect, log-once-when-unavailable.
- **Apps are devices and entities**, discovered by the coordinator, not services with typed
  identifiers. Entity actions are ordinary awaited API calls with a normal request timeout,
  failing fast with `translation_key` exceptions.

## Consequences

- v0.1 needs no new hassette transport. A `DataUpdateCoordinator` polls the existing `/apps`
  endpoints and exposes one device per app (running switch, reload button, status sensor), with
  actions calling `/apps/{app_key}/{start,stop,reload}`.
- Deleted from the plan: custom `hassette/*` WS commands, `WebsocketService` subscription
  routing (July prereq-02), the `service/result` pending-call machinery, `hassette/ready`, and
  the admin-token requirement.
- **Reachability is now a user-setup cost.** HA must reach hassette's API. A remote hassette
  behind a forward-auth proxy needs a bypass for token-authenticated API paths. This is the same
  one-time setup as any HA integration that talks to a proxied self-hosted service. Document it.
- **ADR-0005 interaction:** the add-on's client-reachability story is bearer-token auth
  (`web_api.auth_token`) plus the optional `web_api.trusted_proxies` peer-address bypass for a
  forward-auth gateway sending no `Authorization` header (spec 091). `web_api.allowed_client_ips`
  was only ever a design artifact from the unimplemented ingress-source-guard prereq and never
  shipped — superseded by `trusted_proxies`. A bearer-authenticated client like the integration
  doesn't need peer trust at all: it just needs a reachable URL and its config-flow token,
  ideally handed the internal one via Supervisor discovery.
- **v0.2 carries the deferred cost:** pushing entity state needs a real topic-subscription
  channel on hassette's WS server, which today is broadcast-only with no request ids
  (`src/hassette/web/routes/ws.py`; fan-out in `core/runtime_query_service.py`). That's new server work, owned by hassette.
- Webhooks (v0.3) become straightforward: the integration registers the HA webhook and forwards
  payloads to a hassette endpoint.

## Alternatives considered

- **Keep T1 (ADR-0004).** Its strongest remaining argument is zero-config reachability for remote
  hassette deployments behind forward-auth. Rejected: that's a documentation and proxy-config
  cost every self-hosted HA integration accepts, not a strong enough reason to build on a
  frontend-oriented extension point and novel blocking-service machinery.
- **Plain HA services only (ServEnts model).** Still rejected, same as ADR-0004: no liveness signal.
