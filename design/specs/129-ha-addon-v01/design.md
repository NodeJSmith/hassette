# Design: Home Assistant add-on v0.1

**Date:** 2026-10-10
**Status:** ratified
**Mode:** sketch

## Summary

Hassette ships today as a Docker image (`ghcr.io/nodejsmith/hassette:<version>-py3.<minor>`, `Dockerfile`)
that users compose themselves. Home Assistant OS and Supervised users can't run arbitrary containers, so
for them hassette needs to be an add-on, which HA's UI now calls an "app". The add-on should install from a
custom repository URL, connect to HA with no token pasting, show its web UI, keep its config where users can
edit it, and restart under Supervisor. Umbrella issue: #71 (`epic:ha-addon`).

The July design (`design/adrs/0005-ha-addon-packaging.md`, `design/research/2026-07-07-ha-addon-architecture/`)
is input to this ledger, not inherited by it. Work that has shipped since then changes several of its answers:

- Web API auth (spec 091, `src/hassette/web/auth/`): bearer token, session cookie, default-deny and
  `web_api.trusted_proxies`.
- Config locations (spec 128, `src/hassette/config/locations.py`): apps default to `<config home>/apps`,
  `hassette run --check` prints resolved locations, and exit code 78 marks deterministic startup errors.
- The companion integration (`hass-hassette`, ADR-0006): it is an API client of hassette, configured with
  a URL and token.
- Supervisor itself: add-ons became "apps", and `app_config` replaced `addon_config`.

Each decision is checked against established add-ons in `design/research/2026-10-10-ha-addon-conventions/research.md`
(about 20 add-ons surveyed: Music Assistant, Frigate, ESPHome, Z2M, AppDaemon, Node-RED, Matter, Z-Wave JS and
others). Where a decision diverges from that convention, its table says so.

The work spans three repos: hassette (ingress base path, `base_url` paths, the `web_api.token_file` setting,
the add-on variant image and its glue, the shared `docker_start.sh` changes in D4 and D9, #2331's import check
per D15, the release job), a new `NodeJSmith/hassette-addon` repo (manifest and
store docs, per D2), and `hass-hassette` (discovery pairing, per D13).

The glue pins the settings the add-on owns through environment variables and never computes a value hassette
resolves itself (D6, D7, D8, D10, D13).

In scope: changes to hassette that the add-on needs, including the shared `docker_start.sh` entrypoint (D4's
offline retry, degraded start, whole-script TERM trap and add-on remedy text; D9's `python_packages` step) and
#2331's post-install import check (D15), the add-on package itself (manifest, image, entrypoint glue, store
docs), its release path, the integration's discovery pairing, and the user docs. Out of scope: `hassette build` (#616),
an edge channel, web UI features beyond what ingress needs, and HACS work past pairing the integration with the
add-on.

The decisions below settle the shape. The milestone's Done-when and issue breakdown come from this ledger
once it's ratified.

## Decisions

### D1: Does v0.1 serve the web UI through ingress, or only on a direct port?

**Deciding factor:** the add-on experience HA users expect, at a cost that is bounded and known.

Ingress serves the UI in HA's sidebar behind HA's own login, proxying through Supervisor at
`/api/hassio_ingress/<token>/`. The frontend currently assumes it lives at `/`, so ingress needs base-path
support. That is eight known sites: `BASE_URL = "/api"` (`frontend/src/api/client.ts:3`, also used by
the login flow's `postSession`), `WS_PATH` plus `location.host` (`frontend/src/api/endpoints.ts:46`,
`frontend/src/hooks/use-websocket.ts:50-51`), `window.location.assign(LOGIN_PATH)`
(`frontend/src/lib/query-client.ts:21`), wouter's absolute routes (`frontend/src/app.tsx`), Vite's default
`base: "/"` (`frontend/vite.config.ts`), the absolute icon href (`frontend/index.html`), the five absolute
`url("/fonts/…")` references in `frontend/src/styles/fonts.css:15,26,37,48,59` (CSS `url()` resolves against
the stylesheet, not `<base href>`), and `index.html` served as a static file by `spa_catch_all`
(`src/hassette/web/app.py:141-157`). The build confirms the list is complete with a grep for absolute paths
and an e2e test under a URL prefix, which gates creating the `hassette-addon` repo (Build). Since spec 091,
the direct port uses token login, so it is no longer an unauthenticated exposure.

Behavior to pin:

- `config.yaml` sets `ingress: true`, `ingress_port: 8126`, `panel_icon: mdi:home-automation` and
  `panel_title: Hassette`, with no `ingress_entry` (the default `/`) and no `webui:` key. The direct port is
  declared as `ports: {8126/tcp: null}`, so it is unmapped until the user enters a host port, with a
  `ports_description` entry naming it as the direct web UI and API with token login.
- The backend injects `<base href>` from `X-Ingress-Path` only when the request comes from a
  `trusted_proxies` peer and the value matches `^/api/hassio_ingress/[A-Za-z0-9_-]+$`. It emits the value with
  a trailing `/` appended, HTML-escaped. Without the slash the browser treats the token as a filename and
  resolves relative URLs one segment too high. Any other request gets `/`.

