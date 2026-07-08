# Prereq 04: `self.entities` per-app resource + protocol client

**Repo:** hassette · **Blocked by:** prereq-01, prereq-02, prereq-03 · **Blocks:** prereq-06

The hassette side of v0.1: an `EntityRegistry` core service (protocol client) plus a per-app
`Entities` child resource.

## Scope

- **Core service** (sibling of `BusService` etc.): owns handshake on
  `HASSETTE_EVENT_WEBSOCKET_CONNECTED`, re-registration after reconnect, the post-startup
  `hassette/sync` sweep, a per-instance outbound queue with batched `entity/update` flushes
  (last write per entity wins within a flush), and dispatch of `entity_command` pushes to the
  owning entity's handler via the standard handler-invocation machinery (telemetry, error
  isolation, and web-UI visibility like every other handler).
- `before_shutdown` on the core service best-effort marks all registered entities unavailable
  (same pattern as `WebsocketService.before_shutdown`); connection close guarantees the
  outcome if the push doesn't get out.
- **Per-app resource** `self.entities` (added in `App.__init__` via `add_child`, like
  `self.bus`): `add_sensor`, `add_binary_sensor`, `add_switch`, `add_button`, `add_number`,
  `add_select`. Returns typed handles with `set(value, attributes=..., available=...)`.
  Declaration raises a specific exception when the integration is absent or the handshake
  failed. App teardown marks its entities unavailable (not removed).
- `unique_id` construction `hassette_{instance_id}_{app_key}_{instance_name}_{key}`;
  duplicate `key` within an app instance raises at declaration.
- Command entities: `on_command`/`off_command`/`press`/`set_value`/`select_option` handlers;
  confirmed-by-default semantics, `assumed_state=True` opt-in.
- Handshake failure / version mismatch: fail closed, log, surface status (web UI status
  surface may be a follow-up issue; at minimum expose state on the service for the UI epic).
- Tests: unit tests with faked WS responses/pushes; deterministic race tests per CLAUDE.md
  patterns.
- Docs: new docs-site page for entity registration (per `design-completeness.md`, ships with
  the feature).

## Files

- add `src/hassette/core/entity_registry_service.py` (core service / protocol client)
- add `src/hassette/entities/` (per-app `Entities` resource, typed entity handles,
  declaration params)
- modify `src/hassette/app/app.py` (add `self.entities` child in `App.__init__`)
- modify `src/hassette/core/core.py` (register core service + `depends_on` wiring)
- modify `src/hassette/exceptions.py` (integration-absent / handshake-failed exceptions)
- add unit tests beside existing core-service tests; add docs page under
  `docs/pages/core-concepts/`
