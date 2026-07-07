# Prereq 01: Hassette instance identity

**Repo:** hassette · **Blocks:** prereq-04

Hassette has no stable cross-restart instance identity — only per-app `instance_name` and the
per-run DB `session_id`. The integration namespaces devices, entities (`unique_id` prefix),
and takeover semantics by `instance_id`, so it must exist before any registration protocol
work.

## Scope

- Add `instance_id: str = "default"` to top-level hassette config (`hassette.toml`),
  validated as a slug (lowercase, `[a-z0-9_]`, length-capped) since it embeds into HA
  `unique_id`s.
- Expose it on `Hassette` (alongside `ws_url` etc.) for the protocol client.
- Surface in `hassette status` CLI output and the web UI config view (existing config
  display machinery).
- Docs: configuration reference entry; note that changing `instance_id` orphans previously
  registered HA entities (the integration's sync sweep removes them under the old id only
  when that id reconnects — document "pick once").

## Files (change verb + path)

- modify `src/hassette/config/` (top-level settings class + validation)
- modify `src/hassette/core/core.py` (expose property)
- modify CLI status output + web config endpoint where config fields are listed
- add unit tests beside existing config validation tests
