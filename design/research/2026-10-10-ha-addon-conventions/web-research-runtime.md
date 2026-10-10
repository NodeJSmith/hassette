# Web research: HA add-on ("app") runtime, ingress, auth

Date: 2026-10-10. Primary sources fetched raw from GitHub (main/master/dev branches as of today). Note: the hassio-addons repos were renamed `addon-*` -> `app-*` and "add-on" -> "app" in docs; raw URLs below use the old `addon-*` names, which still resolve. Not verified: anything marked [no source found].

## Sources Found

### HA developer docs: apps/presentation.md (Ingress)
- **URL**: https://github.com/home-assistant/developers.home-assistant/blob/master/docs/apps/presentation.md
- **Type**: official docs
- **Key takeaway**: Ingress needs `ingress: true`; server on 8099 or `ingress_port`; "Only connections from `172.30.32.2` must be allowed"; "Users are previously authenticated via Home Assistant. Authentication is not required." Supervisor adds request header `X-Ingress-Path` "which may be filtered to obtain the base URL". Gateway supports HTTP/1.x, streaming, websockets. Ingress gives +2 security rating (overrides `auth_api`).
- **Relevance**: Defines the contract hassette's `trusted_proxies` = [172.30.32.2] maps onto.

### HA developer docs: apps/configuration.md
- **URL**: https://github.com/home-assistant/developers.home-assistant/blob/master/docs/apps/configuration.md
- **Type**: official docs
- **Key takeaway**: `startup` (`initialize|system|services|application|once`, default `application`; `services` starts before Core, `application` after). `ingress_port` default 8099, "`0` for host-network apps, read the port later via the API". `ingress_entry` default `/`. `ingress_stream` default false. `panel_admin` default true. `watchdog`: URL "like `http://[HOST]:[PORT:2839]/dashboard`" or `tcp://[HOST]:[PORT:80]`. `webui`: URL template with `[HOST]`/`[PORT:n]`.
- **Relevance**: Reference for every key asked about.

### Supervisor ingress proxy source
- **URL**: https://raw.githubusercontent.com/home-assistant/supervisor/main/supervisor/api/ingress.py (and `supervisor/const.py`)
- **Type**: source
- **Key takeaway**: `_init_header` sets `X-Remote-User-Id`, `X-Remote-User-Name`, `X-Remote-User-Display-Name` from the HA session user, and strips any client-supplied copies of those plus `X-Supervisor-Token`/`X-Hassio-Key` (anti-spoofing). `INGRESS_DYNAMIC_PORT_MIN/MAX = 62000/65500` (for `ingress_port: 0`). I found no `X-Ingress-Path` string in ingress.py; the docs say it is added [exact code location: no source found].
- **Relevance**: Headers are trustworthy only if the peer is 172.30.32.2; the user-mapping headers exist for apps that want per-user identity.

### Grafana add-on (hassio-addons/addon-grafana)
- **URL**: https://raw.githubusercontent.com/hassio-addons/addon-grafana/main/grafana/config.yaml ; `.../rootfs/etc/nginx/servers/ingress.conf` ; `.../rootfs/etc/grafana/grafana.ini` ; `.../rootfs/etc/s6-overlay/s6-rc.d/grafana/finish` ; `.../init-grafana/run` ; `.../init-nginx/run` ; `.../Dockerfile`
- **Type**: add-on source
- **Key takeaway**: `ingress_port: 1337`, `init: false`, `startup: services`, `ports: 80/tcp: null` (direct port off by default, description "Not required for Ingress"). nginx ingress server: `allow 127.0.0.1; allow 172.30.32.2; deny all; proxy_set_header X-WEBAUTH-USER %%grafana_user%%` (default value `admin`, option `grafana_ingress_user`; NOT the HA user). `grafana.ini`: `[auth.proxy] enabled=true header_name=X-WEBAUTH-USER auto_sign_up=true whitelist=127.0.0.1`, plus `root_url = ...%%ingress_entry%%` (sed-substituted from `bashio::app.ingress_entry` at init). `proxy_params.conf` blanks `X-WEBAUTH-USER` for all proxied traffic so the direct port cannot spoof it. `finish` script halts the container when Grafana exits non-zero. Dockerfile `HEALTHCHECK curl http://127.0.0.1:1337/api/health`.
- **Relevance**: Best example of "auth proxy header trusted only from the ingress server block, blanked elsewhere" and "app told its base path via config substitution of the ingress entry".