| | A: Ingress in v0.1; direct port optional, off by default | B: Direct port + token login only; ingress in v0.2 |
|---|---|---|
| First-run experience | Install, start, then click the sidebar entry. No token, no port | Map a port, find the token, browse to `http://<host>:<port>` |
| HA conventions (UI add-ons: Node-RED, Z2M, ESPHome use ingress; AppDaemon doesn't) | Matches | Diverges |
| Work in hassette before the add-on can ship | Base path in the frontend + backend `<base href>` injection | None for the UI |
| Risk | Frontend base-path work, with no existing test coverage under a prefix. Eight known sites, plus e2e coverage under a prefix | Low |
| Later cost | None | A second release that changes how users reach the UI, and the token-surfacing problem (D8) becomes the main path, not the fallback |
| Benefit outside the add-on | Reverse-proxy users serving hassette under a sub-path | None |

**Recommendation:** A. Ingress is what makes it feel like an add-on and not a container with extra steps.
The frontend work is now a known list of sites, not open-ended, and it also unblocks sub-path reverse proxies.
**Pick B instead if** getting HAOS users onto hassette sooner matters more than the first-run experience, and
you accept that v0.2 will change how they reach the UI.
**Reversibility:** easy (ingress can be added in a later release, or the port enabled by default, without
migrating user data)
**Challenge:** the base-path site list and `<base href>` trust rule, and the prefix e2e gate before the add-on repo is created, came from challenge findings; choice unchanged.
**Ratified:** Chose ingress in v0.1 with the direct port optional and off by default, over direct-port-only, so the add-on gives the sidebar, no-token experience HA users expect, accepting frontend base-path work in this milestone.

### D2: Where does the add-on package live?

**Deciding factor:** follow the convention established add-ons use, unless it costs something real.

Prior art (`design/research/2026-10-10-ha-addon-conventions/research.md`, which has the counts): every surveyed
add-on lives in a separate add-on repo. That includes the ones owned by their upstream project (Music Assistant, Frigate, ESPHome,
Z2M, evcc). Channels, when added, are sibling folders in that repo with their own slugs (`music_assistant_beta`).
Supervisor clones a custom repository at depth 1 and treats every `config.{yaml,json}` below its root as an
add-on (`~/source/supervisor/supervisor/store/data.py:150-165`, `store/git.py:192`). A hassette checkout is
about 42 MB.

| | A: Separate repo `NodeJSmith/hassette-addon` | B: Folder in this repo (`repository.yaml` at the root, add-on in `addon/hassette/`) | C: Inside `hass-hassette` |
|---|---|---|---|
| Convention | Every surveyed add-on | None surveyed | None surveyed |
| Version lockstep with hassette | hassette's release job commits the bump to the add-on repo (D12) | release-please `extra-files` | Cross-repo, plus the integration's own version line |
| Store URL users add | `…/hassette-addon` | `…/hassette` | The integration's URL, which is confusing |
| Clone cost on each Supervisor | Tiny | ~42 MB, then deltas | Small |
| Stray `config.yaml` read as an add-on | No risk | Needs a lint guard forever | Low |
| Room for channels (edge, beta) | Sibling folders, as Music Assistant does | Possible, but they crowd the framework repo | Awkward |
| CI | A small workflow for lint/validation (`frenck/action-addon-linter` or equivalent) | Existing CI | Mixed |

**Recommendation:** A. It is the universal convention. It keeps the store clone tiny and leaves room for channels.
The one thing B offered was free lockstep versioning, and D12 gets that by having hassette's release job push the
bump.
**Pick B instead if** you want a single repo above all and accept diverging from every surveyed add-on.
**Pick C instead if** you want HA-side distribution in one repo.
**Reversibility:** hard (the repository URL is what users add to their store)
**Ratified:** Chose a separate `NodeJSmith/hassette-addon` repo over a folder in hassette or `hass-hassette`, to match the convention every surveyed add-on follows and keep the store clone small with room for channels, accepting cross-repo version bumps (D12).

### D3: Which image does Supervisor run?

**Deciding factor:** a prebuilt image, as every surveyed add-on uses, without changing how Docker users' image
behaves, apart from a clean exit 0 on stop (D4).

Prior art (`research.md`): every surveyed add-on uses a prebuilt registry image; none relies on Supervisor's local build. HA's
docs call prebuilt "the preferred method", with a generic multi-arch name in `image:` and the tag taken from
`version:`. Upstream-owned add-ons either run the upstream image verbatim (Music Assistant, Frigate, evcc,
ring-mqtt; their entrypoints read `/data/options.json`), or run an add-on variant that upstream CI builds
(ESPHome's `ghcr.io/esphome/esphome-hassio`, from an upstream-owned `docker/ha-addon-rootfs`).

hassette's image runs as `USER hassette` (uid 1000; `Dockerfile:103`). Supervisor mounts `/data` and the
`app_config` folder root-owned, and every surveyed add-on runs as root (D5). hassette publishes
`<version>-py3.11`…`-py3.14` multi-arch tags from `.github/workflows/build_and_publish_image.yml`.

| | A: Add-on variant built by hassette's CI: `ghcr.io/nodejsmith/hassette-addon`, `FROM` the just-built `hassette:<version>-py3.14`, adding `USER root` and the glue entrypoint (ESPHome pattern) | B: The stock image verbatim (Music Assistant pattern): `image: ghcr.io/nodejsmith/hassette`, glue and Supervisor detection in `docker_start.sh` | C: Supervisor builds a thin add-on `Dockerfile` locally |
|---|---|---|---|
| Convention | Upstream-built variant (ESPHome) | Upstream image verbatim (Music Assistant, Frigate, evcc, ring-mqtt) | None surveyed |
| Docker users' image | Unchanged behavior; the shared entrypoint gains add-on-gated branches, plus a clean exit 0 on stop (D4) | Must start as root and drop to uid 1000 when not under Supervisor (a `gosu`/`setpriv` step for every Docker user), or switch Docker users to root | Same as A |
| Supervisor code in the main image | Only D4's add-on-gated branches in `docker_start.sh`, dormant for Docker users; options translation stays in the variant's glue | Options translation and detection, dormant for Docker users | Same as A |
| CI cost | One more build target in the existing image workflow, stable Python only | None | None |
| Where the glue lives | `docker/addon/` in hassette (beside the image it extends) | `scripts/docker_start.sh` | `hassette-addon` repo |
| Install on a Pi | Pull only | Pull only | Pull plus a local build; store marks it as built locally |

**Recommendation:** A. It is the prebuilt convention, and Docker users' image behaves as it does today apart from a clean exit 0
on stop: its only Supervisor-specific code is D4's add-on-gated branches in the shared entrypoint.
Building the variant in hassette's own workflow means the variant can't be published without the image it
extends, and the add-on repo stays pure metadata (`config.yaml`, docs, icons), as Music Assistant's and
Frigate's are. The variant is published as `ghcr.io/nodejsmith/hassette-addon:<version>`, multi-arch (amd64,
arm64), with the bare tag equal to `config.yaml`'s `version:`, because Supervisor pulls `image:` at that tag
(Assumed: image pull). The stock image's `<version>-py3.<minor>` tags don't fit that scheme. The variant
carries the `io.hass.type=app`, `io.hass.arch` and `io.hass.version` labels HA's docs ask prebuilt images for.
Supervisor's install check compares the image's OS architecture, not these labels
(`~/source/supervisor/supervisor/docker/interface.py:611-641`), and takes the version from `config.yaml`
(`docker/app.py:206-208`), so they follow convention rather than gate installation.
**Pick B instead if** you'd rather publish one image for everything and accept a privilege-drop step in every
Docker user's entrypoint.
**Pick C instead if** you want no CI change at all and accept being the only surveyed add-on built on-device.
**Reversibility:** easy (switching `image:` later is invisible to users beyond the update)
**Ratified:** Chose an add-on variant image built by hassette's image workflow (`ghcr.io/nodejsmith/hassette-addon`, `FROM` the release image with `USER root` and the glue) over the stock image verbatim or a local build, to follow the prebuilt convention while leaving Docker users' image behavior unchanged apart from D4's clean exit 0 on stop, accepting one more build target in CI.

### D4: What runs the process inside the add-on container, and how are startup failures handled?

**Deciding factor:** reuse the tested Docker entrypoint, make a broken config sit visibly stopped instead of
looping, and bring a correctly configured add-on back after a reboot even when the network isn't up yet.

The image's entrypoint is `tini -- /app/scripts/docker_start.sh` (`Dockerfile:117`). It runs
`hassette run --check`, installs user deps, then `exec hassette run`. On an unrecoverable error it prints a
banner, idles `HASSETTE_DOCKER_RETRY_DELAY` seconds (default 300), then exits so Docker retries
(`scripts/docker_start.sh:56-84`, spec 128 D12). Exit 78 marks deterministic config errors, and spec 128
designed it as a contract for "the add-on's s6 `finish` script".

The dependency install runs on every start, not only the first: `/app/.venv` resets on each start (Assumed:
container removal), so the `uv.lock` and `python_packages` (D9) installs run again on each restart, reboot and
update. Only `/data/uv_cache` persists (D10). After a power cut, HAOS often boots
before the router and WAN, so a network failure during the install is a normal boot event, not a rare blip.
`uv` without `--offline` contacts the index even when the cache is warm (no `--offline` anywhere in
`scripts/docker_start.sh`).

Unlike Docker's restart policy, Supervisor restarts an exited add-on only with the add-on's **Watchdog** toggle
on, and the toggle is off by default, so an exited add-on normally stays stopped with its log showing why. With
the toggle on, container-exit restarts are throttled (Assumed: Watchdog).

`init: false` is valid with a non-HA base image whose own init is PID 1, and every surveyed add-on sets it
(`research.md`). Supervisor logs a warning when an add-on exits 143 on SIGTERM (Assumed: exit 143), so hassette
must exit 0 on a clean stop (`src/hassette/server.py:68` installs the SIGTERM handler; Build verifies the exit
code). Supervisor's default stop timeout, 10 s after SIGTERM (Assumed: stop timeout), is less than hassette's
30 s shutdown budget (`total_shutdown_timeout_seconds`, `src/hassette/config/models.py:357`).

| | A: tini + `docker_start.sh` with its 300 s retry idle. Glue script runs first, then `exec`s `docker_start.sh` | B: s6-overlay service on an HA base image (`rootfs/etc/s6-overlay/s6-rc.d/hassette/{run,finish}`), `finish` halting the container on non-zero exit | C: tini + `docker_start.sh` with `HASSETTE_DOCKER_RETRY_DELAY=0`: banner, then exit at once | D: C, plus a network fallback: a timeout or network-class `uv` failure retries with `uv --offline` against `/data/uv_cache`; if that fails too, hassette starts with a banner naming the missing install |
|---|---|---|---|---|
| Reuses the tested entrypoint (`tests/` cover `docker_start.sh`) | Yes | No: dep install and the `--check` handshake are reimplemented or called from `run` | Yes | Yes |
| Config error, Watchdog off (default) | Shows "running" while idling, then exits and stays stopped after 300 s. Misleading for 5 minutes | Stops at once and stays stopped | Stops at once and stays stopped; banner is the last log line | Same as C |
| Config error, Watchdog on | Retries every ~300 s indefinitely | Restarted with backoff until the throttle gives up | Same as B | Same as B |
| Network down during the every-start install (boot before the WAN) | Heals by itself after the 300 s idle | Heals only if Watchdog is on | Heals only if Watchdog is on | Heals with Watchdog off when the cache is warm; otherwise runs with a banner, and apps needing the missing package fail to import visibly |
| Real dependency errors (resolution conflicts) | Banner, retries | Stops | Stops with the banner | Stops with the banner, as C |
| Fits D3 A (variant `FROM hassette`) | Yes | No: s6 needs an HA base image or s6 layered onto the hassette image, plus `run`/`finish` scripts replacing the tested entrypoint | Yes | Yes |
| Needs verification | No | No | No | That `uv --offline` installs from the persisted cache with the network blocked (Build) |
| Convention (prior art, `research.md`) | Single-process upstream images exec under tini (Z2M, Music Assistant), but none idles then retries | AppDaemon, Node-RED and most hassio-addons; most s6 images halt on failure | Single-process upstream images (Z2M, Music Assistant) | As C |

**Recommendation:** D. It keeps C's single tested startup path and its visibly stopped add-on for a broken
config, and it stops a WAN outage at boot from leaving automations down until someone opens the add-on page.
The venv still holds hassette itself, so running degraded beats not running. Unlike a retry loop, it doesn't
lengthen the pre-serve phase that D14's start period has to cover. The 300 s idle exists for Docker's
unbounded restart policy, which Supervisor doesn't have.
**Pick C instead if** the Build check shows `uv --offline` can't install from the cache alone, accepting that
transient install failures heal only with Watchdog on (DOCS.md already recommends it, D14).
**Pick A instead if** you want transient failures to heal without users turning on Watchdog, accepting an add-on
that looks "running" while it's actually broken.
**Pick B instead if** you want the s6 layout most hassio-addons use, and accept replacing the tested entrypoint.

Behavior to pin:

- A `uv` timeout or network-class failure (the index can't be reached) retries the same install with
  `--offline`. If that also fails, hassette starts and the log shows a banner naming the install that
  didn't run. A resolution conflict or a config error (exit 78) halts as today, with no offline retry.
- `config.yaml` sets `timeout: 45`: hassette's `total_shutdown_timeout_seconds` (30,
  `src/hassette/config/models.py:357`) plus margin, so a stop never kills hassette mid-shutdown.
- The glue sets `HASSETTE_DOCKER_RUNTIME=addon` (the `HASSETTE_DOCKER_` prefix keeps it out of the settings
  namespace, spec 128 D6). Every add-on-specific behavior in the shared `docker_start.sh` runs only under it:
  the offline retry and degraded start above, the remedy text ("Fix … then restart the add-on from its page"
  in place of the Docker commands at `scripts/docker_start.sh:30-35`), and the `python_packages` install step
  (D9). Without it, Docker users keep today's behavior, including the 300 s halt idle, apart from the TERM
  trap below.
- `docker_start.sh` traps TERM for the whole script, unconditionally, so stopping the container during the
  install exits 0, not 143. Today the script traps only EXIT (`scripts/docker_start.sh:50`), and TERM only
  inside the halt idle (`:74`). A TERM during the halt idle exits 0 as well, replacing `exit 143` at `:74`.
  Docker users get the same clean exit 0 on stop as a side benefit; it is the only change they see.
- The glue sets `HASSETTE_DOCKER_RETRY_DELAY=0` on every start, so `halt` exits at once instead of idling
  (`scripts/docker_start.sh:57-78`).
- The glue sets `HASSETTE_DOCKER_PRUNE_UV_CACHE=0`. `/data/uv_cache` is the persistent cache the offline retry
  installs from (D10), and the default per-start `uv cache prune` (`scripts/docker_start.sh:17,325-328`) could
  discard entries that retry needs.
- Glue steps that fail before `docker_start.sh` runs (seeding, the DB restore in D10) can't use
  `docker_start.sh`'s `halt` (`scripts/docker_start.sh:57-78`), which isn't loaded yet. The glue has its own
  minimal banner function that prints the same banner format with add-on remedies and exits at once. The
  discovery announce never fails the start (D13).
- Exits after `exec hassette run` are outside this fallback. A `FatalError` such as
  `CouldNotFindHomeAssistantError` (`src/hassette/core/websocket_service.py:436-440`) still leaves the add-on
  stopped when Watchdog is off, which is why DOCS.md recommends Watchdog on from install (D14).

**Reversibility:** easy
**Challenge:** the every-start install and network fallback, the stop timeout, and the add-on remedies, glue banners and TERM trap came from challenge findings.
**Ratified:** Chose tini + `docker_start.sh` with no retry idle, `init: false`, a `uv --offline` retry on network-class failures and a degraded start with a banner if that fails, halting only on config errors and dependency conflicts, over the 300 s idle, an s6 rewrite or plain fail-fast, so a correctly configured add-on comes back after a reboot without Watchdog while real errors stop visibly, accepting a degraded start when dependencies can't install and `timeout: 45`, add-on remedy text and a whole-script TERM trap as new entrypoint behavior.

### D5: Which user does hassette run as inside the add-on?

**Deciding factor:** the add-on works with Supervisor's root-owned mounts and no ownership fix-up step.

The image runs as `USER hassette` (uid 1000) and pre-creates `/config` and `/data` owned by 1000
(`Dockerfile:97-98,103`). Supervisor bind-mounts `/data` and the `app_config` folder from the host, owned
by root, over those paths. As uid 1000, hassette can't create `/data/hassette.db` or
`/config/.web_api_token` (D8).

| | A: The add-on variant image (D3 A) sets `USER root` | B: Stay uid 1000; the glue script `chown`s the mounts first (needs root at start, then drops privileges with `setpriv`/`gosu`) | C: Stay uid 1000; rely on Supervisor-side ownership |
|---|---|---|---|
| Works with root-owned mounts | Yes | Yes | No: Supervisor doesn't chown add-on mounts |
| Moving parts | One line | A privilege drop and a recursive chown on each start | None, but broken |
| Files users see in `app_configs/` | Owned by root, like every other add-on's | Owned by 1000 | n/a |
| Convention (prior art) | Every surveyed add-on runs as root; Matter Server sets `USER root` over its upstream image | None found | n/a |

**Recommendation:** A. It is the add-on convention, and the add-on container is already isolated by
Supervisor. Running as root also lets user deps install into `/app/.venv` (owned by 1000, writable by root).
**Pick B instead if** you want defense in depth against user app code writing outside its directories.
**Reversibility:** easy
**Ratified:** Chose running as root (the variant image sets `USER root`) over chown-and-drop or staying uid 1000, to match every surveyed add-on and work with Supervisor's root-owned mounts, accepting no in-container privilege separation for user app code.

### D6: How does hassette reach HA through Supervisor's proxy?

**Deciding factor:** fewest new settings, and correct behavior for every `base_url` users already have.

With `homeassistant_api: true`, Supervisor proxies HA at `http://supervisor/core/api/...` for REST and at
`ws://supervisor/core/api/websocket` (among others) for WebSocket, accepting the `SUPERVISOR_TOKEN` it injects
into the container (Assumed: Supervisor proxy). hassette won't start without an HA token
(`config.require_token()`, `src/hassette/server.py:61`), and none of the token's accepted names (`token`,
`hassette__token`, `ha_token`, `home_assistant_token`; `src/hassette/config/config.py:181-184`) is
`SUPERVISOR_TOKEN`, so the glue has to map it. hassette builds both URLs
from `base_url`'s scheme, host and port only, and drops any path (`src/hassette/utils/url_utils.py:45-51`).
So `base_url = "http://supervisor/core"` would produce `http://supervisor/api/`.

