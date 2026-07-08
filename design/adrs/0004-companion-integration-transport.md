# ADR-0004: Companion integration transport — custom WS commands over hassette's existing HA connection

**Status:** Accepted (2026-07-07)
**Relates to:** #45, #46, #594 · `design/research/2026-07-07-companion-integration-architecture/research.md`

## Context

The `epic:hacs` companion integration must let hassette register real HA entities, services,
devices, and webhooks — all of which require code inside HA's process. The two sides need a
bidirectional channel: hassette pushes registrations and state; HA pushes entity commands,
service invocations, and webhook payloads back. #45 sketched three transports (dedicated
hassette-hosted API, MQTT Discovery, REST polling); prior art added two working models:
hass-node-red (custom WS commands) and domovoy/ServEnts (plain HA services).

## Decision

The integration registers custom WebSocket commands (`hassette/*`) via
`websocket_api.async_register_command`. Hassette calls them over the WebSocket connection it
already maintains (`WebsocketService.send_and_wait` provides id-correlated request/response).
For HA→hassette traffic, hassette opens a connection-scoped subscription
(`hassette/subscribe`); the integration pushes `event_message` frames over it, and stores its
cleanup callable in `connection.subscriptions`, which HA invokes automatically on disconnect.

Consequently:

- **Auth** rides the existing WS authentication. No new secrets, ports, or pairing flows.
- **Availability is structural.** Disconnect fires the subscription cleanup; the integration
  marks that instance's entities unavailable. Reconnect re-runs handshake + idempotent
  re-registration.
- **Version skew is handled at connect** via a `hassette/handshake` exchange that fails closed.
- Payload shapes live in the shared `hassette-protocol` package (stdlib-only; voluptuous
  validates on the HA side, hassette's own Pydantic models on its side).

## Alternatives considered

- **Plain HA services (ServEnts model):** simplest HA side, but no callback channel (command
  entities, service triggering, and webhooks would need broadcast HA events), no disconnect
  signal (stale entities stay available), no handshake. Rejected as a foundation; individual
  convenience services may still be added later as an escape hatch.
- **Hassette-hosted API the integration connects to** (#45 option 1): adds network
  reachability config, a pairing secret, and a second reconnect state machine, with no
  capability the chosen design lacks. Rejected.
- **MQTT Discovery** (#45 option 2): ruled out by decision — no broker dependency, and no
  callback path for services/webhooks.

## Consequences

- `WebsocketService.dispatch` gains subscription-id routing (today it assumes all
  `type: "event"` frames are HA event envelopes).
- Hassette's long-lived token must belong to an admin user (`@require_admin` on all
  `hassette/*` commands).
- Read-only entity support needs only hassette→HA commands; command entities, services, and
  webhooks share one push envelope designed once.
- The transport works unchanged for Docker, remote hosts, and the future HA add-on
  (`epic:ha-addon`).