### Z-Wave JS UI add-on
- **URL**: https://raw.githubusercontent.com/hassio-addons/addon-zwave-js-ui/main/zwave-js-ui/config.yaml ; `.../rootfs/etc/nginx/templates/ingress.gtpl` ; `.../s6-rc.d/zwave-js-ui/run`, `/finish` ; upstream docs https://raw.githubusercontent.com/zwave-js/zwave-js-ui/master/docs/usage/reverse-proxy.md
- **Type**: add-on source + upstream docs
- **Key takeaway**: `ingress_port` default (8099), `ingress_stream: true`, `init: false`, `startup: system`, `ports: 3000/tcp: null`. nginx template: `listen 8099; proxy_set_header X-External-Path {{ .entry }}; allow 127.0.0.1; allow 172.30.32.2; deny all`. Upstream app reads `X-External-Path` (or `base` in config) at runtime, "so the frontend doesn't need rebuilding". Upstream docs show `proxy_set_header X-External-Path $http_x_ingress_path;`. No sub_filter. Run script is plain `exec node server/bin/www`; `finish` halts container on non-zero exit.
- **Relevance**: Closest match to hassette's situation (app that supports a runtime base path via header; proxy is a thin forwarder).

### Node-RED add-on
- **URL**: https://raw.githubusercontent.com/hassio-addons/addon-node-red/main/node-red/config.yaml ; `.../rootfs/etc/node-red/config.js` ; `.../nginx/templates/ingress.gtpl` ; `.../s6-rc.d/nodered/run`, `/finish`
- **Type**: add-on source
- **Key takeaway**: `ingress_port: 0` (host network; nginx listens on `{{ .interface }}:{{ .port }}`), `ingress_stream: true`, `init: false`, `ports: 80/tcp: 1880` (direct port ENABLED by default, with optional ssl and `http_node`/`http_static` basic auth). `config.js`: `config.adminAuth = null; // Disable authentication, let HA handle that`, `uiHost = "127.0.0.1"`, `httpNodeRoot = "/endpoint"`. Ingress block: `allow 172.30.32.2; deny all`. Node-RED's own editor uses relative URLs, so no rewrite is done by the add-on [claim about editor internals: no source found].
- **Relevance**: Example of disabling the app's own auth entirely and putting the only exposed listener behind the IP allowlist; the app itself binds loopback only.

### InfluxDB v1, Studio Code Server add-ons
- **URL**: https://raw.githubusercontent.com/hassio-addons/addon-influxdb/main/influxdb/config.yaml ; https://raw.githubusercontent.com/hassio-addons/addon-vscode/main/vscode/config.yaml ; `.../vscode/rootfs/etc/s6-overlay/s6-rc.d/code-server/run` ; `.../init-user/run`
- **Type**: add-on source
- **Key takeaway**: InfluxDB: `ingress_port: 1337`, `startup: services`, Chronograf `80/tcp: null` ("Not required for Ingress") but 8086 API port enabled. VS Code: `ingress_port: 1337`, `init: false`; run script passes `--auth none` ("we use HA authentication"); init script references `/root/.zsh_history`, i.e. runs as root. All three put nginx on 1337 in front.
- **Relevance**: 1337 is the community-add-on convention (not 8099); root user confirmed by VS Code.