| | A: `base_url` keeps its path prefix (REST `<base>/api/`, WS `<base>/api/websocket`) | B: New optional `api_url` / `ws_url` overrides (the July plan) |
|---|---|---|
| Add-on config | `base_url = "http://supervisor/core"` | Two URLs |
| New settings | None | Two, plus precedence rules against `base_url` |
| Today's users | Unchanged unless their `base_url` has a path. Today such a path is silently dropped, so this is a fix (HA served under a sub-path behind a proxy) | Unchanged |
| Also serves | HA behind a sub-path proxy | Any proxy whose REST and WS paths don't share a prefix (none known) |
| Breaking risk | A `base_url` with a stray trailing path that works today by accident would start using it. The build must decide whether a lone `/` or trailing slash counts as a path (it shouldn't) | None |

**Recommendation:** A. Supervisor exposes `/core/api/websocket`, so the standard `<base>/api/...` shape
works and no new setting is needed. Honoring the path is also the less surprising behavior.
**Pick B instead if** a known deployment needs REST and WS on unrelated paths.

Behavior to pin:

- hassette logs the resolved REST and WebSocket URLs, path included, at INFO on startup, with no special case
  for `/core`. A user whose pasted `base_url` (`http://ha.local:8123/lovelace/0`) worked by accident sees the
  cause in the log, not only a 404. The PR carries a `BREAKING CHANGE:` footer, and the upgrading docs note
  that `base_url` paths are now honored.
- `config.yaml` sets `homeassistant_api: true`.
- On every start the glue sets `HASSETTE__BASE_URL=http://supervisor/core` and
  `HASSETTE__TOKEN="$SUPERVISOR_TOKEN"` (`HASSETTE__TOKEN` matches the `hassette__token` alias). Both are
  add-on-owned settings on D7's list: a `base_url` or `token` in `hassette.toml` or `/config/.env` is
  overridden, since process environment outranks both (`src/hassette/config/config.py:115-124`).

**Reversibility:** easy
**Challenge:** the startup URL log and breaking-change footer came from challenge findings; choice unchanged.
**Ratified:** Chose making `base_url` keep its path prefix (REST `<base>/api/`, WS `<base>/api/websocket`; a lone `/` or trailing slash is not a prefix) over new `api_url`/`ws_url` settings, so the add-on's glue pins `base_url = "http://supervisor/core"` and maps `SUPERVISOR_TOKEN` to `token` with no new settings, accepting a user-visible behavior change for any `base_url` whose path is silently dropped today.

### D7: How does ingress traffic authenticate, and who sees the panel?

**Deciding factor:** ingress needs no hassette login, everything else keeps token auth, and the listener the
manifest names is always the one hassette serves.

Supervisor proxies ingress from `172.30.32.2` after HA has authenticated the user. A `trusted_proxies` peer
that sends no `Authorization` header skips the token check (`src/hassette/web/auth/__init__.py`
`resolve_auth_outcome`, `WebApiConfig.trusted_proxies` in `src/hassette/config/models.py`). Peer matching
uses the raw ASGI peer, never forwarded headers (`web/auth/trusted_proxies.py`).

Prior art: add-ons with their own auth trust the ingress peer and keep auth elsewhere (ESPHome's peer guard,
Frigate's unauthenticated ingress port, Music Assistant's separate ingress listener). ESPHome's
CVE-2026-59177 came from skipping auth for ingress without enforcing the peer in the app, on a listener reachable
from the LAN. `trusted_proxies` is that enforced peer check. `panel_admin` is mixed: most keep the default
`true`, while Frigate and Music Assistant (media and camera viewing) set `false`.

`ingress_port`, the `watchdog:` URL and the discovery payload all name port 8126 and assume hassette serves on
`0.0.0.0` with the UI and auth on. Those are ordinary settings (`src/hassette/config/models.py:448-472`:
`run`, `run_ui`, `host`, `port`, `auth_enabled`) in the `hassette.toml` that D10 seeds and invites users to edit. Environment
variables outrank `hassette.toml` (`src/hassette/config/config.py:115-124`).

The table covers gateway trust and the listener. `panel_admin` and the `X-Remote-User-*` headers are stated
parts below it.

| | A: The glue pins `trusted_proxies` and the listener settings via env on every start | B: As A, but a `hassette.toml` that sets a conflicting listener halts the start (exit 78, banner) | C: A separate ingress-only listener that trusts the gateway (Music Assistant, Frigate) | D: As A, but `trusted_proxies` is set only when the direct port is unmapped |
|---|---|---|---|---|
| Ingress needs no hassette login | Yes | Yes | Yes | Only while the direct port is unmapped |
| A `hassette.toml` that sets another listener | Overridden; DOCS.md says so | The add-on stops until the user removes it | Ingress unaffected; the main listener still needs A's pins for the `watchdog:` URL and discovery | Overridden, as A |
| Gateway-only trust rests on | A HAOS check that a mapped-port client never presents as `172.30.32.2` (Build) | Same as A | Structure: the ingress listener is never mapped | Structure while unmapped; mapping the port turns trust off |
| hassette changes | None | A conflict check before start | A second listener in the web server | None; the glue reads the port mapping |
| Convention | A trusted, app-enforced ingress peer, as ESPHome's peer guard | None surveyed | Music Assistant, Frigate | None surveyed |

**Recommendation:** A. It keeps ingress login-free whether or not the port is mapped, keeps the manifest's
port true no matter what `hassette.toml` says, and needs no hassette change. The glue sets, on every start:

- `HASSETTE__WEB_API__TRUSTED_PROXIES='["172.30.32.2"]'`, whether or not the user maps the direct port.
- `HASSETTE__WEB_API__HOST=0.0.0.0`, `HASSETTE__WEB_API__PORT=8126`, `HASSETTE__WEB_API__RUN=true`,
  `HASSETTE__WEB_API__RUN_UI=true` and `HASSETTE__WEB_API__AUTH_ENABLED=true`.

DOCS.md lists these as add-on-owned settings that `hassette.toml` can't change, alongside `base_url` and
`token` (D6), `web_api.token_file` (D8) and the DB path (D10), all pinned the same way, and says environment
overrides `hassette.toml`. This follows D9's documented precedent of options overriding `hassette.toml`.
DOCS.md also marks `web_api.auth_token` as "do not set in the add-on". It is not pinned, and a configured value
still wins over the token file, with a WARNING (D8).

Requests from any peer other than the gateway, including the direct port and the HACS integration, need the
token. The July plan's `allowed_client_ips` and its `hassio_api` port-mapping query are dropped; auth already
covers what they did.

`panel_admin` stays at its default (`true`). That hides the sidebar entry from non-admins. It doesn't restrict
access: `panel_admin` only sets the panel's `require_admin`
(`~/source/core/homeassistant/components/hassio/addon_panel.py:120`), while the ingress view itself has
`requires_auth = False` (`hassio/ingress.py:67`) and is gated by a Supervisor ingress session that any
logged-in user can create, because Core exempts the ingress session endpoints from admin checks
(`hassio/websocket_api.py:50-58`). Any logged-in HA user holding the ingress URL gets full start, stop and
reload. DOCS.md says so plainly. Real enforcement (resolving the ingress user's admin status) is a follow-up
issue, out of scope for v0.1.

Supervisor's ingress adds `X-Remote-User-*` headers naming the HA user (id, username, display name; no admin
flag). v0.1 ignores them: they are only trustworthy from the gateway peer, and nothing in hassette needs a
per-user identity yet.

Gateway trust rests on a mapped direct-port client never presenting as `172.30.32.2`. The failure direction is
mostly safe: a LAN client shown as the gateway `.1` or a userland-proxy address is untrusted and needs the
token; only `.2` is dangerous. The build verifies this on a real HAOS host and records the result in the
Addendum (Build). At start, the glue logs the add-on's port mappings (the `network` field of
`GET http://supervisor/addons/self/info`, which needs no `hassio_api`, Assumed), so a support log shows
whether the direct port is exposed.

