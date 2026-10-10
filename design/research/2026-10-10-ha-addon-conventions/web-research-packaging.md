# Prior art: packaging, imaging and releasing HA add-ons ("apps") that wrap an upstream server

Research date 2026-10-10. All files fetched from raw.githubusercontent.com / GitHub API on that date (default-branch HEAD).
"Not verified" = I did not read the file that would confirm it.

## Sources Found

### HA developer docs: Publishing your app
- **URL**: https://github.com/home-assistant/developers.home-assistant/blob/master/docs/apps/publishing.md
- **Type**: documentation / standard
- **Key takeaway**: Pre-built registry images are "the preferred method"; local builds are for experimenting ("once you're an established repository, please migrate to pushing builds to a container registry"). `image:` should be the generic multi-arch name (`ghcr.io/org/app`); `{arch}` is a compat fallback.
- **Relevance**: Settles (b): ship a prebuilt multi-arch image. hassette's existing ghcr.io multi-arch images already fit.

### HA developer docs: App configuration
- **URL**: https://github.com/home-assistant/developers.home-assistant/blob/master/docs/apps/configuration.md
- **Type**: documentation / standard
- **Key takeaway**: `version` "needs to match the tag of the image" when `image:` is used. `init: false` is for images with their own init (s6); default `true` injects Docker's init. `stage` = stable/experimental/deprecated. `breaking_versions` forces manual update across listed versions. `build.yaml` is no longer used by the new builder; base image goes in the Dockerfile `FROM`. Since Supervisor 2026.04.0 `BUILD_FROM` is no longer defaulted.
- **Relevance**: Version-equals-tag coupling is why every surveyed project has an automated or semi-automated bump. `breaking_versions` is the lever for hassette breaking releases.

### HA blog: Migrating app builds to Docker BuildKit (2026-04-02)
- **URL**: https://github.com/home-assistant/developers.home-assistant/blob/master/blog/2026-04-02-builder-migration.md
- **Type**: documentation
- **Key takeaway**: Legacy `home-assistant/builder` container retired; replaced by composite actions over native BuildKit. `build.yaml` deleted in favour of `FROM`/`ARG`/`LABEL` in the Dockerfile. Supervisor still reads `build.yaml` for local builds but warns. Base images are now multi-platform manifests.
- **Relevance**: Do not model a new add-on on older repos that still use `build.yaml` (Z2M, Matter Server, hassio-addons Renovate regex still reference it).

### home-assistant/apps-example (builder.yaml, config.yaml, Dockerfile)
- **URL**: https://github.com/home-assistant/apps-example (files: `.github/workflows/builder.yaml`, `example/config.yaml`, `example/Dockerfile`)
- **Type**: reference implementation
- **Key takeaway**: Canonical shape: one folder per app in a repo, `repository.yaml` at root, `image: ghcr.io/home-assistant/app-example` (no `{arch}`), `init: false`, Dockerfile `ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23`, workflow detects changed app folders (config/Dockerfile/rootfs) and builds only those via `home-assistant/builder` composite actions; push publishes, PR only builds.
- **Relevance**: Template for the add-on repo's CI if we build our own wrapper image. If we only point `image:` at hassette's image, none of this is needed.

### home-assistant/builder
- **URL**: https://github.com/home-assistant/builder
- **Type**: reference implementation (composite actions: `build-image`, `publish-multi-arch-manifest`)
- **Key takeaway**: Named in publishing.md as the supported build path; per-arch image + generic manifest.
- **Relevance**: Only needed if the add-on image differs from the upstream image. (README not fetched; cited via publishing.md.)