### Frigate (blakeblackshear/frigate + frigate-hass-addons)
- **URL**: https://raw.githubusercontent.com/blakeblackshear/frigate-hass-addons/main/frigate/config.yaml ; https://raw.githubusercontent.com/blakeblackshear/frigate/dev/docker/main/rootfs/usr/local/nginx/conf/nginx.conf ; `.../auth_request.conf` ; `.../s6-rc.d/frigate/finish` ; https://raw.githubusercontent.com/blakeblackshear/frigate/dev/frigate/api/auth.py ; https://raw.githubusercontent.com/blakeblackshear/frigate/dev/docs/docs/configuration/authentication.md
- **Type**: add-on + upstream source
- **Key takeaway**: Add-on config: `init: false`, `startup: application`, `watchdog: "http://[HOST]:[PORT:5000]/"`, `webui` same URL, `ingress: true`, `ingress_port: 5000`, `ingress_entry: /`, `panel_admin: false`, and ports `5000/tcp: null`, `8971/tcp: null` (described "Authenticated Web interface"), 8555 enabled. Two-port model: 8971 = authenticated UI/API ("Reverse proxies should use this port"); 5000 = "Internal unauthenticated UI and API access. Access to this port should be limited". `auth.py`: "Internal port always has admin role set by the /auth endpoint" (`remote-user: anonymous, remote-role: admin`). Ingress points at 5000, so ingress users are anonymous admins; `panel_admin: false` lets non-admin HA users open it anyway. Base path: frontend is built with literal `/BASE_PATH/` placeholder and nginx `sub_filter` rewrites it per-request from `$http_x_ingress_path` (href, url(), /dist/, /js/, /assets/, /locales/, manifest `start_url`/`src`, and injects `<script>window.baseUrl="$http_x_ingress_path/"</script>` after `<body>`). Frigate's own `finish` script halts the s6 tree on any service exit.
- **Relevance**: The exact two-port pattern and the "build with placeholder prefix, rewrite at serve time" pattern.

### Music Assistant (add-on + server)
- **URL**: https://raw.githubusercontent.com/music-assistant/home-assistant-addon/main/music_assistant/config.yaml ; https://raw.githubusercontent.com/music-assistant/server/dev/music_assistant/controllers/webserver/helpers/auth_middleware.py ; `.../controllers/webserver/controller.py` ; `.../music_assistant/constants.py`
- **Type**: add-on + upstream source
- **Key takeaway**: `ingress_port: 8094`, `init: false`, `panel_admin: false`, `host_network: true`, `auth_api: true`. The server runs a SEPARATE ingress webserver bound to the `172.30.32.x` interface on `INGRESS_SERVER_PORT = 8094` (`controller.py` L370-376, picks the first IP starting `172.30.32.`), distinct from the main authenticated webserver. `auth_middleware.py`: `is_request_from_ingress_proxy(request)` -> `resolve_ingress_user` reads `X-Remote-User-ID/-Name/-Display-Name`, requires all present ("for security"), looks up the HA user via the HA API, creates a local user on first sign-in, honours HA admin role; the reserved `homeassistant` system user is rejected on the non-ingress webserver.
- **Relevance**: Strongest "map HA user via X-Remote-User-*" example; physical separation of ingress and public listeners.

### Zigbee2MQTT add-on
- **URL**: https://raw.githubusercontent.com/zigbee2mqtt/hassio-zigbee2mqtt/master/zigbee2mqtt/config.json ; `.../common/rootfs/docker-entrypoint.sh` ; `.../zigbee2mqtt-proxy/nginx.conf.gtpl` ; https://raw.githubusercontent.com/Koenkk/zigbee2mqtt/dev/lib/extension/frontend.ts
- **Type**: add-on + upstream source
- **Key takeaway**: `ingress: true`, no `ingress_port` (so 8099 default), `init: false`, `startup: application`, `ports: 8099/tcp: null`, no `watchdog:` key. Entrypoint is a bashio script that `exec node index.js` after forcing `ZIGBEE2MQTT_CONFIG_FRONTEND_PORT=8099`; it calls `bashio::config.require 'data_path'` (config-error fail-fast) and links the Supervisor race issue #3884. Upstream `frontend.ts` has `base_url` (default "/") and checks `frontend.auth_token` only on the websocket upgrade (`?token=`). The companion "Zigbee2MQTT Proxy" add-on's nginx gtpl does `allow 172.30.32.2; deny all` and appends `&token=<auth_token>` to proxied requests, so auth_token stays enabled and ingress injects it. Z2M's `Z2M_WATCHDOG` env is an app-level MQTT-restart watchdog, not the Supervisor `watchdog:` key. How the SPA resolves asset paths under the ingress prefix (relative `./` base): [no source found] (windfront/frontend vite config URLs 404'd).
- **Relevance**: "Keep app auth, have the proxy inject the credential" variant.