Behavior to pin: a `hassette.toml` that sets another `web_api.port`, `host`, `run`, `run_ui` or `auth_enabled`
still serves `0.0.0.0:8126` with the UI and auth on.

**Pick B instead if** you'd rather a `hassette.toml` that sets another port fail loudly than be silently
overridden.
**Pick C instead if** you want the gateway-only property to be structural rather than verified once, or the
HAOS check comes back ambiguous.
**Pick D instead if** the HAOS check finds a mapped port can present clients as `172.30.32.2`, accepting that
mapping the port turns off login-free ingress.
**Pick `panel_admin: false` instead if** non-admin household members should see hassette's dashboard in the
sidebar. Access is the same either way.
**Reversibility:** easy
**Challenge:** the listener pins, the HAOS gateway check as a Build item with the port-mapping log, and `panel_admin` as a sidebar hint only came from challenge findings.
**Ratified:** Chose the glue pinning `trusted_proxies = ["172.30.32.2"]` plus the listener settings (`host`, `port`, `run`, `run_ui`, `auth_enabled`) via env, token auth for every other peer, and `panel_admin: true` documented as hiding the sidebar entry only, over halting on a conflicting listener, trusting only when the port is unmapped, or a separate ingress listener, so ingress is login-free and the manifest's port is always true, accepting that `hassette.toml` edits to those settings are overridden and that the HAOS gateway check is a Build item; real admin enforcement is a follow-up.

### D8: How does a user who isn't pairing through discovery get the web API token?

**Deciding factor:** one resolver decides the token and every consumer reads what it decided, and direct-port
and CLI users can get the token without shell access, given that the integration gets it from discovery (D13).

The token is resolved from `web_api.auth_token`, else `<data_dir>/.web_api_token`, else generated and written
there atomically at mode 0600. A blank configured token or an empty, corrupt or unreadable file falls through
to the next step, and a log line names the file but not the value (`src/hassette/web/auth/tokens.py:28-88`).
`WebApiService` resolves it before the server starts serving (`src/hassette/core/web_api_service.py:109`,
server built at `:151`). In the add-on, `data_dir` is `/data`, which Samba, File Editor and Studio Code Server
can't see. If D13 ships discovery, the HACS integration receives the token automatically. This decision then
covers only users who map the direct port or point the `hassette` CLI at the add-on, plus which component
writes the token the discovery payload carries. Prior art has no strong convention here: Music Assistant
relied on discovery.

| | A: The glue keeps the token in `/config/.web_api_token` (visible in `app_configs/`) and exports it as `HASSETTE__WEB_API__AUTH_TOKEN` | B: Show the token in the web UI (ingress-authenticated admins), e.g. a "Connect" panel on the system page | C: A password-type add-on option `api_token`; blank means generate | D: hassette gains a `web_api.token_file` setting (default `<data_dir>/.web_api_token`); the glue sets it to `/config/.web_api_token` and reads the file back once hassette serves |
|---|---|---|---|---|
| User effort | Open a file in File Editor | Click in the sidebar UI | Read a masked field in the Configuration tab | Open a file in File Editor |
| Sources of truth for the token | Two: the glue's file and hassette's resolver. A blank file makes hassette generate a different token while the glue announces the blank one | One | Two: the option and the resolver | One: hassette's resolver |
| Blank, corrupt or unwritable file | New bash logic | n/a | n/a | Existing, tested resolver logic |
| hassette changes | None | New API endpoint + frontend view | None, unless the generated value is written back (`hassio_api` + `POST /addons/self/options`) | One setting read by the existing resolver |
| Benefits outside the add-on | None | Docker users get it too | None | Docker users can place the token file anywhere |
| Secret exposure | Backups, and anyone with file access to `app_configs` (same as `hassette.toml`) | Anyone with an authenticated session | Backups and the options UI | Same as A. `/data` is backed up too, so no location avoids backups |
| Fits D13 | The glue reads the file it wrote, whether or not hassette uses it | Independent | The glue reads the option | The glue reads the file after `/api/health/live` answers, when it holds the token hassette serves with |

**Recommendation:** D. hassette already handles blank, corrupt and unwritable files and writes atomically at
0600, so moving the file costs one setting where keeping the glue as owner re-implements the resolver in
bash. The glue exports no `HASSETTE__WEB_API__AUTH_TOKEN`; it sets `HASSETTE__WEB_API__TOKEN_FILE=/config/.web_api_token`
and reads the file only after hassette is serving, to build the discovery payload (D13). The existing
`cli.token_file` (`CliConfig`, `src/hassette/config/models.py:736`) is a different, client-side setting: the
credential the `hassette` CLI sends to a target. `web_api.token_file` is where the server keeps its own token,
so the two don't duplicate each other.
**Pick A instead if** keeping hassette unchanged for this milestone outweighs a second token source,
accepting bash-side checks for a blank file and a verify step once hassette serves.
**Pick B instead if** you want a UI flow every deployment benefits from, and accept frontend work in this
milestone. **Pick C instead if** you want the token visible in the add-on's own UI.

Behavior to pin:

- With `web_api.token_file` set and no `auth_token`, hassette reads that file, or generates a token and writes
  it there atomically at 0600. With it unset, the path stays `<data_dir>/.web_api_token`.
- An empty or corrupt token file is replaced by a fresh token at the same path.
- A configured `web_api.auth_token` still wins over the file (`src/hassette/web/auth/tokens.py:66-71`). In the
  add-on that would leave the file stale and the discovery payload wrong. So `web_api.token_file` is pinned
  with the add-on-owned settings (D7), DOCS.md marks `web_api.auth_token` as "do not set in the add-on" (it is
  not pinned), and hassette logs a WARNING when a configured `auth_token` overrides an explicitly set
  `token_file`.
- DOCS.md gives the rotation procedure: delete `/config/.web_api_token` and restart the add-on. hassette
  writes a new token, the glue announces the changed payload, and the integration picks it up on its next 401
  with no user input (D13).
- The new setting is documented in the web API config reference for Docker users too.

**Reversibility:** easy
**Challenge:** the single token owner, the rotation procedure and the 0600 mode came from challenge findings.
**Ratified:** Chose a new general `web_api.token_file` setting that the glue points at `/config/.web_api_token`, with hassette's resolver owning generation and the glue reading the file only after hassette is serving, over the glue owning the token, a UI panel or an options field, so one resolver decides the token every consumer reads, accepting a hassette change, the token in backups, and a documented rotation procedure.

### D9: Which settings appear in the add-on's Configuration tab?

**Deciding factor:** every option is a support question. Add only what can't live in `hassette.toml`, or what
users of code-hosting add-ons expect to find there.