### Music Assistant add-on repo
- **URL**: https://github.com/music-assistant/home-assistant-addon and https://github.com/music-assistant/server/blob/main/.github/workflows/release.yml (job `update_addon`, ~line 1378)
- **Type**: reference implementation
- **Key takeaway**: Add-on repo has NO Dockerfile; each folder's config.yaml sets `image: ghcr.io/music-assistant/server`. The upstream server repo's release workflow mints a GitHub App token for `home-assistant-addon`, rewrites `version` + CHANGELOG in the folder matching the channel (stable -> `music_assistant`, beta/rc -> `music_assistant_beta`, nightly -> `music_assistant_nightly` and `music_assistant_dev`), and commits.
- **Relevance**: Closest match to hassette's situation (Python server, own multi-arch image, own release pipeline). Strongest evidence for "separate repo + `image:` -> upstream image + upstream release pipeline pushes version bump".

### Frigate add-on repo
- **URL**: https://github.com/blakeblackshear/frigate-hass-addons (e.g. `frigate/config.yaml`, `frigate_beta/config.yaml`)
- **Type**: reference implementation
- **Key takeaway**: Maintained by the Frigate author in a separate repo; folders `frigate`, `frigate_beta`, `frigate_fa`, `frigate_fa_beta`, `frigate_oldcpu`, `frigate_proxy`; config.yaml has `image: ghcr.io/blakeblackshear/frigate` (upstream image, no `{arch}`), no Dockerfile in the folder. Version bumps are hand-made PRs by maintainers ("0.18 release (#300)", "update to rc2 (#299)"). `breaking_versions` lists every minor.
- **Relevance**: Shows the minimal viable add-on: config.yaml + docs + icon pointing at the upstream image; manual bump is tolerated. Upstream image `docker/main/Dockerfile` is s6-overlay based and decides at runtime whether to run as root (`FRIGATE_RUN_AS_ROOT` / `service-runs-as-root`).

### ESPHome add-on repo + upstream Dockerfile
- **URL**: https://github.com/esphome/home-assistant-addon (`esphome/config.yaml`, `.github/workflows/bump-version.yml`); https://github.com/esphome/esphome/blob/dev/docker/Dockerfile ; https://github.com/esphome/esphome/blob/dev/.github/workflows/release.yml
- **Type**: reference implementation
- **Key takeaway**: Add-on repo is separate, generated folders (`esphome`, `esphome-beta`, `esphome-dev`; file "FILES ARE GENERATED DO NOT EDIT"), config.yaml `image: ghcr.io/esphome/esphome-hassio`. The image is built in the UPSTREAM repo from the same Dockerfile with `BUILD_TYPE=ha-addon` (base `docker-base:debian-ha-addon-*`, HA rootfs in upstream `docker/ha-addon-rootfs`). Add-on version bump is a `workflow_dispatch` with `version` input running `script/bump-version.py`, committing through a GitHub App; upstream release.yml has a `version-notifier` job that dispatches a workflow in `esphome/version-notifier` (the final hop to the add-on dispatch is not verified).
- **Relevance**: The "upstream builds an add-on-flavoured variant of its own image" pattern; also shows bot-driven bump with GitHub App token rather than PAT.

### Zigbee2MQTT add-on repo
- **URL**: https://github.com/zigbee2mqtt/hassio-zigbee2mqtt (`common/Dockerfile`, `common/build.yaml`, `.github/workflows/{ci,release}.yml`, `zigbee2mqtt/config.json`); upstream trigger in https://github.com/Koenkk/zigbee2mqtt/blob/master/.github/workflows/ci.yml
- **Type**: reference implementation
- **Key takeaway**: Separate repo; HA-flavoured Alpine image built from `ghcr.io/home-assistant/{arch}-base:3.24` (NOT the upstream image), upstream source fetched by tag in the Dockerfile; `image: ghcr.io/zigbee2mqtt/zigbee2mqtt-{arch}`, `init: false` with explicit `tini` entrypoint. Upstream release workflow POSTs a `repository_dispatch` (`event_type: release`, `version: "$TAG-1"`) to the add-on repo, which `jq`-edits config.json, prepends CHANGELOG, commits, tags; tag push triggers CI with `home-assistant/builder`. Add-on version = `<upstream>-<addon-revision>` (e.g. 2.14.2-1). Upstream `dev` push dispatches the edge build. Folders: `zigbee2mqtt`, `zigbee2mqtt-edge`, `zigbee2mqtt-proxy`.
- **Relevance**: Best documented "upstream repository_dispatch -> add-on repo" implementation; the `-N` suffix solves add-on-only fixes without an upstream release.