### ESPHome Device Builder add-on + CVE-2026-59177
- **URL**: https://raw.githubusercontent.com/esphome/home-assistant-addon/main/esphome/config.yaml ; https://raw.githubusercontent.com/esphome/esphome/dev/docker/ha-addon-rootfs/etc/s6-overlay/s6-rc.d/esphome/run ; https://corgea.com/advisories/vulnerabilities/CVE-2026-59177
- **Type**: add-on source + security advisory
- **Key takeaway**: `ingress: true`, `ingress_port: 0`, `host_network: true`, `init: false`, `startup: services`, `ports: 6052/tcp: null`. Run script: `exec esphome-device-builder /config/esphome --ha-addon --ingress-port "$(bashio::addon.ingress_port)"`; the direct port requires BOTH a mapped 6052 and `leave_front_door_open` (`DISABLE_HA_AUTHENTICATION=true`), with comment that either alone stays ingress-only. CVE-2026-59177 (CVSS 8.8, fixed in device-builder 1.0.10): the ingress site skipped auth assuming Supervisor had authenticated, but bound `0.0.0.0` on a host-network add-on, exposing it to the LAN. Fix: bind loopback + 172.30.32.1 only, plus an `ingress_peer_guard` returning 403 to any TCP peer other than loopback or 172.30.32.2.
- **Relevance**: Directly applicable warning: "skip auth for 172.30.32.2" is only safe with a peer check enforced in the app itself and a narrow bind. hassette's `trusted_proxies` peer-IP check is the right shape.

### AppDaemon add-on (wait for Core)
- **URL**: https://raw.githubusercontent.com/hassio-addons/addon-appdaemon/main/appdaemon/rootfs/etc/s6-overlay/s6-rc.d/appdaemon/run ; `.../appdaemon/config.yaml`
- **Type**: add-on source
- **Key takeaway**: Run script polls `GET http://supervisor/core/api/config` with `Authorization: Bearer ${SUPERVISOR_TOKEN}` every 5 s, up to 300 s, until `.state == "running"`; if never running it logs a warning and starts anyway. Rationale in comment: a `subscribe_events` sent while Core loads integrations "times out after 10s and is not retried", leaving AppDaemon running silently without events. Config: `init: false`, no `startup` (default `application`), no ingress, `webui: http://[HOST]:[PORT:5050]`, `ports: 5050/tcp: 5050` (direct port ENABLED), no `watchdog`.
- **Relevance**: The only surveyed add-on that gates on Core state; precedent for hassette's connect-after-ready logic.

### Official core add-ons (home-assistant/addons)
- **URL**: https://raw.githubusercontent.com/home-assistant/addons/master/{mosquitto,matter_server,configurator,ssh,whisper,duckdns,samba}/config.yaml
- **Type**: add-on source
- **Key takeaway**: Only Mosquitto sets `watchdog` (`tcp://[HOST]:1883`); all seven have `init: false`. Matter Server: `ingress_port: 5580`, `ports: 5580/tcp: null`, `startup: services`. File editor and SSH use ingress at default 8099; SSH `22/tcp: null`.
- **Relevance**: `watchdog:` is rare even in first-party add-ons; `tcp://` is the form used there.

### Community: Supervisor issue on startup race
- **URL**: https://github.com/home-assistant/supervisor/issues/3884 (referenced in Z2M entrypoint comment; not fetched)
- **Type**: issue (referenced only)
- **Key takeaway**: [not fetched; cited via Z2M entrypoint comment]
- **Relevance**: Background only.

## Survey Table