Connection settings are automatic (D6). Project installs from `uv.lock` happen whenever a lockfile exists
(`scripts/docker_start.sh` step 1). `requirements.txt` installs are opt-in through `HASSETTE_DOCKER_INSTALL_DEPS`
(step 2). Log level reads `HASSETTE__LOGGING__LOG_LEVEL` (`src/hassette/config/helpers.py:76-78`).

Prior art (`research.md`): the surveyed add-ons keep options minimal: log level, a few toggles and package lists. Code-hosting
add-ons take extra packages as **option lists** installed on each start: AppDaemon has `python_packages`,
`system_packages` and `init_commands`, and Node-RED has `npm_packages`. None documents a `requirements.txt` in
the config dir. Z2M documents that options "take precedence" over its config file; the others don't say.

| | A: `log_level` + `install_requirements` toggle | B: `log_level` + `python_packages` list (AppDaemon style) | C: `log_level` only; `requirements.txt` and `uv.lock` installs always on |
|---|---|---|---|
| Convention | Toggle for a file convention: unusual | Matches AppDaemon/Node-RED | Minimal, like Music Assistant/Matter |
| Fits hassette's dependency model (`uv.lock` project, `requirements.txt`, constraints) | Directly | A third path: a list installed with the same constraints file | Directly |
| Install surprise | Explicit opt-in | Explicit per package | A stray `requirements.txt` anywhere under `/config` installs on start |
| Options to document | 2 | 2 | 1 |
| Glue and entrypoint complexity | Map a bool to `HASSETTE_DOCKER_INSTALL_DEPS` | A `match()` schema on the option; the glue exports the list, and `docker_start.sh` gains an add-on-gated install step passing each entry as its own argument to a constraints-checked `uv pip install` | None |

**Recommendation:** B. AppDaemon users, who are the people most likely to try hassette, will look for
`python_packages`. Installing the list with the image's constraints file is a few lines of glue, and
users with real projects keep using `uv.lock`, which needs no option. Packages that are set as options rather
than files are also visible in the add-on UI and survive config folder edits. DOCS.md says options override
`hassette.toml` for log level.

Behavior to pin:

- `config.yaml` declares `log_level: list(DEBUG|INFO|WARNING|ERROR|CRITICAL)?` with no entry in `options`,
  since any default makes an option required (HA developer docs, `web-research-config.md`).
  These are exactly hassette's `LogLevel` values (`wire/src/hassette_wire/literals.py:8`, used by
  `LoggingConfig.log_level` at `src/hassette/config/models.py:202`). When the option is set, the glue exports
  it as `HASSETTE__LOGGING__LOG_LEVEL` on every start, so it overrides `hassette.toml`; when it is unset,
  nothing is exported and `hassette.toml` or hassette's own default (`INFO`) applies.
- `config.yaml` declares the `python_packages` option's schema as
  `python_packages: ['match(^[A-Za-z0-9][A-Za-z0-9._\-\[\],<>=!~ ;]*$)']`, single-quoted because `\-`, `\[` and
  `\]` are invalid escapes in a YAML double-quoted string. Supervisor rejects anything but a plain requirement
  specifier when the user saves. The add-on repo's CI validates `config.yaml` against Supervisor's schema, so a
  pattern that doesn't parse fails before release.
- The glue passes the list to `docker_start.sh` as `HASSETTE_DOCKER_PYTHON_PACKAGES`, one entry per line.
  Newline-separated is safe because the schema admits no newline in an entry, and it needs no JSON parser in
  the script.
- The install is a step inside `docker_start.sh`, run only under `HASSETTE_DOCKER_RUNTIME=addon` (D4), on every
  start, after the `uv.lock` project install (step 1) and the requirements step (step 2), so neither can remove
  or conflict with the extra packages afterward.
- The glue leaves `HASSETTE_DOCKER_INSTALL_DEPS` at its default (off, `scripts/docker_start.sh:16`), so step 2 is
  skipped in the add-on; DOCS.md points users with real projects to `uv.lock`.
- The step runs one `uv pip install … -c /app/constraints.txt` with each entry as its own argv element, never
  through a requirements file, so no entry can become a uv option line (`--extra-index-url`, `-r`,
  `--find-links`).
- It follows the same rules as the other install steps: its own timeout constant beside
  `UV_REQUIREMENTS_TIMEOUT_SECS` (`scripts/docker_start.sh:24-27`), counted in D14's `--start-period`, D4's
  `--offline` retry and degraded start on a network-class failure, and a halt on a resolution conflict.
- URL and VCS specifiers are unsupported in v0.1, and DOCS.md points those users to `uv.lock`.

**Pick A instead if** you'd rather add-on users follow the same `requirements.txt` convention as Docker users.
**Pick C instead if** you want a single option and accept implicit installs.
**Reversibility:** easy (adding options later is non-breaking)
**Challenge:** the `match()` schema validation and per-entry argv passing came from challenge findings; choice unchanged.
**Ratified:** Chose `log_level` plus an AppDaemon-style `python_packages` list (validated by a `match()` schema and installed on every start with each entry passed as its own argument to the constraints-checked `uv pip install`) over a requirements toggle or log level alone, so AppDaemon users find the option they expect and packages are visible in the add-on UI, accepting a third dependency path beside `uv.lock` and `requirements.txt`; options override `hassette.toml` for log level, as DOCS.md states.

### D10: What does the add-on seed, and how do its cache and telemetry DB get backed up?

**Deciding factor:** a new user sees something working, backups stay small, and the telemetry DB survives a
restore intact without stopping automations.

`app_config` mounts at `/config`. hassette's config home is then `/config` and apps default to
`/config/apps` (`src/hassette/config/locations.py`). `/data` persists and is included in backups. The image
puts the uv cache at `/uv_cache`, which isn't persisted (`Dockerfile:91,111`).

This decision has three parts. Starter files and the uv cache are stated choices, with their alternatives
inline. Only the telemetry DB has options worth a table.

- **Starter files:** only when `/config` is empty, the glue writes a commented `hassette.toml` and an `apps/`
  directory holding one example app that logs a line. If `/config` holds anything, nothing is seeded, so a
  user with env-only config, a deleted `hassette.toml` or a partial restore never gets the example app beside
  their own. The emptiness check runs before anything else writes to `/config`, including hassette's token
  file (D8). **Pick "seed once per install, marked by `/data/.seeded` written last" instead if** a user who
  clears `/config` on purpose should not get the example back. **Pick "no starter files" instead if** you'd
  rather users copy the example from DOCS.md, keeping the glue script smaller.
- **uv cache:** `UV_CACHE_DIR=/data/uv_cache`, so the every-start install (D4) is warm after the first start
  and D4's offline fallback has something to install from (per-start pruning is off, D4). `backup_exclude` keeps it out of backups. Behavior
  to pin: a backup contains no uv cache files.
- **Telemetry DB:** the table below. The DB at `/data/hassette.db` runs in WAL mode
  (`src/hassette/core/database_service.py:445`). Supervisor's default `backup: hot` tars `/data` while
  hassette writes, so the main file and `-wal` can be captured at different moments and restore torn. The DB
  matters to users now and will matter more, so dropping it from backups isn't the answer.

| | A: `backup: cold` | B: Hot, with `backup_pre` running a WAL checkpoint | C: `backup_exclude` the live DB, `-wal` and `-shm`; restore starts with a fresh DB | D: Hot, with `backup_pre` writing a consistent snapshot to `/data/backup/hassette-snapshot.db` (SQLite online backup API or `VACUUM INTO`); `backup_exclude` the live DB, `-wal` and `-shm`; on start, a missing live DB is restored from the snapshot |
|---|---|---|---|---|
| Restore consistency | Guaranteed | Narrower tear window; writes after the checkpoint can still tear | Guaranteed (no DB) | Guaranteed: the snapshot is one self-consistent file |
| Automations during backup | Stopped for the backup's duration | Running | Running | Running; WAL mode lets writers continue while the snapshot reads |
| History survives a restore | Yes | Usually | No | Yes, up to the snapshot's moment |
| Moving parts | One manifest key | A checkpoint command run by `backup_pre` | One manifest key | A snapshot command run by `backup_pre`, three exclude patterns, a restore step at start |
| Extra disk | None | None | None | A second copy of the DB in `/data/backup` |

**Recommendation (telemetry DB):** D. It is the only option that keeps history, restores consistently, and leaves
automations running. The snapshot command is a short glue script using the venv's Python `sqlite3`, run inside
the container by `backup_pre` (Assumed), so hassette gains no add-on code.

Behavior to pin for D:

- The snapshot is written to a temp file and renamed into place, so a backup never captures a half-written
  snapshot.
- A `hassette.db` exclude pattern would also drop `/data/backup/hassette.db` (Assumed: `backup_exclude`), so
  the snapshot's name must match no exclude pattern, hence `hassette-snapshot.db`. The patterns are exactly `uv_cache`, `hassette.db`, `hassette.db-wal`
  and `hassette.db-shm`. A backup contains the snapshot and none of the live DB files.
- If the snapshot fails, the command logs why and exits 0. A non-zero exit would leave the whole add-on,
  `/config` and the user's apps included, out of that backup (Assumed). The backup then holds the previous
  snapshot.
- On start, before hassette runs, the glue copies the snapshot to `/data/hassette.db` only when the live DB is
  absent and a snapshot exists. A present live DB is never overwritten; that is safe because a restore wipes
  `/data` before copying the backup in, so a stale live DB can't survive one (Assumed: restore). hassette then
  opens it and runs its normal migrations.