### Matter Server (official home-assistant/addons)
- **URL**: https://github.com/home-assistant/addons/tree/master/matter_server (`config.yaml`, `build.yaml`, `Dockerfile`)
- **Type**: reference implementation
- **Key takeaway**: Wraps a third-party image: `build.yaml` sets `build_from` to `ghcr.io/matter-js/matterjs-server:1.4.0` (pinned), Dockerfile `FROM ${BUILD_FROM}`, `USER root` (comment: upstream image is unprivileged, add-on needs root for s6-overlay and BLE), then layers bashio/tempio/s6-overlay on top. Published as `image: homeassistant/{arch}-addon-matter-server`. Beta channel is a runtime option (`beta: bool`), not a separate folder. Repo's only dependabot config is for GitHub Actions; no bump automation for the base tag was visible.
- **Relevance**: The only surveyed example of "upstream image as base + HA tooling layered on top" and it has to flip to root and install an init system.

### Mosquitto (official home-assistant/addons)
- **URL**: https://github.com/home-assistant/addons/tree/master/mosquitto
- **Type**: reference implementation
- **Key takeaway**: Monorepo of first-party add-ons, `image: homeassistant/{arch}-addon-mosquitto` (legacy per-arch naming), Dockerfile `FROM $BUILD_FROM`, builds Mosquitto from source/apt on HA base.
- **Relevance**: Legacy shape; not the pattern for a third-party server that already ships an image.

### hassio-addons community org (Node-RED, Z-Wave JS UI, AppDaemon, Studio Code Server)
- **URL**: https://github.com/hassio-addons/app-node-red, .../app-zwave-js-ui, .../app-appdaemon, .../app-vscode
- **Type**: reference implementation
- **Key takeaway**: One repo per add-on (separate from upstream), `config.yaml` carries `version: dev` and no `image:`; Dockerfile `ARG BUILD_FROM=ghcr.io/hassio-addons/base:21.0.8` (Alpine) or `debian-base:9.5.0` (vscode); upstream software installed by pinned `ARG ZWAVE_JS_UI_VERSION="11.24.3"` + `npm install`. CI/deploy are thin callers of shared reusable workflows (`hassio-addons/workflows/.github/workflows/app-{ci,deploy}.yaml@<sha>`) triggered by push to main / release published. Renovate with custom regex managers on Dockerfile + Alpine package datasource bumps pins. `init: false` everywhere (s6).
- **Relevance**: Shows the "own the image, bump upstream via Renovate" model and the shared reusable-workflow trick. `version: dev` in-tree is stamped at release (inferred from the deploy workflow; I did not read app-deploy.yaml).

### tsightler/ring-mqtt-ha-addon
- **URL**: https://github.com/tsightler/ring-mqtt-ha-addon (`ring-mqtt/config.yaml`), upstream Dockerfile https://github.com/tsightler/ring-mqtt/blob/main/Dockerfile
- **Type**: reference implementation
- **Key takeaway**: Separate add-on repo; `image: 'tsightler/ring-mqtt'` is the same Docker Hub image standalone users run. Upstream image is `FROM node:jod-alpine` + s6-overlay with `ENTRYPOINT ["/init"]` and the app's own `init/s6` scripts that detect add-on mode. `init: false`. Lists armhf/armv7 too.
- **Relevance**: Direct proof that one image can serve both standalone Docker and the add-on when the entrypoint reads `/data/options.json` / Supervisor env itself.

### evcc-io/hassio-addon
- **URL**: https://github.com/evcc-io/hassio-addon (`evcc/config.yaml`)
- **Type**: reference implementation
- **Key takeaway**: Separate repo owned by the upstream org; `image: evcc/evcc` (upstream Docker Hub image), `legacy: true`, `init: false`, folders `evcc` and `evcc-nightly`. Commits by a bot titled "Mirror evcc nightly release" / "Update evcc changelog" (mechanism not read). CI is only `frenck/action-addon-linter`.
- **Relevance**: Upstream-org-owned add-on repo with bot-mirrored versions and lint-only CI.

