# Prereq 05: `hass-hassette` integration skeleton

**Repo:** new (`hass-hassette`) · **Blocked by:** prereq-03 · **Blocks:** prereq-06

The HA-side scaffold, installable via HACS custom repository, before any entity platform
exists.

## Scope

- Repo scaffold: `custom_components/hassette/` with `manifest.json` (domain `hassette`,
  `iot_class: local_push`, `requirements: ["hassette-protocol==…"]`), `hacs.json` with
  minimum-HA pin, README, license.
- Single zero-config `config_flow` entry (one entry, no fields; abort on second).
- WS command registration: `hassette/handshake` (protocol version exchange, hub device
  creation per `instance_id`, takeover semantics for a reconnecting instance id) and
  `hassette/subscribe` (store cleanup in `connection.subscriptions`; cleanup marks the
  instance's entities unavailable). All commands `@require_admin`.
- `Store`-backed instance/definition persistence keyed by `instance_id` (schema versioned).
- CI: `hassfest` action, HACS validation action, `pytest-homeassistant-custom-component`
  suite, contract tests against `hassette-protocol` fixtures.
- Note: the first *tagged release* (required by HACS) is cut only after prereq-06 lands —
  it is housekeeping that follows prereq-06, not part of this prereq's blocking scope.

## Files

- add `custom_components/hassette/` (`__init__.py`, `manifest.json`, `config_flow.py`,
  `websocket.py`, `store.py`), `hacs.json`, `.github/workflows/` (hassfest, HACS, tests),
  `tests/`, README, LICENSE — all in the new `hass-hassette` repo