- The DB path is add-on-owned like D7's listener settings: the glue pins `HASSETTE__DATABASE__PATH=/data/hassette.db`
  so the snapshot, the exclude patterns and the restore all name the file hassette opens.

**Pick A instead if** you'd rather have no snapshot machinery and accept automations stopping during every
backup. **Pick B instead if** you want the smallest change that keeps history and accept a residual tear risk.
**Pick C instead if** the telemetry history turns out to be disposable.
**Reversibility:** easy
**Challenge:** the WAL-mode hot-backup tear (answered by keeping the DB backed up through a snapshot) and seeding only into an empty `/config` came from challenge findings.
**Ratified:** Chose seeding starter files only into an empty `/config`, `uv_cache` excluded from backups, and hot backups where `backup_pre` writes a consistent SQLite snapshot to `/data/backup/hassette-snapshot.db` (failures logged, exit 0), the live DB files excluded, and a missing live DB restored from the snapshot at start, over cold backups, a WAL checkpoint, or excluding the DB, so telemetry history survives a restore consistently without stopping automations, accepting a snapshot command, a restore step and a second copy of the DB on disk.

### D11: Does `find_project_dir` move into the Python resolver for this milestone?

**Deciding factor:** one tested rule per location, without doing the move where nothing needs it.

The #71 comment (2026-10-09) proposed moving the project-dir walk-up from `scripts/docker_start.sh`
(`find_project_dir`, stopping at `/app`) into `src/hassette/config/locations.py`, with `--check` printing
`PROJECT_DIR`, "before the add-on's s6 scripts copy it". With no s6 scripts (D4), the add-on runs the same
`docker_start.sh` and nothing is copied. The `/app` stop sentinel holds in the add-on too, since the add-on
image is `FROM` the hassette image (D3 A).

**Recommendation:** not in this milestone, because the add-on runs the same `docker_start.sh` (D4). Leave the
#71 comment as a note: if a second entrypoint appears, do the move first, with the stop condition passed in by
each entrypoint.
**Pick "do it anyway" instead if** you want `--check` to report every location for debugging, regardless of
the add-on.
**Reversibility:** easy
**Ratified:** Chose not moving `find_project_dir` in this milestone, because the add-on reuses `docker_start.sh` (D4) on an image `FROM` hassette (D3) where the `/app` sentinel still holds, accepting that the #71 note stays open for a future second entrypoint.

### D12: How does each hassette release reach the add-on store?

**Deciding factor:** a hassette release and its add-on update are one event, with no manual step, and the store
never offers a version whose image doesn't exist yet.

Prior art: in upstream-owned add-ons, the upstream release pipeline pushes the add-on bump after the image
publishes. Music Assistant commits `version` + CHANGELOG with a GitHub App token
(`music-assistant/server` `release.yml`, job `update_addon`); Z2M uses `repository_dispatch` and ESPHome
`workflow_dispatch`. Repos that rebuild upstream themselves use Renovate. None uses release-please for the
add-on. hassette's release workflow (`.github/workflows/release-please.yml`) already chains jobs with `needs:`,
and images publish from `build_and_publish_image.yml`.

| | A: A job in hassette's release workflow, after the add-on image (D3) publishes, commits `version` + a CHANGELOG entry to `hassette-addon` using a GitHub App token | B: Renovate on smithfamily watches `ghcr.io/nodejsmith/hassette-addon` tags and opens a PR in `hassette-addon` | C: Bump by hand |
|---|---|---|---|
| Convention | Music Assistant, Z2M, ESPHome, evcc | hassio-addons (but for rebuilt images) | Frigate, Matter |
| Lag after a release | None in the workflow; Supervisor offers it at its next store reload | Renovate schedule, plus a merge | Whenever you do it |
| Image exists before the store offers it | Guaranteed by `needs:`, and checked by an anonymous manifest pull | Yes | Yes |
| Credentials | A GitHub App installed on `hassette-addon` (preferred over a PAT, as ESPHome and Music Assistant do), its key stored in the `release` environment | Renovate's existing token | None |
| Pre-releases | The job skips non-stable releases in v0.1 (stable channel only) | Needs a Renovate rule | Manual |

**Recommendation:** A. It is the upstream-owned convention, and the bump is committed as soon as the image
publishes, with no manual step.

Behavior to pin:

- The bump job is in `release-verify`'s `needs:` and result checks (`.github/workflows/release-please.yml:369-388`),
  so a failed bump fails the release the same way a failed PyPI or Docker publish does.
- The job refuses a version lower than `hassette-addon`'s current `version`. `workflow_dispatch` accepts any
  `tag_name` (`release-please.yml:6-11`), and a re-run of an old tag must not downgrade add-on users. An equal
  version is a successful no-op, so re-running a release whose bump already landed (after a later step failed)
  passes without committing.
- Before committing, an anonymous `docker manifest inspect` confirms the add-on image exists for amd64 and
  arm64, so a private or missing package fails the release instead of reaching the store. Supervisor pulls
  anonymously (Assumed: image pull).
- The job skips pre-releases: only a stable hassette release bumps the add-on in v0.1.
- The CHANGELOG entry is the hassette version plus a link to that release's GitHub release notes; the notes
  aren't copied.
- The GitHub App key lives in the `release` environment, not as a repo-wide secret.
- The new `hassette-addon` GHCR package is made public before the first release (Build).

**Pick B instead if** you'd rather review each add-on bump as a PR.
**Pick C instead if** you want to hold add-on users back from some releases.
**Reversibility:** easy
**Challenge:** the release gate, replay guard, anonymous pull check and scoped key came from challenge findings; choice unchanged.
**Ratified:** Chose a job in hassette's release workflow that, after the add-on image publishes, commits `version` and a CHANGELOG entry to `hassette-addon` with a GitHub App token, stable releases only, over Renovate PRs or manual bumps, matching the upstream-owned convention with no manual step, accepting a one-time GitHub App setup.

### D13: Does v0.1 pair the HACS integration with the add-on automatically?

**Deciding factor:** HAOS users can connect the integration without typing a hostname and token. The risk that
custom integrations can't receive discovery gets retired before the milestone depends on it.

Supervisor discovery: the add-on lists `discovery: [hassette]` in `config.yaml`, and its glue POSTs
`{"service": "hassette", "config": {"host": …, "port": 8126, "auth_token": …}}` to
`http://supervisor/discovery`. Supervisor forwards it to Core, which starts a config flow for the integration
whose domain matches the service, with `source=hassio`. The integration implements
`async_step_hassio(HassioServiceInfo)` and shows a "Discovered" card. Prior art: Music Assistant sends
`{host, port, auth_token}` this way and its integration trusts the token after validating it (added a year
after its v1). Matter and Z-Wave JS had discovery from v1. Supervisor doesn't restrict service names beyond
the add-on's own `discovery:` list (`~/source/supervisor/supervisor/discovery/`), so a HACS integration should
receive it. No surveyed example proves that. Supervisor checks only that list, so any add-on from any
repository can declare `discovery: [hassette]` (`~/source/supervisor/supervisor/api/discovery.py:91-112`).

Supervisor sets the add-on's hashed hostname as the container's hostname (Assumed: hostname), so the glue
reads it (`hostname`) instead of recomputing a hash of a repo URL it doesn't know.

`hass-hassette` declares `single_config_entry: true`, and one hassette entry per HA is a product rule. Once an
entry exists, Core aborts `hassio`-sourced flows for such an integration before `async_step_hassio` runs
(Assumed: `single_config_entry`), so discovery can create the first entry but can never update it. Supervisor
keeps the latest payload per add-on and re-pushes it only when it changes (Assumed: discovery storage).

| | A: Discovery in v0.1, gated on a spike proving a custom integration receives it and the refresh path works; manual pairing is the fallback if the spike fails | B: Manual in v0.1: DOCS.md gives the hostname and token location; discovery stays in HACS v0.4 |
|---|---|---|
| User setup for the integration | Click "Configure" on the discovered card | Find a hashed hostname and the token file, then type both |
| Work | A background glue announce after hassette serves (needs only the `discovery:` key), plus `async_step_hassio`, a confirm step, the 401 refresh path, tests and a release in `hass-hassette` | Docs |
| Repos touched | hassette, hassette-addon, hass-hassette | hassette, hassette-addon |
| Risk | Custom-integration discovery and the refresh path are unproven. The spike retires both first | None |
| Roadmap | Pulls the v0.4 item forward; the roadmap's HACS chain is updated | Unchanged |

How an existing entry picks up a rotated token or a changed host:

| | R1: Keep `single_config_entry`; on a 401 or a connection failure, re-read the add-on's current discovery info and update the entry | R2: Drop `single_config_entry`; unique id = add-on slug; `_abort_if_unique_id_configured(updates=…)` | R3: Keep `single_config_entry`; no refresh, manual reauth after a token change |
|---|---|---|---|
| Rotated token picked up without the user | Yes, on the next 401 | Yes, at the next announcement | No |
| One hassette entry per HA | Kept | Lost (a Docker instance plus the add-on could both be entries) | Kept |
| HA idiom | A Core helper Matter and Z-Wave JS use for their add-ons, on a custom trigger | Standard (Matter, Z-Wave JS) | n/a |
| Work in `hass-hassette` | A 401 handler and a stored slug | Manifest change, unique id in the user and hassio steps, a slug check before updating | None |
| Repoint by another add-on | Not possible: only the stored slug is read | Needs the slug check | Not possible |