### alexbelgium/hassio-addons
- **URL**: https://github.com/alexbelgium/hassio-addons (e.g. `sonarr/{config.yaml,Dockerfile,build.json,updater.json}`)
- **Type**: reference implementation (community aggregator wrapping upstream images)
- **Key takeaway**: Monorepo wrapping linuxserver.io images: `build.json` `build_from: lscr.io/linuxserver/sonarr:<arch>-develop`, Dockerfile `ARG BUILD_UPSTREAM` + `FROM ${BUILD_FROM}`, `image: ghcr.io/alexbelgium/sonarr_nas-{arch}`, per-add-on `updater.json` (`upstream_repo`, `upstream_version`) driven by `weekly_addons_updater` workflow; `init: false`.
- **Relevance**: The scaled-out "wrap many upstream images" approach; shows what it costs (updater tooling, arch-specific tags, root + s6 shim on top of foreign images).

## Survey Table

| Add-on | Repo topology | Base image | `image:` key | Version bump | Channels | `init` | User |
|---|---|---|---|---|---|---|---|
| Music Assistant | Separate repo (`music-assistant/home-assistant-addon`); no Dockerfile there | Upstream image as-is (`ghcr.io/music-assistant/server`, python-slim based, built in upstream repo) | `ghcr.io/music-assistant/server`, no `{arch}` | Upstream `release.yml` job `update_addon` commits version+CHANGELOG via GitHub App | Separate folders: stable, `_beta`, `_nightly`, `_dev`; `stage: stable/experimental` | false | Not verified |
| Zigbee2MQTT | Separate repo (`zigbee2mqtt/hassio-zigbee2mqtt`), shared `common/Dockerfile` copied per folder in CI | HA base `ghcr.io/home-assistant/{arch}-base:3.24` | `ghcr.io/zigbee2mqtt/zigbee2mqtt-{arch}` | Upstream `repository_dispatch` `release` with `vX-1`; tag triggers builder | Folders: stable, `-edge` (dev branch), `-proxy` | false (+ `tini` ENTRYPOINT) | Root (HA base; no USER seen) |
| ESPHome | Separate repo (`esphome/home-assistant-addon`); image Dockerfile + `ha-addon-rootfs` live in UPSTREAM repo | `ghcr.io/esphome/docker-base:debian-ha-addon-*` (upstream-owned HA-flavoured base) | `ghcr.io/esphome/esphome-hassio` (no `{arch}`) | `workflow_dispatch` w/ version input + `bump-version.py`, GitHub App commit; triggered from upstream release (last hop not verified) | Folders: stable, `-beta`, `-dev` (generated) | false | Not verified |
| Frigate | Separate repo (`frigate-hass-addons`), author-owned; no Dockerfile | Upstream image as-is (`ghcr.io/blakeblackshear/frigate`) | `ghcr.io/blakeblackshear/frigate`, no `{arch}` | Manual maintainer PRs per RC/release | Folders: `frigate`, `_beta`, `_fa`, `_fa_beta`, `_oldcpu`, `_proxy` | false | Upstream decides at runtime (root vs non-root script) |
| Matter Server (official) | Monorepo `home-assistant/addons`, separate from upstream `matter-js` | Upstream image as base `ghcr.io/matter-js/matterjs-server:1.4.0` + bashio/tempio/s6 layered | `homeassistant/{arch}-addon-matter-server` | Pin in `build.yaml`; no automation seen (only dependabot for Actions) | Single add-on; `beta: bool` runtime option | false | `USER root` forced |
| Mosquitto (official) | Same monorepo | HA base via `BUILD_FROM` | `homeassistant/{arch}-addon-mosquitto` | Manual in monorepo | One | false | Not verified |
| Z-Wave JS UI | Separate repo per add-on (`hassio-addons/app-zwave-js-ui`) | `ghcr.io/hassio-addons/base:21.0.8` (Alpine), npm-installs upstream | none in tree (`version: dev`) | Renovate regex on Dockerfile `ARG`; release stamps version | Single; separate repo not used for edge | false | Root (s6 base) |
| Node-RED | Separate repo (`hassio-addons/app-node-red`) | `ghcr.io/hassio-addons/base:21.0.8` | none in tree (`version: dev`) | Renovate (custom Alpine datasource) | Single | false | Root (s6 base) |
| AppDaemon | Separate repo (`hassio-addons/app-appdaemon`) | hassio-addons base (Dockerfile not read) | none in tree (`version: dev`) | Renovate (same org config) | Single | false | Root (s6 base) |
| Studio Code Server | Separate repo (`hassio-addons/app-vscode`) | `ghcr.io/hassio-addons/debian-base:9.5.0` | none in tree (`version: dev`) | Renovate | Single | false | Root (s6 base) |
| Ring-MQTT | Separate repo (`tsightler/ring-mqtt-ha-addon`), author-owned | Upstream image as-is (`node:jod-alpine` + s6, built in upstream repo) | `tsightler/ring-mqtt` (Docker Hub, shared with standalone users) | Manual / author (version 5.9.3) | Single | false | Not verified |
| evcc | Separate repo owned by upstream org (`evcc-io/hassio-addon`) | Upstream image as-is | `evcc/evcc` | Bot commits "Mirror evcc ... release" | Folders `evcc`, `evcc-nightly` | false | Not verified |
| alexbelgium (sonarr example) | Community monorepo | Upstream image as base (`lscr.io/linuxserver/sonarr:<arch>-develop` via `build.json`) | `ghcr.io/alexbelgium/sonarr_nas-{arch}` | Weekly `addons_updater` workflow + `updater.json` | Per-add-on; `github_beta` flag | false | Root layer on top of foreign image |
| InfluxDB / Grafana / Scrypted / Valetudo | [no source found] - not fetched; Scrypted/Valetudo have only community add-ons (e.g. https://github.com/dshafik/ha-addon-scrypted, https://github.com/eoura2/Scrypted-HA-addon, appeared in search, not read) | - | - | - | - | - | - |

## Patterns Found

### Pattern 1: Add-on lives in a separate repo, never inside the upstream project repo
**Used by**: all 12 add-on repos surveyed (Music Assistant, Z2M, ESPHome, Frigate, Matter, Mosquitto, Z-Wave JS UI, Node-RED, AppDaemon, vscode, ring-mqtt, evcc, plus alexbelgium).
**How it works**: `repository.yaml`/`repository.json` at root, one folder per add-on/channel, README/DOCS/CHANGELOG/icon/logo/config.yaml. Even when the image is built in upstream (ESPHome) the add-on definition stays separate. Supervisor requires the repo layout to be scannable by folder, which discourages embedding in a monorepo with other build tooling.
**Strengths**: Supervisor store clones the repo (small, fast); upstream release cadence and add-on metadata changes decouple; no tags/versions collision with upstream's release train.
**Weaknesses**: Cross-repo bump plumbing (token, dispatch) required; two places to update docs.
**Example**: https://github.com/music-assistant/home-assistant-addon ; https://github.com/blakeblackshear/frigate-hass-addons ; [no source found] for any add-on that lives as a subfolder of its upstream repo.

### Pattern 2: `image:` points straight at the upstream image, no add-on Dockerfile
**Used by**: Music Assistant, Frigate, ring-mqtt, evcc (4), plus ESPHome with a dedicated `-hassio` tag from upstream CI (a variant).
**How it works**: config.yaml `image: ghcr.io/org/app` (generic multi-arch name), `version` equals image tag, no Dockerfile or build.yaml in the folder. The upstream image reads `/data/options.json` / Supervisor env in its entrypoint (ring-mqtt via s6 scripts, MA via `entrypoint.sh`, Frigate via s6 services).
**Strengths**: One artifact tested everywhere; no wrapper build pipeline; fastest to ship; matches HA docs' preferred shape.
**Weaknesses**: Image must tolerate Supervisor's runtime (root, `/data` mount, ingress port, no TTY) and carry HA-mode code paths; version tag must exist at the moment the add-on version lands (ordering constraint, so the bump must follow image publish).
**Example**: https://github.com/music-assistant/home-assistant-addon/blob/main/music_assistant/config.yaml ; https://github.com/blakeblackshear/frigate-hass-addons/blob/main/frigate/config.yaml

### Pattern 3: Wrapper image built from an HA base image, upstream installed by pinned version
**Used by**: Z2M, Z-Wave JS UI, Node-RED, AppDaemon, vscode, Mosquitto (6+).
**How it works**: `FROM ghcr.io/home-assistant/base` or `ghcr.io/hassio-addons/{base,debian-base}`; install runtime and upstream release by version `ARG`; s6 or tini; bashio for config.
**Strengths**: Full HA integration (bashio, tempio, s6, Supervisor APIs), small Alpine layers, familiar to the add-on community.
**Weaknesses**: A second build/test pipeline; musl/Alpine vs upstream's glibc/Debian can diverge (relevant to Python wheels - hassette is Debian python-slim); bump needs Renovate regexes or dispatch.
**Example**: https://github.com/zigbee2mqtt/hassio-zigbee2mqtt/blob/master/common/Dockerfile ; https://github.com/hassio-addons/app-zwave-js-ui/blob/main/zwave-js-ui/Dockerfile

### Pattern 4: Upstream image as the base, HA tooling layered on top
**Used by**: Matter Server (official), alexbelgium (many).
**How it works**: `FROM <upstream image>:<pinned tag>`, `USER root`, add bashio/tempio/s6-overlay, `COPY rootfs`.
**Strengths**: Keeps upstream runtime exactly; HA conveniences available.
**Weaknesses**: Must override upstream's non-root user and entrypoint; fights upstream's own init (hence `init: false` + s6); two image names to track; no bump automation seen for Matter.
**Example**: https://github.com/home-assistant/addons/blob/master/matter_server/Dockerfile

### Pattern 5: Upstream release pipeline pushes the add-on version bump
**Used by**: Music Assistant (GitHub App commit), Z2M (`repository_dispatch` + auto-commit + tag), ESPHome (`workflow_dispatch` + GitHub App), evcc (bot "mirror" commits). 4 of 13.
**How it works**: After upstream publishes the image, a job in the upstream repo authenticates to the add-on repo (GitHub App token or PAT) and either dispatches a workflow there or commits config.yaml `version` + CHANGELOG directly; channel (stable/beta/nightly) picks the folder.
**Strengths**: Zero lag, no Renovate, ordering guaranteed (image exists first). Add-on repo commits are mechanical.
**Weaknesses**: Needs cross-repo credential (GitHub App preferred; Z2M uses a PAT-style `GH_TOKEN`); upstream must know the add-on repo layout.
**Example**: https://github.com/music-assistant/server/blob/main/.github/workflows/release.yml ; https://github.com/Koenkk/zigbee2mqtt/blob/master/.github/workflows/ci.yml (lines ~161-182)

### Pattern 6: Channels as sibling folders with distinct slugs, not branches or repos
**Used by**: Music Assistant (4 folders), Z2M (3), ESPHome (3), Frigate (6), evcc (2). Matter uses a runtime `beta` option instead.
**How it works**: each folder has its own `slug` (`music_assistant_beta`), `name` ("... (BETA)"), `stage: experimental` for non-stable, and can be installed side by side. Pre-release `version` strings carry the suffix (2.11.0b4, 2026.10.0b2, edge).
**Strengths**: Users opt in per add-on; single repo; Supervisor's `stage` flag communicates risk.
**Weaknesses**: Duplicated config.yaml across folders (ESPHome generates them; MA copy-edits); side-by-side installs share ports/host_network.
**Example**: https://github.com/music-assistant/home-assistant-addon (folders list)

### Pattern 7: Renovate/updater bot bumps the pinned upstream version inside a self-built image
**Used by**: hassio-addons org (Renovate regex on Dockerfile ARGs), alexbelgium (`updater.json` + weekly workflow).
**How it works**: regex custom manager matches `ARG X_VERSION=` lines; PR bump; release-drafter/deploy publishes and stamps the add-on version.
**Strengths**: Works when upstream has no add-on awareness.
**Weaknesses**: Only needed because the add-on rebuilds upstream; irrelevant when `image:` points at the upstream tag.
**Example**: https://github.com/hassio-addons/app-node-red/blob/main/.github/renovate.json

### Pattern 8: `init: false` is universal
**Used by**: 13 of 13 inspected config files.
**How it works**: images ship their own PID 1 (s6-overlay `/init`, or `tini` ENTRYPOINT in Z2M), so Docker's injected init is disabled; docs say it is required with s6 v3.
**Strengths**: Avoids double-init and s6 "must be PID 1" failure.
**Weaknesses**: Images without any init (a bare bash entrypoint) lose zombie reaping unless they bring `tini`.
**Example**: https://github.com/zigbee2mqtt/hassio-zigbee2mqtt/blob/master/common/Dockerfile (`ENTRYPOINT [ "/sbin/tini", "--", ...]` with `init: false` in config.json); hassette's existing tini PID 1 fits this exactly.

## Anti-Patterns

- **Local Supervisor builds for an established project**: HA docs explicitly call it slower, SD-wearing and brittle; no surveyed established project does it.
- **Still shipping `build.yaml`**: deprecated by the 2026-04 builder migration; Z2M, Matter, and hassio-addons Renovate patterns still reference it and will warn.
- **Per-arch `{arch}` image names**: legacy (Mosquitto, Z2M, alexbelgium); docs now prefer the generic manifest name.
- **Hand-bumping versions** (Frigate): works, but nothing prevents `version` and image tag drifting; the survey shows maintainers who have an upstream release workflow automate it.
- **Version drift by mutable tags**: `version` must equal the image tag per docs; pointing at `latest` breaks update detection [no source found for a project doing this; inferred from docs].

## Emerging Trends

- GitHub App tokens (`actions/create-github-app-token`) replacing PATs for cross-repo bump commits (ESPHome, Music Assistant).
- Shared reusable workflows for fleets (`hassio-addons/workflows`), changed-folder matrix builds (apps-example).
- Naming shift "add-ons" -> "apps" and repo renames (`app-node-red`, `apps-example`), generic multi-arch image names.
- No project in the survey uses release-please for add-on versioning [no source found].

## Summary of dominant conventions

(a) Location: separate repo, 13/13 (zero embed the add-on in the upstream repo; ESPHome keeps only the image Dockerfile and `ha-addon-rootfs` upstream). Channels are sibling folders in that repo (5 of 13), occasionally a runtime option (Matter).
(b) Image: prebuilt registry image, 13/13 in practice. Of those, `image:` pointing at the upstream/upstream-built image with no add-on Dockerfile: 4 (MA, Frigate, ring-mqtt, evcc) + ESPHome's upstream-built `-hassio` variant. Wrapper images built by the add-on repo: 8. Supervisor local build: 0 for established projects (hassio-addons ships no `image:` in-tree, but their deploy workflow publishes to ghcr; inferred).
(c) Base: HA/hassio-addons base ~7 (Alpine, s6 or tini), upstream image as base 2 (Matter, alexbelgium; both need `USER root` + s6), upstream image used verbatim 4. For a Debian-slim Python server that already has an HA-aware entrypoint, "verbatim upstream image" is the lowest-friction precedent (Music Assistant is the closest analogue).
(d) Bumps: upstream release pipeline pushes the add-on version (MA, Z2M, ESPHome, evcc) 4; Renovate/updater when the add-on rebuilds upstream 2 orgs; manual 3 (Frigate, ring-mqtt, Matter). `version` must equal the image tag. `init: false` 13/13.
