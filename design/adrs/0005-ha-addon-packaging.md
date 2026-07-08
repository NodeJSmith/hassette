# ADR-0005: HA Add-on Packaging — Derived Image, Ingress-First Web UI

**Date:** 2026-07-07
**Status:** Accepted
**Context:** `epic:ha-addon` (#71). Full analysis in
`design/research/2026-07-07-ha-addon-architecture/research.md`.

## Context

Hassette needs a Home Assistant add-on distribution so HAOS/Supervised users can install it
from the add-on store instead of composing Docker themselves. The two architectural choices
that shape everything else: how the add-on image relates to the published hassette image, and
how the web UI is exposed to the user.

Constraints that drove the decision:

- The hassette web API has **no authentication**. Any exposure model must not widen that gap.
- Add-on users cannot substitute images — the supervisor owns the container, so runtime
  dependency install (already implemented in `scripts/docker_start.sh` and chosen for exactly
  this future in `design/specs/docker-dep-redesign/design.md`) is the only dep path.
- Supervisor 2026.04 removed implicit `BUILD_FROM` injection and `build.yaml`; add-on
  Dockerfiles use explicit `FROM`, and prebuilt images are referenced via the `image:` key.
- The frontend is absolute-path throughout (Vite base `/`, hardcoded `/api` client base,
  absolute `wouter` routes), which no ingress deployment can serve unmodified.

## Decision

**Derived image.** The add-on repo (`hassette-addon`, separate from the framework repo) builds
a thin image `FROM ghcr.io/nodejsmith/hassette:<version>-py3.14`, adding only a `run.sh` that
translates `/data/options.json` + `SUPERVISOR_TOKEN` into `HASSETTE__*` environment variables
and execs the existing entrypoint chain. All supervisor-specific glue lives in the add-on repo;
the main image carries zero add-on awareness.

**Ingress-first exposure.** `ingress: true` proxying to hassette's existing port 8126. The
supervisor authenticates the HA user before proxying, giving the unauthenticated web UI an auth
layer for free; hassette additionally restricts clients to the ingress gateway when no host
port is mapped. A host port mapping exists in `config.yaml` but ships disabled — opting in
reproduces today's Docker trust model and is documented as unauthenticated.

Supporting choices (detailed in the research brief): minimal options schema with real config in
`hassette.toml` under the `addon_config` mount; new general-purpose `api_url`/`ws_url` config
overrides so hassette can use the supervisor's proxy endpoints (`ws://supervisor/core/websocket`
does not follow the `base_url + /api/websocket` pattern); watchdog pointed at the existing
liveness endpoint `/api/health/live`, never at readiness, so supervisor restarts don't fight
hassette's own HA-reconnect logic.

## Alternatives considered

**Add-on-aware main image** — `docker_start.sh` detects `SUPERVISOR_TOKEN`/`options.json`
itself and the add-on references the stock image. One less image to publish, but supervisor
logic would ship (dormant) to every Docker user, couple the framework release cycle to add-on
manifest details, and put add-on debugging in the main repo. Rejected: the translation layer is
~50 lines of shell; a derived image isolates it where it belongs.

**Local Dockerfile build (no `image:` key)** — each user's machine builds on install. Rejected:
multi-minute installs on Pi-class hardware, build failures surfacing on user machines, and we
already publish multi-arch images.

**Direct-port exposure only (AppDaemon model)** — skips the frontend base-path work entirely.
Rejected: it exposes the auth-less UI on the LAN as the *only* access path, forfeits the
sidebar embedding that #71 exists for, and the base-path work is a bounded, one-time frontend
investment that also benefits reverse-proxy deployments.

**MQTT/other transports for HA connection** — not applicable; the add-on changes nothing about
how hassette talks to HA except the URLs and token source. ADR-0004's companion-integration
transport rides the same connection unchanged.

## Consequences

- The frontend must become base-path-agnostic (prereq-01): `<base href>` injection from
  `X-Ingress-Path`, with router/API/WS URLs derived from `document.baseURI`. This is the
  epic's largest single work item and benefits non-add-on reverse-proxy users.
- Hassette gains `api_url`/`ws_url` overrides (prereq-02) and `web_api.allowed_client_ips`
  (prereq-03) — small, generally useful config additions; no add-on-specific code paths.
- A second repo and image pipeline exist (`hassette-addon`), with version bumps automated off
  hassette releases (prereq-05). The add-on version is pinned to an exact hassette release tag,
  so add-on users update through the add-on store, never by image drift.
- First start with user dependencies has a web-UI-unavailable install window; the uv cache
  persists on `/data` so it is first-start-only. #615 (splash screen) remains the UX answer.
- `hassette build` (#616) is decoupled from the epic: the supervisor owns the image, so the
  add-on necessarily uses runtime install. #616 remains a standalone-Docker improvement.