**Recommendation:** A with R1. Without discovery, the integration is effectively out of reach for most HAOS
users. R1 keeps the one-entry rule and still picks up a rotated token with no user input, using the same Core
helper Core's own add-on integrations use. The spike comes first in the build order and covers both receipt
and refresh, so an unworkable path costs an hour, not the milestone. It passes when (1) a HACS integration
receives the discovery flow, and (2) the re-read triggered by a 401 or a connection failure returns the current
payload and updates the entry. If either fails, v0.1 ships manual pairing (B).
**Pick B instead if** you want this milestone to touch only hassette and the add-on repo.
**Pick R2 instead if** more than one hassette entry per HA should be allowed.
**Pick R3 instead if** the spike can't prove the refresh path, accepting manual reauth after every token change.

Behavior to pin if A:

- The announce is a background glue step started before `exec docker_start.sh`. It waits until
  `/api/health/live` answers on port 8126, then reads `/config/.web_api_token` (D8) and the container's
  hostname and POSTs. The "Discovered" card never appears before hassette can answer Configure. A failed
  POST is logged and never stops the add-on.
- `async_step_hassio` accepts only a `slug` ending in `_hassette`, confirms with the user before creating the
  entry, and stores the slug in the entry.
- When the integration gets a 401, or can't connect to the stored URL, and the entry has a stored slug, it
  reads the add-on's current discovery config through Core's
  `AddonManager(hass, logger, name, slug).async_get_addon_discovery_info()`
  (`~/source/core/homeassistant/components/hassio/addon_manager.py:127-141`, exported from
  `hassio/__init__.py:52`; used by `matter/addon.py:14-16` and `zwave_js/config_flow.py:370-374`). If the
  URL or token changed, it updates the entry in place and retries. Only if that fails does it raise reauth.
  It reads only the stored slug, so another add-on can't repoint the entry.
- A second announcement after pairing never creates a second entry.
- A token rotated by deleting the file (D8) is picked up on the next 401 without user input.
- An entry created manually has no stored slug and never takes the refresh path; reconfigure covers it.
- The token in the payload is documented in DOCS.md.

**Reversibility:** easy
**Challenge:** announcing only after hassette serves, reading the hostname from the container, the refresh path that keeps one entry, the slug check, and keeping discovery in v0.1 behind the two-part spike came from challenge findings.
**Ratified:** Chose discovery pairing in v0.1, announced by a background glue step after `/api/health/live` answers with the hostname read from the container, keeping `single_config_entry` (one hassette per HA) and refreshing a stale entry on a 401 or a connection failure by re-reading the stored slug's discovery info via Core's `AddonManager.async_get_addon_discovery_info()`, accepting only slugs ending in `_hassette`, over manual pairing or dropping `single_config_entry`, gated on a two-part spike (receipt and refresh) with manual pairing as the fallback, accepting a third repo in the milestone.

### D14: What does Supervisor's watchdog check?

**Deciding factor:** Supervisor restarts hassette only when hassette itself is dead, never because HA is
down.

The `watchdog:` URL only matters with the Watchdog toggle on. Its probe restarts with no cap but skips any
add-on not in `STARTED`, while an exited or `UNHEALTHY` container takes the throttled path (Assumed: Watchdog).
Prior art (`research.md`): most surveyed
add-ons omit `watchdog:`; Frigate uses an HTTP URL and Mosquitto `tcp://`. Without a URL, the toggle still restarts an add-on whose
container exits, through the throttled container path.

The pre-serve phase runs on every start (D4): port 8126 isn't served until the installs finish and hassette
starts. That can take up to the sum of the uv step timeouts (`scripts/docker_start.sh:24-27`, plus D9's
`python_packages` step) plus startup. The hassette image has no Docker `HEALTHCHECK` (`Dockerfile`), so the
add-on is `STARTED` at once and the application watchdog starts probing a port nobody listens on yet. An image
`HEALTHCHECK` changes that (Assumed: `HEALTHCHECK`).

| | A: `watchdog:` URL on `/api/health/live`, plus a `HEALTHCHECK` on the same route in the add-on variant image, with a `--start-period` longer than the worst-case pre-serve phase | B: `watchdog:` URL only | C: URL, plus a glue stub listener on 8126 until hassette binds | D: No `watchdog:` URL |
|---|---|---|---|---|
| Start slower than two watchdog intervals (cold cache, a Pi), Watchdog on | Held in `STARTUP`, not probed until healthy | Restarted on the second miss, uncapped, so the install may never finish | Stub answers, not restarted | Not probed |
| Hung-but-running hassette | Restarted via the URL, and via `UNHEALTHY` (throttled container path) | Restarted via the URL | Restarted via the URL once hassette owns the port | Never restarted |
| Start that never finishes | `UNHEALTHY` after the start period, then throttled restarts | Uncapped restart loop | Stub stays green and hides it | Shows "running" |
| HA outage | Not restarted (liveness is independent of HA) | Same | Same | Same |
| Moving parts | One `HEALTHCHECK` line in the variant Dockerfile | None beyond the URL | A process to start and hand off | None |
| Docker users' image | Unchanged | Unchanged | Unchanged | Unchanged |
| Convention | URL as Frigate | URL as Frigate | None surveyed | Most surveyed add-ons |

**Recommendation:** A. It uses Supervisor's own startup gate, keeps hung-process detection, and can't hide a
start that never finishes. Liveness answers 200 while the event loop serves, independent of the HA connection,
and is exempt from auth (`WebApiConfig.auth_enabled` docstring, `src/hassette/config/models.py`; route at
`src/hassette/web/routes/health.py:18`). DOCS.md recommends turning Watchdog on from install, since it is
also what restarts hassette after a crash or a `FatalError` exit (D4).

Behavior to pin:

- The `HEALTHCHECK` exists only in the add-on variant image (D3 A).
- The check is `curl -fsS http://127.0.0.1:8126/api/health/live || exit 1` (curl is already in the image,
  `Dockerfile:82`), with `--interval=30s --timeout=5s --retries=3`.
- Its `--start-period` exceeds the sum of the uv step timeouts in `scripts/docker_start.sh` (including the
  `python_packages` step, D9), D4's offline retries and hassette's startup. A test fails if `--start-period` is not greater than the sum of
  those timeout constants, so raising a timeout can't silently outgrow it.
- DOCS.md says the install runs on every start, not only the first.
- The build confirms on HAOS that Supervisor holds the add-on in `STARTUP` until the `HEALTHCHECK` passes
  (Build).

**Pick C instead if** the HAOS check shows Supervisor doesn't honor the image's `HEALTHCHECK` for this add-on.
**Pick D instead if** you'd rather match the majority and give up hung-process detection.
**Pick B instead if** no user's start can exceed two watchdog intervals (no dependencies, warm cache).
**Pick `/api/health/ready` as the URL instead if** you want an HA outage to restart hassette, which fights
hassette's own reconnect logic.
**Reversibility:** easy
**Challenge:** the every-start install, the uncapped application watchdog and the `HEALTHCHECK` start gate came from challenge findings.
**Ratified:** Chose `watchdog: http://[HOST]:[PORT:8126]/api/health/live` plus a Docker `HEALTHCHECK` on the same URL with a `--start-period` covering the worst-case install, in the variant image only, over the URL alone, no URL, a stub listener, or readiness, so Supervisor never restarts a slow start yet still restarts a hung hassette, accepting that the HEALTHCHECK behavior is confirmed on HAOS during the build; DOCS.md recommends Watchdog on from install.

### D15: Which neighboring issues join the milestone?

**Deciding factor:** the roadmap's rule: an issue joins only if the Done-when fails without it.

