# Prereq 02 — Supervisor Connection Mode (`api_url` / `ws_url` Overrides)

**Repo:** hassette
**Depends on:** nothing
**Size:** small
**Also benefits:** reverse-proxy and split-endpoint HA setups where the REST and WS endpoints
don't share `base_url`.

## Problem

Hassette derives both HA endpoints from one field: `base_url` (default
`http://127.0.0.1:8123`) becomes REST `<base>/api/` and WS `<base>/api/websocket`
(`src/hassette/utils/url_utils.py:51`, consumed via `hassette.ws_url` / `hassette.rest_url`,
`src/hassette/core/core.py:264-270` — `ws_url` at 264-266, `rest_url` at 268-270).

The supervisor's proxy endpoints don't follow that pattern:

- REST: `http://supervisor/core/api`
- WS: `ws://supervisor/core/websocket`  ← not `<base>/api/websocket`

So no `base_url` value can express the pair. Auth is not a problem — the proxy accepts
`SUPERVISOR_TOKEN` in the standard WS `auth` message and as a REST bearer token, both of which
flow through the existing `token` field (`HASSETTE__TOKEN` env override,
`src/hassette/config/config.py:131-140`).

## Design (T4 in the research brief)

Add two optional override fields to `HassetteConfig`:

- `api_url: str | None = None` — full REST API base (e.g. `http://supervisor/core/api`)
- `ws_url: str | None = None` — full WS endpoint (e.g. `ws://supervisor/core/websocket`)

Resolution: when set, used verbatim; when unset, derived from `base_url` exactly as today.
The derivation moves behind `hassette.rest_url` / `hassette.ws_url` so all consumers
(`api_resource.py`, `websocket_service.py`) are untouched. Validation: reject setting
`api_url`/`ws_url` to values that conflict in scheme (e.g. `ws_url` with `http://`) with the
same friendly-error style as existing config validators.

The add-on's `run.sh` sets `HASSETTE__API_URL` / `HASSETTE__WS_URL` / `HASSETTE__TOKEN`; env
source precedence guarantees `hassette.toml` can't override them into a broken state.

Non-goals: no `supervisor_mode` flag, no auto-detection of `SUPERVISOR_TOKEN` in hassette
itself — all supervisor awareness stays in the add-on's run script (ADR-0005, derived-image
decision).

## Files

- Modify `src/hassette/config/config.py` — add `api_url`, `ws_url` fields + validator
- Modify `src/hassette/utils/url_utils.py` — override-aware URL construction
- Modify `src/hassette/core/core.py` — `rest_url` / `ws_url` properties consume the overrides
- Modify `tests/unit/` (config/url tests) — resolution matrix: neither set / both set / one
  set / scheme-mismatch rejection
- Modify `docs/pages/` (configuration reference page for connection settings) — document the
  two fields and the reverse-proxy use case
- Regenerate `hassette.schema.json` (config schema export) if the export script tracks
  `HassetteConfig`

## Acceptance criteria

- [ ] `HASSETTE__API_URL=http://supervisor/core/api HASSETTE__WS_URL=ws://supervisor/core/websocket`
      connects REST and WS through URLs that don't share a base
- [ ] Unset overrides reproduce today's derivation byte-for-byte (pin with a test before
      touching `url_utils.py`)
- [ ] Scheme mismatch (`ws_url: "http://..."`) fails fast at config load with a clear message
- [ ] Docs page covers the fields with the supervisor and reverse-proxy examples
