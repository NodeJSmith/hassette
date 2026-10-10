---
topic: "Conventions for packaging an upstream server as a Home Assistant add-on (app)"
date: 2026-10-10
status: Draft
---

# Prior Art: Packaging an upstream server as a Home Assistant add-on

## The Problem

hassette already publishes its own multi-arch Docker image, with an entrypoint that installs user dependencies
and then execs the server. It needs to ship as a Home Assistant add-on, which HA now calls an "app". The open
questions are where the add-on lives, which image Supervisor runs, how failures and restarts behave, how the
web UI works through ingress next to hassette's own auth, and how the companion integration finds the server.
The sketch ledger `design/specs/129-ha-addon-v01/design.md` drafted answers to these. This survey checks
each draft answer against what established add-ons actually do.

## How We Do It Today

There is no add-on yet. ADR-0005 (July) planned a separate `hassette-addon` repo with a thin derived image
and a `run.sh`. The draft ledger moved away from that plan: it puts the add-on in the hassette monorepo, has
Supervisor build a thin image locally, and keeps tini plus `docker_start.sh` with a zero retry delay. Since
July, hassette has gained web API auth, including `trusted_proxies`, and resolved config locations
(`--check`, apps under `/config/apps`).

## Survey (about 20 add-ons; full tables in web-research-{packaging,runtime,config}.md)

| | Music Assistant | Frigate | ESPHome | Z2M | Matter (core) | Z-Wave JS UI | Node-RED | AppDaemon |
|---|---|---|---|---|---|---|---|---|
| Repo | separate | separate | separate (image built upstream) | separate | core monorepo | separate | separate | separate |
| Image | upstream image verbatim | upstream verbatim | upstream-built `-hassio` variant | wrapper on HA base | wrapper on upstream | wrapper on HA base | wrapper | wrapper |
| Version bump | upstream release → GitHub App commit | manual | upstream dispatch | upstream `repository_dispatch` | manual | Renovate | Renovate | Renovate |
| Supervision | plain exec | s6, finish halts | s6, finish halts | tini + exec | s6 | s6 | s6 | s6 |
| User | root | root/runtime | root | root | root | root | root | root |
| Ingress | separate listener on 172.30.32.x, 8094 | unauth port 5000 | app-side, peer guard | 8099 | 5580 app-native | `X-External-Path` app-side | relative paths | none |
| Direct port | n/a (host net) | `null` | `null` + 2nd opt-in | `null` | `null` | — | on | on |
| Discovery | yes, with `auth_token` (added a year after v1) | — | yes (added late) | n/a | yes (from v1) | yes (from v1) | — | — |
| watchdog | none | HTTP | none | none | none | none | none | none |

## Patterns Found

### Pattern 1: Separate add-on repo, with channels as sibling folders
**Used by**: 13 of 13 surveyed. None ships the add-on as a folder inside its upstream repo. Channels are
sibling folders with their own slugs: Music Assistant has `_beta`, `_nightly` and `_dev`; Frigate and ESPHome
also use folders.
**How it works**: `repository.yaml` at the root and one folder per add-on, each holding config.yaml, README,
DOCS, CHANGELOG and icon/logo.
**Strengths**: a small store clone, and add-on metadata changes are decoupled from upstream releases.
**Weaknesses**: version bumps need plumbing across the two repos.
**Example**: https://github.com/music-assistant/home-assistant-addon

