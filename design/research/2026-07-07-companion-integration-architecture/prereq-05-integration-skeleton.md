# Prereq 05: `hass-hassette` integration skeleton

**Repo:** new (`hass-hassette`) · **Blocked by:** prereq-03 · **Blocks:** prereq-06

The HA-side scaffold, installable via HACS custom repository, before any entity platform
exists.

## Scope

- Repo scaffold: `custom_components/hassette/` with `manifest.json` (domain `hassette`,
  `iot_class: local_push`, `requirements: ["hassette-protocol>=1,<2"]` — a **range**, never
  `==`; an exact pin that misses HA's own constraint is a hard install failure, HA issue
  #173019), `hacs.json` with minimum-HA pin, README, license.
- Single zero-config `config_flow` entry (one entry, no fields; abort on second).
- WS command registration: `hassette/handshake` (protocol version exchange, hub device
  creation per `instance_id`, takeover semantics for a reconnecting instance id) and
  `hassette/subscribe` (store cleanup in `connection.subscriptions`; cleanup marks the
  instance's entities unavailable). All commands `@require_admin`.
- `Store`-backed instance/definition persistence keyed by `instance_id` (schema versioned).
- CI: HACS validation action, `pytest-homeassistant-custom-component` suite, contract tests
  against `hassette-protocol` fixtures.

  > **Scope corrected 2026-08-07** (`design/research/2026-08-07-integration-transport-revisit/research.md`).
  > The original scope also listed a `hassfest` action and assumed core-integration rigor. For a
  > HACS *custom* integration that is heavier than required: HA's integration quality scale does
  > not apply to custom integrations, HACS does not run `hassfest`, and `==` requirement pinning
  > is unenforced. Brands-repo submission also stopped being required as of HA 2026.3. Run
  > `hassfest` if it turns out to be cheap and useful, but do not treat it as a gate.
- Note: the first *tagged release* (required by HACS) is cut only after prereq-06 lands —
  it is housekeeping that follows prereq-06, not part of this prereq's blocking scope.

## Files

- add `custom_components/hassette/` (`__init__.py`, `manifest.json`, `config_flow.py`,
  `websocket.py`, `store.py`), `hacs.json`, `.github/workflows/` (hassfest, HACS, tests),
  `tests/`, README, LICENSE — all in the new `hass-hassette` repo
