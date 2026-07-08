# Prereq 02: WebSocket subscription routing

**Repo:** hassette · **Blocks:** prereq-04

`WebsocketService.dispatch` assumes every `type: "event"` frame is an HA event envelope and
funnels it to `create_event_from_hass`. Integration pushes arrive as `event_message` frames
carrying the subscription's message id — they must be routed to a registered handler instead
of being parsed as HA events.

## Scope

- Add a subscription routing table: `dict[int, handler]` mapping subscription message ids to
  async handlers. `dispatch` checks the frame's `id` against the table before falling through
  to the HA-event path (the existing all-events subscription id can itself live in the table,
  making routing uniform).
- Registration API on `WebsocketService`: subscribe-with-handler that sends the command via
  `send_and_wait` and installs the route atomically; routes cleared in `partial_cleanup` /
  `cleanup` alongside `_subscription_ids`.
- Handler errors are isolated (log + continue), matching `dispatch`'s existing behavior.
- Regression tests: routed frame reaches handler; unknown id falls through to HA-event path;
  routes cleared on reconnect (follow the startup-race test pattern from CLAUDE.md — gate
  with `asyncio.Event`, no sleeps).

## Files

- modify `src/hassette/core/websocket_service.py`
- add/extend unit tests for dispatch routing