- **#616 `hassette build`:** out. The add-on can't use it, since Supervisor owns the image.
- **#2330** (docs: project install and app loading are independent import paths) and **#2331**
  (`docker_start.sh` doesn't check that the installed project imports): the add-on runs the same install path
  (D4), and add-on users can't easily debug it. Recommendation: **#2331 in, #2330 out.** A silent
  import failure inside an add-on is much harder to diagnose than under Docker. The docs gap is the same as
  today's. #2331 adds a WARNING after the project install when the installed project package isn't
  importable. It is a warning, not a halt, so it sits outside D4's halt/degrade taxonomy and never stops the
  start.
- **#1253** (high-volume live logs freezing the UI) and other UI bugs: out, as interrupts.

**Pick "both in" instead if** you want the add-on docs to explain project installs as fully as the Docker
docs should. **Pick "both out" instead if** you'd rather keep the milestone to the add-on's own seams.
**Reversibility:** easy
**Ratified:** Chose #2331 in the milestone and #2330, #616 and UI bugs out, applying the roadmap's Done-when rule, because a silent import failure is much harder to diagnose inside an add-on, accepting that the project-install docs gap stays as it is today.

## Assumed

- Supervisor's current map type for an add-on's own config folder is `app_config`. `addon_config` still
  works but logs a deprecation warning, as of 2026.07. Host path `/app_configs/<repo-id>_<slug>`.
  Evidence: `~/source/supervisor/supervisor/apps/validate.py:137,262-266`,
  `supervisor/docker/const.py:207,214`.
- Supervisor clones custom repositories at depth 1 and finds add-ons by globbing `**/config.*` outside
  dot-dirs and `rootfs/`. Evidence: `~/source/supervisor/supervisor/store/git.py:192`,
  `supervisor/store/data.py:150-165`.
- A `build.yaml` and the implicit `BUILD_FROM` are deprecated; local builds use the add-on's
  `Dockerfile` as written. Evidence: `~/source/supervisor/supervisor/apps/build.py:67,111-114`.
- **Supervisor proxy:** Supervisor injects `SUPERVISOR_TOKEN` into every add-on container's environment, and
  proxies HA REST at `/core/api/...` and WebSocket at both `/core/websocket` and `/core/api/websocket`,
  accepting that token only for an add-on with `homeassistant_api: true`. Evidence:
  `~/source/supervisor/supervisor/docker/app.py:236-241`, `docker/const.py:166` (env injection);
  `api/__init__.py:703-713` (routes); `api/proxy.py:122,359` (`access_homeassistant_api` check).
- hassette's logs go to stdout/stderr only, so Supervisor's log viewer needs no work. Evidence:
  `Dockerfile` (`PYTHONUNBUFFERED=1`), no file handlers in `src/hassette/logging_.py`.
- `/api/health/live` and `/api/health/ready` bypass auth. Evidence: `WebApiConfig.auth_enabled` docstring,
  `src/hassette/config/models.py`.
- The ingress gateway's peer address is `172.30.32.2`. Evidence: HA add-on developer docs (ingress section).
- Released images are multi-arch `amd64`/`arm64`, which covers Supervisor's supported `amd64` and
  `aarch64`. Evidence: `.github/workflows/build_and_publish_image.yml:155`.
- **Image pull:** Supervisor pulls an add-on's `image:` (with `{arch}` substituted) at the tag equal to its
  `version:`, for the host's platform. It pulls anonymously unless the user has stored credentials for that
  registry. Evidence: `~/source/supervisor/supervisor/apps/model.py:780-789` (`_image`),
  `docker/interface.py:279-300,351-368` (`install`), `:213-248` (`_get_credentials`).
- `hassette run --check` resolves and prints `CONFIG_DIR`, `CONFIG_HOME`, `APPS_DIR` and exits 78 on
  config errors; `docker_start.sh` consumes it. Evidence: `scripts/docker_start.sh:99-140`, spec 128 D12/D14.
- With `HASSETTE__CONFIG_DIR=/config` (already set by the image), apps default to `/config/apps` with no
  other setting. Evidence: `src/hassette/config/locations.py`, spec 128 D5.
- **Watchdog:** Supervisor restarts an exited or `UNHEALTHY` add-on, and acts on the `watchdog:` URL, only when the user has
  turned on the add-on's Watchdog toggle (default off). The two paths differ:
  - Container exit or `UNHEALTHY`: restarts back off from 10 s, doubling, and are capped at 10 per 30 minutes.
    Evidence: `~/source/supervisor/supervisor/apps/app.py:1768-1777` (throttle on `_restart_after_problem`),
    `:1865-1879` (`watchdog_container`), `apps/const.py:41-44`.
  - Application watchdog (`watchdog:` URL): checked every 120 s, skipped for any add-on not in `STARTED`,
    and restarted on the second consecutive miss with no throttle. Evidence: `~/source/supervisor/supervisor/misc/tasks.py:47`,
    `:330-361`.
- **`HEALTHCHECK`:** An image `HEALTHCHECK` keeps an add-on in `STARTUP` while its container runs but hasn't reported healthy;
  without one, a running container is `STARTED` at once. Evidence: `~/source/supervisor/supervisor/apps/app.py:203-210`.
- **Root-owned mounts:** Supervisor bind-mounts the add-on's data and config folders from the host and doesn't
  chown them, so a non-root process can't write them. Evidence: `~/source/supervisor/supervisor/docker/app.py:460-525`
  (bind mounts, no ownership change); every surveyed add-on runs as root
  (`design/research/2026-10-10-ha-addon-conventions/web-research-runtime.md`).
- **Container removal:** Supervisor removes the add-on's container on every stop, so anything outside the mounted `/data` and
  `/config` (including `/app/.venv`) resets on each start. Evidence: `~/source/supervisor/supervisor/docker/app.py:1013`
  (`stop(remove_container: bool = True)`).
- **Stop timeout:** An add-on's default stop timeout is 10 s after SIGTERM, configurable as `timeout` from 10 to 300. Evidence:
  `~/source/supervisor/supervisor/apps/validate.py:550-552`.
- `backup_pre` runs inside the container before a hot backup and is ignored with `backup: cold`. A non-zero
  exit fails that add-on's backup, and the full backup continues without the add-on. Evidence:
  `~/source/supervisor/supervisor/apps/app.py:1430-1440` (`run_inside`, non-zero raises), `:1459-1465`;
  `apps/validate.py:228-233`; `backups/backup.py:701-705`, `:734-737`.
- **`backup_exclude`:** Patterns are tested with `PurePath.match` against each file's full host path, which
  anchors at the right end: `hassette.db` matches a `hassette.db` in any subdirectory. An excluded directory is
  skipped with its contents. Evidence: `~/source/supervisor/supervisor/apps/app.py:1488-1503`; securetar
  `_atomic_contents_add` (2026.4.1).
- **Restore:** Restoring an add-on backup deletes the add-on's existing `/data` and `app_config` folders before
  copying the backup's copies in, so no file from before the restore survives in either. Evidence:
  `~/source/supervisor/supervisor/apps/app.py:1715-1731` (`_restore_data`: `remove_data(self.path_data)`,
  `remove_data(self.path_config)`, then `copytree`).
- **Discovery storage:** Supervisor stores one discovery message per add-on and service. An identical payload is not re-pushed to
  Core; a changed payload replaces the stored config and is pushed again. Core re-lists stored messages when
  it starts. Evidence: `~/source/supervisor/supervisor/discovery/__init__.py:79-102`,
  `~/source/core/homeassistant/components/hassio/discovery.py:35-51`.
- **`single_config_entry`:** For an integration with `single_config_entry`, Core aborts any flow other than ignore, reauth or reconfigure
  with `single_instance_allowed` once an entry exists, before the integration's step runs. Evidence:
  `~/source/core/homeassistant/config_entries.py:1612-1631`.
- An add-on's `SUPERVISOR_TOKEN` can call `/addons/self/info` and `/discovery` without `hassio_api`. Evidence:
  `~/source/supervisor/supervisor/api/middleware/security.py:98-108`.
- **Exit 143:** Supervisor warns when an add-on exits 143 on SIGTERM. Evidence: `~/source/supervisor/supervisor/apps/app.py`
  `container_state_changed`.
- An add-on can only announce discovery services listed in its own `discovery:` key. Core starts a config flow for
  the integration whose domain equals the service name, with `source=hassio`, and the integration receives a
  `HassioServiceInfo` (`config`, `name`, `slug`, `uuid`). Evidence: `~/source/supervisor/supervisor/discovery/`,
  `design/research/2026-10-10-ha-addon-conventions/web-research-config.md`. That a custom (HACS) integration
  receives it is inferred, not demonstrated; D13's spike verifies it.
- **Hostname:** An add-on's hostname on the internal network is `<first 8 hex of sha1(lowercased repo URL)>-<slug>`, with `_`
  replaced by `-`, and Supervisor sets it as the container's hostname. Evidence:
  `~/source/supervisor/supervisor/apps/model.py:182-184`, `store/utils.py:12-15`, `docker/app.py:700-708`.
- Ingress requests arrive from `172.30.32.2` with the prefix stripped. `X-Ingress-Path` is
  `/api/hassio_ingress/<token>`, set by HA Core's hassio ingress view and passed through by Supervisor.
  Supervisor sets `X-Remote-User-*` and strips client-supplied copies. Evidence:
  `~/source/core/homeassistant/components/hassio/ingress.py:275`,
  `~/source/supervisor/supervisor/api/ingress.py:333-363`.
- Supervisor's ingress proxies WebSockets. Evidence: `~/source/supervisor/supervisor/api/ingress.py`
  (websocket handler).
- `hass-hassette`'s config flow takes URL + optional token, and implements no `async_step_hassio` today. Its
  manifest declares `single_config_entry: true`. Evidence: `~/source/hass-hassette/custom_components/hassette/config_flow.py:33-38`,
  `manifest.json`.
- hassette's own HA-not-ready handling (bootstrap gate, `StateProxy` initial capability) covers starting while
  Core is still loading, so the add-on does not poll Core's state first as AppDaemon's add-on does. Evidence:
  `.claude/rules/core-startup.md`.

## Build

- [ ] Run the D13 spike against its pass criteria; on failure, v0.1 ships manual pairing
- [ ] D1 prefix e2e gate: the frontend passes an e2e test served under a URL prefix, and a grep finds no remaining absolute paths, before the `hassette-addon` repo is created
- [ ] Verify `uv --offline` installs from a warm `/data/uv_cache` with the network blocked, with per-start pruning off as the add-on runs it (D4)
- [ ] Verify on real HAOS that Supervisor holds the add-on in `STARTUP` until the image `HEALTHCHECK` passes (D14)
- [ ] Verify on real HAOS that a client of the mapped direct port is never presented as `172.30.32.2`; record the result in the Addendum (D7)
- [ ] Verify the add-on container stops with exit 0 on `ha apps stop`, both while hassette serves and during the pre-serve install (D4)
- [ ] Verify on real HAOS that the UI's WebSocket (`frontend/src/hooks/use-websocket.ts`) connects through ingress (D1)
- [ ] Make the `hassette-addon` GHCR package public before the first release (D12)
- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**

## Addendum

**2026-10-10 — D12 credentials.** The bump job uses the existing `nodejsmith-release-please` GitHub App
instead of a new one. That app is installed on all of the account's repositories with `contents: write`,
and hassette already holds its credentials as repo secrets (`RELEASE_PLEASE_APP_ID`,
`RELEASE_PLEASE_APP_PRIVATE_KEY`). Any workflow in hassette can already mint a token for `hassette-addon`,
so putting a second app's key in the `release` environment would add no isolation. Tighter scoping means
narrowing that installation to selected repositories, which is web-UI-only and out of scope here. The job
requests a token limited to `hassette-addon` (`repositories:` on `actions/create-github-app-token`), and the
`hassette-addon` ruleset lists the app as an `always` bypass actor so the job can commit to `main`
directly.