### Pattern 2: Prebuilt image, owned by upstream
**Used by**: 13 of 13 use prebuilt images; none relies on Supervisor's local build. HA's docs call prebuilt
"the preferred method" and recommend a generic multi-arch image name. Upstream-owned add-ons point `image:`
at either the upstream image itself (Music Assistant, Frigate, evcc, ring-mqtt) or an HA-flavoured variant
that upstream CI builds (ESPHome's `esphome-hassio`, built from an upstream-owned `ha-addon-rootfs`).
**Strengths**: one artifact, tested where it's built, with no wrapper pipeline.
**Weaknesses**: the image must tolerate Supervisor's runtime (root, `/data`, no TTY). The version tag must
exist before the add-on version lands.
**Example**: https://github.com/music-assistant/home-assistant-addon/blob/main/music_assistant/config.yaml ;
https://github.com/esphome/esphome/tree/dev/docker

### Pattern 3: Upstream's release pipeline pushes the add-on bump
**Used by**: Music Assistant (GitHub App commit after the image publishes), Z2M (`repository_dispatch`),
ESPHome (`workflow_dispatch`), evcc (bot mirror). Repos that rebuild upstream themselves use Renovate
instead (hassio-addons, alexbelgium). None uses release-please.
**How it works**: once the image publishes, a job in the upstream repo uses a GitHub App token to commit
`version` and a CHANGELOG entry into the add-on repo's channel folder.
**Strengths**: no lag, and ordering is guaranteed because the image exists first.
**Weaknesses**: needs a credential that works across repos.
**Example**: https://github.com/music-assistant/server/blob/main/.github/workflows/release.yml (`update_addon`)

### Pattern 4: `init: false`, root, and stop on failure
**Used by**: `init: false` in 14 of 14. Every add-on runs as root. Images built on s6 use a `finish` script
that halts the container on a non-zero exit. Single-process images (Z2M, Music Assistant) use tini or a plain
`exec`. None idles and then retries.
**Strengths**: Supervisor's own state (stopped) shows the failure.

### Pattern 5: Ingress with the base path handled by the app, and a peer guard
**Used by**: the robust approach is app-side: Z-Wave JS UI (`X-External-Path`), Grafana (`root_url`), Z2M
(`base_url`), ESPHome. Frigate's nginx `sub_filter` placeholder rewrite is called brittle. The direct port
defaults to `null` in 7 of 10 ingress add-ons. Apps that have their own auth trust the ingress peer: ESPHome
uses a peer guard, Frigate has an unauthenticated ingress port, and Music Assistant runs a separate ingress
listener.
**Anti-pattern**: ESPHome CVE-2026-59177. Its ingress listener skipped auth, assuming Supervisor had already
authenticated, but it bound `0.0.0.0` on host networking. The fix was a peer guard (403 unless the peer is
loopback or 172.30.32.2) plus a narrow bind.

### Pattern 6: Discovery carrying the API token, added later than v1
**Used by**: Music Assistant sends `{host, port, auth_token}` and the integration trusts that token. It
arrived in Nov 2025, about a year after the integration first shipped. Matter and Z-Wave JS had discovery from
v1. Supervisor doesn't restrict service names, so a HACS integration should be able to consume discovery;
this is inferred from code, and I found no example of one doing it.

## Relevance to Us: ledger decisions vs convention

| Decision | Draft recommendation | Convention | Verdict |
|---|---|---|---|
| D1 ingress in v0.1 | ingress; direct port `null` | ingress; direct port `null` (7 of 10) | **matches** |
| D1 base-path method | `<base href>` from `X-Ingress-Path`, app-side | app-side is the robust approach | **matches** |
| D2 repo | folder in hassette monorepo | separate repo, 13 of 13 | **diverges** |
| D3 image | Supervisor builds locally | prebuilt, 13 of 13; upstream-owned image or upstream-built HA variant | **diverges** |
| D4 supervision | tini + `docker_start.sh`, retry delay 0, exit and stay stopped | `init: false`; stop on failure; single-process images use exec | **matches** |
| D5 user | root | root, all of them | **matches**, but see D3: the stock hassette image is `USER hassette` |
| D6 HA URLs | `base_url` keeps its path | internal; no convention | n/a |
| D7 ingress auth | `trusted_proxies=172.30.32.2`, token elsewhere | peer-guarded ingress, own auth elsewhere (ESPHome post-CVE, Frigate, Music Assistant) | **matches**; `panel_admin` is mixed (Frigate and Music Assistant use `false`) |
| D8 token surfacing | token file in `/config` | weakly established; Music Assistant relied on discovery | no strong convention |
| D9 options | `log_level` + `install_requirements` | log level and toggles; code hosts use **option lists** (`python_packages`, `init_commands`) installed on start | **partial**: lists are the norm, and a requirements.txt toggle isn't |
| D10 seeding + backup | seed only if absent; exclude uv cache; keep DB | AppDaemon seeds only if absent; caches excluded, DBs kept | **matches** |
| D11 resolver | not needed | n/a | n/a |
| D12 release | release-please `extra-files` | upstream pipeline pushes the bump after the image publishes | **diverges** (follows D2) |
| D13 discovery | manual in v0.1 | v1 manual is precedented (Music Assistant); token-in-discovery is the target | **matches** for v0.1 |
| D14 watchdog | `/api/health/live` | 12 of 14 omit `watchdog:`; Frigate uses HTTP | mild divergence; harmless |
| — wait for Core | not in ledger | only AppDaemon polls | n/a (hassette's bootstrap gate covers it) |
| — channels | stable only | sibling folders when added | compatible |

## Recommendation

Revise D2, D3 and D12 to follow Pattern 1 + 2 + 3, as ESPHome and Music Assistant do:

- **D2:** a separate `NodeJSmith/hassette-addon` repo. Channels added later become sibling folders.
- **D3:** the hassette repo's image workflow builds an HA variant image (ESPHome-style). It runs as root, and
  its glue is an HA entrypoint layered `FROM` the just-built image, published as a generic multi-arch name.
  The main image stays add-on-unaware. An image used verbatim, Music Assistant-style, would need the stock image to
  start as root and drop privileges for Docker users. That is a bigger change to the image every Docker user
  runs.
- **D12:** after that image publishes, hassette's release workflow commits `version` and a CHANGELOG entry to
  `hassette-addon` with a GitHub App token.

Open questions to settle in the ledger: whether D9 should switch to an AppDaemon-style `python_packages` list,
and whether `panel_admin` should be `false` like Frigate and Music Assistant. D14 is optional either way.

Coverage gaps: I never read ESPHome's last dispatch hop. The runtime user for Music Assistant, ESPHome and
ring-mqtt is unconfirmed. There's no example of a custom integration consuming discovery.

## Sources

### Reference implementations
- https://github.com/music-assistant/home-assistant-addon — upstream image, channels as folders, discovery with auth_token
- https://github.com/music-assistant/server/blob/main/.github/workflows/release.yml — upstream release job bumps the add-on
- https://github.com/blakeblackshear/frigate-hass-addons — upstream image, two-port auth model
- https://github.com/esphome/home-assistant-addon ; https://github.com/esphome/esphome/tree/dev/docker — upstream-built `-hassio` variant, peer guard
- https://github.com/zigbee2mqtt/hassio-zigbee2mqtt — tini entrypoint, upstream dispatch
- https://github.com/hassio-addons/app-appdaemon, app-node-red, app-zwave-js-ui, app-vscode — s6 wrappers, Renovate
- https://github.com/home-assistant/addons (matter_server, mosquitto) — core add-ons
- https://github.com/evcc-io/hassio-addon ; https://github.com/tsightler/ring-mqtt-ha-addon ; https://github.com/alexbelgium/hassio-addons

### Writeups and advisories
- https://corgea.com/advisories/vulnerabilities/CVE-2026-59177 — ESPHome ingress auth-skip on 0.0.0.0

### Documentation and standards
- https://github.com/home-assistant/developers.home-assistant/tree/master/docs/apps — configuration, communication, presentation, publishing, repository
- ~/source/supervisor (2026.10.1): apps/validate.py, store/data.py, apps/app.py (watchdog), api/ingress.py, discovery/