Supervision column: "s6" = s6-rc service with a `finish` that halts the container on non-zero exit (copy-pasted ~identically across hassio-addons); "entrypoint" = upstream/own script `exec`s the app, no s6 services. All surveyed use `init: false` (Supervisor's tini not used; base image provides s6 or the add-on has its own entrypoint). User: root unless noted.

| Add-on | Supervision | `watchdog:` | User | Ingress (port, base-path method) | Direct port default | Own-auth-under-ingress |
|---|---|---|---|---|---|---|
| Grafana | s6, finish halts on fail | none (Docker HEALTHCHECK on :1337/api/health) | root (s6 base) | 1337; `root_url` with `%%ingress_entry%%` sed-substituted into grafana.ini | off (`80/tcp: null`) | `auth.proxy` via `X-WEBAUTH-USER` set only in ingress block (fixed `admin`, not HA user); header blanked elsewhere |
| Z-Wave JS UI | s6, finish halts | none | root | 8099 (default); app reads `X-External-Path` (= X-Ingress-Path) at runtime | off (`3000/tcp: null`, WS port only) | App has auth off in add-on [from nginx allowlist only; app setting: no source found]; nginx `allow 172.30.32.2` |
| Node-RED | s6, finish halts | none | root | 0 (host net); nginx front; editor needs no rewrite (relative) | ON (`80/tcp: 1880`) | `adminAuth = null`; ingress allowlist 172.30.32.2; app binds 127.0.0.1 |
| InfluxDB v1 | s6 | none | root | 1337; nginx | Chronograf off, API 8086 on | `auth_api`/own InfluxDB auth for API; ingress allowlist |
| Studio Code Server | s6 | none | root (`/root/.zsh_history`) | 1337; code-server is path-relative | none | `--auth none` |
| Frigate | s6, finish halts | `http://[HOST]:[PORT:5000]/` | root | 5000; build with `/BASE_PATH/`, nginx `sub_filter` from `$http_x_ingress_path` | off (5000, 8971 null; 8555 on) | Ingress hits unauth port 5000 (anonymous admin); authed 8971 for external |
| Music Assistant | upstream container (`ENTRYPOINT entrypoint.sh`, `exec mass`) | none | root | 8094 separate ingress webserver bound to 172.30.32.x | n/a (host_network) | Maps `X-Remote-User-*` to local MA user, requires all headers |
| Zigbee2MQTT | entrypoint (bashio, `exec node`) | none (Z2M internal `watchdog` option) | root | 8099 default; relative base [no source found] | off (`8099/tcp: null`) | Keeps `auth_token`; Proxy add-on injects `&token=` and allows only 172.30.32.2 |
| ESPHome Device Builder | s6, finish halts | none | root | 0 (host net), `--ingress-port` passed by run script; bind 127.0.0.1 + 172.30.32.1 (post-CVE) | off (`6052/tcp: null`); needs port mapped AND `leave_front_door_open` to go unauth | Skips auth for ingress peers; `ingress_peer_guard` 403 otherwise |
| AppDaemon | s6 | none | root | no ingress | ON (`5050/tcp: 5050`, `webui:`) | n/a (own dashboard) |
| Mosquitto (core) | s6 | `tcp://[HOST]:1883` | root | no ingress | on | n/a |
| Matter Server (core) | s6 | none | root | 5580; app-native | off (`5580/tcp: null`) | none |
| File editor / SSH (core) | s6 | none | root | 8099 | SSH 22 off | n/a |

## Patterns Found

### Pattern 1: Container-halting s6 `finish` + Supervisor restart
**Used by**: Grafana, Z-Wave JS UI, Node-RED, ESPHome, Frigate (essentially all hassio-addons-derived).
**How it works**: each longrun service's `finish` (receives exit code, signal) writes the code to `/run/s6-linux-init-container-results/exitcode` and `exec /run/s6/basedir/bin/halt`, so the container exits and Supervisor sees a stopped add-on. Code 256 = killed by signal (writes 128+signal; halts only on SIGTERM in the hassio-addons variant). Config errors are `bashio::exit.nok` in init oneshots (e.g. Grafana plugin install, Z2M `config.require`), which also fail the container. Whether Supervisor then restarts depends on `watchdog:` (restart on failed health/stopped) and `boot:`; none of the surveyed repos implement their own backoff or idle-then-exit.
**Strengths**: one tiny script, no restart loop inside the container; failure surfaces in HA UI.
**Weaknesses**: no distinction between config error and crash (no exit-78 convention found); without `watchdog:` Supervisor does not restart a halted add-on [Supervisor's exact restart-on-exit behavior: no source found in this pass].
**Example**: https://raw.githubusercontent.com/hassio-addons/addon-grafana/main/grafana/rootfs/etc/s6-overlay/s6-rc.d/grafana/finish

### Pattern 2: `init: false` everywhere; own PID 1
**Used by**: 14/14 configs fetched (all of the above plus 7 core add-ons).
**How it works**: base image's s6-overlay is PID 1 (or add-on provides entrypoint); Supervisor's injected tini is disabled. Z2M and Music Assistant use a bare entrypoint that `exec`s the app instead of s6. [No fetched example uses `init: true`; the only one is Z2M Proxy's `config.json`, which has `"init": true`.]
**Strengths**: signal handling and zombie reaping come from s6.
**Weaknesses**: s6 not appropriate for single-process images like hassette's; plain `exec` from a script under tini is the equivalent.
**Example**: https://raw.githubusercontent.com/zigbee2mqtt/hassio-zigbee2mqtt/master/common/rootfs/docker-entrypoint.sh

### Pattern 3: `watchdog:` is optional and mostly omitted
**Used by**: Frigate (HTTP `http://[HOST]:[PORT:5000]/`), Mosquitto (`tcp://[HOST]:1883`). 2 of 14 configs set it. Docker `HEALTHCHECK` (Grafana, File editor) is the more common liveness signal in Dockerfiles.
**How it works**: Supervisor polls the URL (HTTP expects a good response; `tcp://` just connects) and restarts the add-on on failure.
**Strengths**: gets auto-restart for hangs.
**Weaknesses**: rarely adopted; HTTP watchdog on an auth-gated URL needs an unauthenticated health route (Frigate points at its unauth port).
**Example**: https://raw.githubusercontent.com/blakeblackshear/frigate-hass-addons/main/frigate/config.yaml

### Pattern 4: Everything runs as root
**Used by**: all surveyed (VS Code explicit `/root/...`; no `USER` directive in Music Assistant Dockerfile; s6 base images are root).
**How it works**: root inside the container can write Supervisor's root-owned `/data` and mapped `/config`, `/share`, etc. without chown gymnastics. No surveyed add-on drops to non-root. Frigate has an `init-usermod` s6 script (user remap for the upstream image) [content not fetched].
**Strengths**: no permission problems on mounts.
**Weaknesses**: weaker defense in depth; compensated via AppArmor, ingress allowlists.
**Example**: https://raw.githubusercontent.com/hassio-addons/addon-vscode/main/vscode/rootfs/etc/s6-overlay/s6-rc.d/init-user/run
(No source found for any add-on that runs the main process non-root and handles `/data` ownership.)

### Pattern 5: App with runtime base-path support, proxy forwards `X-Ingress-Path`
**Used by**: Z-Wave JS UI (`X-External-Path`), Grafana (`root_url` substituted at init from `ingress_entry`), Z2M (`base_url`), Frigate (partially, via header in sub_filter), docs-recommended header.
**How it works**: either a header per request (`X-Ingress-Path` -> app) or a startup substitution of the ingress entry URL (`bashio::app.ingress_entry`) into config. App generates all links/asset URLs from the base.
**Strengths**: no content rewriting; works with websockets and JS-built URLs; the most robust option.
**Weaknesses**: needs upstream framework support (hassette's SPA currently assumes `/`).
**Example**: https://raw.githubusercontent.com/hassio-addons/addon-zwave-js-ui/main/zwave-js-ui/rootfs/etc/nginx/templates/ingress.gtpl

### Pattern 6: Build with a placeholder prefix and `sub_filter` at serve time
**Used by**: Frigate.
**How it works**: SPA built with `/BASE_PATH/` baked into HTML/JS/CSS/manifest; nginx replaces it with `$http_x_ingress_path` using ~10 `sub_filter` rules (`Accept-Encoding ""` so responses are uncompressed) and injects `window.baseUrl`. Code also patched: `return\`/BASE_PATH/\`` -> `return window.baseUrl`.
**Strengths**: works for a bundle that cannot be re-parameterized; also usable for the non-ingress case (rewrite to `""`).
**Weaknesses**: brittle string matching (must enumerate every pattern; JS template literals need special cases), decompress cost, harder CSP; Frigate had to carry `window.baseUrl` fix-ups.
**Example**: https://raw.githubusercontent.com/blakeblackshear/frigate/dev/docker/main/rootfs/usr/local/nginx/conf/nginx.conf (lines ~355-376)

### Pattern 7: Auth disabled for app, IP allowlist at the ingress listener
**Used by**: Node-RED (`adminAuth=null`), VS Code (`--auth none`), Z-Wave JS UI, Grafana/InfluxDB/Z2M Proxy (`allow 172.30.32.2; deny all`), ESPHome (post-CVE guard).
**How it works**: nginx (or the app) accepts only `172.30.32.2` (and sometimes 127.0.0.1) on the ingress listener; app binds loopback or nginx-only. This mirrors the hassette `trusted_proxies` mechanism but where hassette keeps its auth for other peers.
**Strengths**: simple, matches docs.
**Weaknesses**: only safe if the listener is not reachable from other peers: ESPHome's CVE-2026-59177 (bound 0.0.0.0 on host network) shows the failure; always enforce the peer check in the app and bind narrowly.
**Example**: https://corgea.com/advisories/vulnerabilities/CVE-2026-59177

### Pattern 8: Two listeners: authenticated external, unauthenticated ingress
**Used by**: Frigate (8971 authed TLS / 5000 unauth for ingress), Music Assistant (main webserver vs 8094 ingress webserver on 172.30.32.x), ESPHome (6052 public gated behind two opt-ins vs ingress site).
**How it works**: the ingress listener is separate code path/port that trusts Supervisor; direct port is default-null in config.yaml, and users opt in. Frigate publishes 5000 as `null` ("not required for Home Assistant Ingress") and 8971 as `null` (user may map).
**Strengths**: clear trust boundary; no "if peer is X skip auth" branching in one handler.
**Weaknesses**: two ports to document/test.
**Example**: https://raw.githubusercontent.com/music-assistant/server/dev/music_assistant/controllers/webserver/helpers/auth_middleware.py

### Pattern 9: Map HA user from `X-Remote-User-*`
**Used by**: Music Assistant (full mapping, auto-create user, HA admin role); Grafana does NOT (fixed `admin`).
**How it works**: Supervisor sets `X-Remote-User-Id/Name/Display-Name` and strips client copies; app requires them present and only honors them from the ingress peer.
**Strengths**: per-user identity under ingress.
**Weaknesses**: requires the peer guard; most add-ons skip it and use a single shared identity.
**Example**: https://raw.githubusercontent.com/home-assistant/supervisor/main/supervisor/api/ingress.py (`_init_header`)

### Pattern 10: Poll Core readiness before connecting
**Used by**: AppDaemon (curl loop on `/core/api/config`, 300 s cap, then start anyway). Z2M has a comment about a Supervisor start-order race but no wait loop. Others rely on `startup:`.
**How it works**: see AppDaemon entry. `startup: services` (starts before Core): Grafana, InfluxDB, VS Code, ESPHome, Z-Wave? (`system`), Matter. `startup: application` (after Core, default): Frigate, Z2M, AppDaemon (default).
**Strengths**: avoids a subscribe-before-ready failure.
**Weaknesses**: `startup: application` only orders after Core starts, not after it finishes loading integrations (AppDaemon's comment).
**Example**: https://raw.githubusercontent.com/hassio-addons/addon-appdaemon/main/appdaemon/rootfs/etc/s6-overlay/s6-rc.d/appdaemon/run

## Anti-Patterns

- **Binding the ingress listener to 0.0.0.0 on a host-network add-on while skipping auth** (ESPHome CVE-2026-59177). Bind loopback + 172.30.32.1 and reject non-172.30.32.2 peers.
- **Trusting a header-based identity (`X-WEBAUTH-USER`, `X-Remote-User-*`) on any listener also reachable directly.** Grafana blanks `X-WEBAUTH-USER` in shared proxy params for this reason.
- **Relying on `ingress` for security while publishing an unauthenticated direct port by default** (Node-RED `1880` enabled but protected by `http_node` basic auth config only; AppDaemon 5050 on).

## Emerging Trends

- `ingress_port: 0` plus run script reading `bashio::addon.ingress_port` (ESPHome) for host-network apps.
- Rename "add-on" -> "app" (hassio-addons repos `app-*`, `bashio::app.ingress_entry`); dev docs now under `docs/apps/`.
- Fixed-image maintainers (Z2M, MA, Frigate) keep runtime base-path support in the app itself rather than in the add-on wrapper.
