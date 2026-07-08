# Prereq 04 — `hassette-addon` Repo Skeleton

**Repo:** hassette-addon (new)
**Depends on:** prereqs 01–03 shipped in a hassette release (the pinned base image must
contain base-path support, URL overrides, and the source guard)
**Size:** medium

## Goal

A working add-on installable from a custom repository URL: `repository.yaml` at the root, one
`hassette/` add-on folder, a derived image, and the options→env run script. The full manifest
sketch, run.sh responsibility list, and directory layout live in the research brief
(`research.md`, "Add-on anatomy") — this prereq is the checklist for building it.

## Key implementation notes

- **Dockerfile** (Supervisor 2026.04 rules: explicit `FROM`, no `build.yaml`):
  `FROM ghcr.io/nodejsmith/hassette:<version>-py3.14`, copy `run.sh`, set it as the
  entrypoint's command (tini stays PID 1 via the base image's `ENTRYPOINT ["tini","--"]`;
  `init: false` in the manifest so docker doesn't add a second init). Required labels
  (`io.hass.version`, `io.hass.type`, `io.hass.arch`) via the publish workflow.
- **run.sh** reads `/data/options.json` with the image's own Python (no bashio), exports the
  `HASSETTE__*` set (research brief lists them: token, `api_url`/`ws_url`, app dir under
  `/config/apps`, the web-port pin `HASSETTE__WEB_API__PORT=8126`, log level, install toggle,
  `UV_CACHE_DIR=/data/uv_cache`, conditional
  `allowed_client_ips`), seeds a commented starter `hassette.toml` + `apps/` on first run,
  then `exec /app/scripts/docker_start.sh`.
- **First-run seed** must be idempotent and never overwrite user files — presence check on
  `hassette.toml` only.
- **Port-mapping query** for the source guard: `GET http://supervisor/addons/self/info` with
  `Authorization: Bearer $SUPERVISOR_TOKEN` (`hassio_api: true`); if `network["8126/tcp"]` is
  null, export the allowlist restriction.
- **DOCS.md** is the in-store documentation tab: installation, where config lives
  (`/addon_configs/<repo>_hassette/`), how to add apps, the optional-port warning
  (unauthenticated), and the first-start dep-install delay.
- **Slug** is `hassette`; the host config dir is therefore `<repo-id>_hassette` where the repo
  id derives from the repository URL hash — document it as "shown in the add-on's
  Configuration tab" rather than hardcoding.

## Files (all created, new repo)

- `repository.yaml`
- `hassette/config.yaml` — manifest per the research-brief sketch
- `hassette/Dockerfile`
- `hassette/run.sh`
- `hassette/DOCS.md`
- `hassette/CHANGELOG.md`
- `hassette/icon.png`, `hassette/logo.png` — from the existing hassette logo asset
- `hassette/translations/en.yaml` — labels/descriptions for the two options
- `README.md` — repo-level: what this is, the add-store install link
  (`my.home-assistant.io` deep link), pointer to hassette docs
- `.github/workflows/` — see prereq-05 (can land as a stub building on push)

## Acceptance criteria

- [ ] Repo URL pastes into the add-on store and the add-on appears with icon and description
- [ ] Fresh install on HAOS: starts, connects to HA via the supervisor proxy with zero
      configuration, sidebar panel opens the dashboard through ingress (deep links included)
- [ ] `hassette.toml` + `apps/` appear in `/addon_configs/...` on first start; an app added
      there loads after restart
- [ ] Watchdog: killing the process inside the container triggers a supervisor restart;
      stopping HA core does **not** (liveness stays 200 while disconnected)
- [ ] With the host port left unmapped, requests from another LAN host to `:8126` are refused;
      after mapping the port they succeed (and DOCS.md states the trust implication)
- [ ] Uninstall/reinstall preserves `addon_config` contents; `/data` (telemetry DB) is
      recreated cleanly
