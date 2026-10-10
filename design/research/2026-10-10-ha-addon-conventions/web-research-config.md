# Web research: HA add-on ("app") configuration, companion-integration connection, documentation

Date: 2026-10-10. Primary sources: HA developer docs, add-on repos (raw GitHub), plus local clones at ~/source/supervisor (HEAD 2026-10-10) and ~/source/core (HEAD 2026-10-07). Some add-on files were summarized by the fetch tool rather than quoted raw; those are flagged "(summarized)". Where nothing was found: [no source found].

## Sources Found

### HA developer docs: apps/configuration.md
- **URL**: https://raw.githubusercontent.com/home-assistant/developers.home-assistant/master/docs/apps/configuration.md
- **Type**: official docs
- **Key takeaway**: map values are `homeassistant_config, app_config, all_app_configs, local_apps, ssl, backup, share, media, data` (ro by default, `:rw` or `read_only: false`); `data` always mapped rw. `backup: hot|cold` (cold stops the app first); `backup_exclude` is a glob list; `stage` stable|experimental|deprecated; `discovery` = "list of services this app provides for Home Assistant". Optional option = trailing `?` in schema and no default; any default makes it required. Translations: `translations/{lang}.yaml` with only two keys `configuration` and `network`.
- **Relevance**: authoritative field list for config.yaml. The doc does not mention the `addon_config` rename at all.

### HA developer docs: apps/communication.md
- **URL**: https://raw.githubusercontent.com/home-assistant/developers.home-assistant/master/docs/apps/communication.md
- **Type**: official docs
- **Key takeaway**: Hostname is `{REPO}_{SLUG}` with `_` replaced by `-` (example `local_xy` -> `local-xy`); for GitHub repos REPO is a hash of the repo URL. `/discovery*` is callable without `hassio_api: true`. Doc does not describe the discovery payload.
- **Relevance**: addressing for the HACS integration (`http://<hash>-hassette:<port>`).

### HA developer docs: apps/presentation.md
- **URL**: https://raw.githubusercontent.com/home-assistant/developers.home-assistant/master/docs/apps/presentation.md
- **Type**: official docs
- **Key takeaway**: README.md = store intro/short description; DOCS.md = usage, config options, support channels, license; CHANGELOG.md curated per-version, Keep a Changelog format; icon.png square, 128x128 recommended; logo.png ~250x100. Suggests stable/beta as separately named repos using `#branch` URL suffix (example `apps-example#next`), e.g. "Super app (stable)" / "Super app (beta)".
- **Relevance**: doc layout checklist. Translations, `stage`, badges not covered there.

### HA developer docs: apps/repository.md
- **URL**: https://raw.githubusercontent.com/home-assistant/developers.home-assistant/master/docs/apps/repository.md
- **Type**: official docs
- **Key takeaway**: root `repository.yaml` (name required; url, maintainer optional); one folder per app; tip to generate an add-repository button at https://my.home-assistant.io/create-link/ for the README.
- **Relevance**: my.home-assistant.io link convention.

### Supervisor source (local clone)
- **URL**: ~/source/supervisor/supervisor/{apps/model.py:182, apps/validate.py:137,525-526, discovery/validate.py, api/discovery.py:92-110, store/utils.py:12, config.py:57}
- **Type**: primary source code
- **Key takeaway**: (a) `hostname = slug.replace("_","-")`; slug = `<sha1(repo_url.lower())[:8]>_<slug>`. (b) Discovery has NO allowlist of service names: schema is `vol.Optional(ATTR_DISCOVERY): [str]`; the only check is that the POSTed `service` is in the app's own `discovery:` list, else the POST is rejected with "Apps must list services they provide via discovery in their config!". (c) Payload is `{service, config: dict|null}`; `addon` key is deprecated since 2026.05 in favour of `app`. (d) map regex accepts both `app_config` and `addon_config` (and `all_app_configs`/`all_addon_configs`), so legacy names still validate. (e) `backup_exclude: [str]`.
- **Relevance**: a custom service name such as `hassette` is legal.

### HA core hassio discovery handler (local clone)
- **URL**: ~/source/core/homeassistant/components/hassio/discovery.py:113-140
- **Type**: primary source code
- **Key takeaway**: Core calls `discovery_flow.async_create_flow(hass, data.service, context={"source": SOURCE_HASSIO}, data=HassioServiceInfo(config, name, slug, uuid))`. The flow domain is simply the service string. No manifest key and no allowlist (grep of loader.py / hassfest manifest.py finds no "hassio" key). Any integration domain whose ConfigFlow defines `async_step_hassio` receives it, so a HACS custom integration with domain equal to the add-on's discovery service name should work. I found no existing custom integration doing this [no source found], so it is inferred from code, not observed in the wild.
- **Relevance**: answers "can a HACS integration consume discovery".

### AppDaemon add-on config.yaml
- **URL**: https://raw.githubusercontent.com/hassio-addons/addon-appdaemon/main/appdaemon/config.yaml (summarized)
- **Type**: add-on manifest
- **Key takeaway**: options are only `system_packages`, `python_packages`, `init_commands` (all empty lists) + `log_level`. map: `addon_config`, `homeassistant_config`, `media`, `share`, `ssl` (all rw). Port 5050. No discovery, no backup_exclude shown.
- **Relevance**: closest analogue (Python code host).

### AppDaemon DOCS.md
- **URL**: https://raw.githubusercontent.com/hassio-addons/addon-appdaemon/main/appdaemon/DOCS.md
- **Type**: add-on docs
- **Key takeaway**: "It does, however, create some sample files to get you started on the first run." Ships without `token`/`ha_url` in appdaemon.yaml; "no need to create access tokens or to set your Home Assistant URL" (Supervisor token injected). Packages via options only; requirements.txt not mentioned. Docs say "found in the app configuration folder" without naming the path.
- **Relevance**: model for zero-config HA connection and option-based deps.

### AppDaemon init run script
- **URL**: https://raw.githubusercontent.com/hassio-addons/addon-appdaemon/main/appdaemon/rootfs/etc/s6-overlay/s6-rc.d/init-appdaemon/run (summarized)
- **Type**: add-on code
- **Key takeaway**: Migration: if `/config/appdaemon.yaml` is absent but `/homeassistant/appdaemon/appdaemon.yaml` exists, move all files (incl. hidden) into `/config/` (app_config). Seed: if still no `appdaemon.yaml`, copy defaults from the image. Then patch token/http url if missing; apt install `system_packages`; `uv` install `python_packages` into the venv; run `init_commands` each start. Seed-if-absent check on one sentinel file = no overwrite.
- **Relevance**: canonical seed + migrate + install sequence.

### AppDaemon user reports on the config move
- **URL**: https://community.home-assistant.io/t/appdaemon-add-on-config-files/965196 ; https://community.home-assistant.io/t/appdaemon-not-seeing-my-apps/933480 ; https://community.home-assistant.io/t/appdaemon-config-files-where/975855
- **Type**: forum threads (from search snippets, threads not opened)
- **Key takeaway**: Users confused by `/addon_configs/a0d7b954_appdaemon` vs `/config/appdaemon`; apps not loaded after update; restored backup left folder empty; duplicate `apps.yaml` in both locations (symlink left behind). Docs inconsistency (README says /config/appdaemon, Samba path is addon_configs). Anecdotal, no official migration announcement found.
- **Relevance**: documents the failure mode to avoid: state the host-visible path in DOCS.md once, and never leave two live locations.

### Mosquitto config.yaml
- **URL**: https://raw.githubusercontent.com/home-assistant/addons/master/mosquitto/config.yaml (summarized)
- **Type**: add-on manifest
- **Key takeaway**: `discovery: [mqtt]`, `services: [mqtt:provide]`, `startup: system`, `auth_api: true`, map `ssl`,`share`. Options are structured (logins, certs). Integration side: `async_step_hassio` copies `config` (host, port, username, password, protocol, ssl) into the entry (core mqtt/config_flow.py:4407-4430). Added to MQTT in 2018 (core commit "Add Hass.io discovery to MQTT (#16962)").
- **Relevance**: credentials ride inside the discovery payload.

### Matter Server config.yaml
- **URL**: https://raw.githubusercontent.com/home-assistant/addons/master/matter_server/config.yaml (summarized)
- **Type**: add-on manifest
- **Key takeaway**: options only `log_level, beta, enable_test_net_dcl, time_sync`; `discovery: [matter]`; map `type: app_config, read_only: false`; `stage: stable`; no backup_exclude; run script backgrounds `matter-server-discovery` which posts discovery. Core `matter/config_flow.py:252` checks `discovery_info.slug == ADDON_SLUG` then builds `ws://host:port`; the handler was present from integration birth (core commit "Add matter integration BETA (#83064)", Dec 2022).
- **Relevance**: minimal options + slug guard in async_step_hassio.

### Z-Wave JS config.yaml
- **URL**: https://raw.githubusercontent.com/home-assistant/addons/master/zwave_js/config.yaml (summarized)
- **Type**: add-on manifest
- **Key takeaway**: `discovery: [zwave_js]`, `map: app_config:rw`, ingress 8091, `stage: stable`, `hassio_api: true`; options hold security keys (empty by default), device, log settings. Core `zwave_js/config_flow.py:779` also slug-guards and builds `ws://host:port`; discovery step added with the integration's add-on support (Jan 2021, #45552).
- **Relevance**: shows slug guard and "confirm" step pattern.

### ESPHome config.yaml
- **URL**: https://raw.githubusercontent.com/esphome/home-assistant-addon/main/esphome/config.yaml (summarized)
- **Type**: add-on manifest
- **Key takeaway**: `discovery: [esphome]`, `map: config:rw`, `backup_exclude: '*/*/'` (excludes build dirs two levels down), schema with only 3 optional booleans/ints. Core esphome `async_step_hassio` just stores dashboard host/port then aborts `service_received` (no user prompt; added Jan 2023, #85662, years after the add-on).
- **Relevance**: only add-on found using backup_exclude for build artifacts plus silent discovery.

### Music Assistant add-on + integration
- **URL**: https://raw.githubusercontent.com/music-assistant/home-assistant-addon/main/music_assistant/config.yaml (summarized); core `homeassistant/components/music_assistant/config_flow.py:136-190` (local)
- **Type**: add-on manifest + integration code
- **Key takeaway**: options `log_level`, `safe_mode`; `discovery: [music_assistant]`; `backup_exclude: cache.db, collage_images/*, .cache/*, library.db.backup` (the library DB itself is NOT excluded); `stage: stable`; host_network, ingress 8094. Integration reads `config["host"]`, `config["port"]` and `config["auth_token"]` from discovery ("We trust the token from hassio discovery and validate it during setup"). That token path arrived with commit "Add support for authentication to the Music Assistant integration (#157257)", Nov 2025; the integration existed since Oct 2024 (#128919) and `git log -S"hassio"` on its config_flow shows only the Nov 2025 commit, so hassio discovery was added later, with auth, not in the first release.
- **Relevance**: the one real example of an add-on handing an API token to an integration through discovery. Closest match to hassette's need.

### Music Assistant repo layout
- **URL**: https://github.com/music-assistant/home-assistant-addon
- **Type**: repo listing
- **Key takeaway**: sibling folders `music_assistant/`, `music_assistant_beta/`, `music_assistant_dev/`, `music_assistant_nightly/` in one repo with one `repository.json`. Naming/docs of channels not visible on that page.
- **Relevance**: release channels.

### Zigbee2MQTT add-on
- **URL**: https://raw.githubusercontent.com/zigbee2mqtt/hassio-zigbee2mqtt/master/zigbee2mqtt/config.json ; .../DOCS.md
- **Type**: add-on manifest + docs
- **Key takeaway**: JSON manifest (repo predates YAML). map: `share`, `homeassistant_config` at `/config`, `app_config` at `/addon_config`, `ssl`; `data_path` option default `/config/zigbee2mqtt` (config stayed in HA config dir; app_config mounted alongside). `services: mqtt:need`; no discovery (Z2M is a client; HA talks to it via MQTT). Docs: "Settings configured through the app configuration page will take precedence over settings in the configuration.yaml"; remove them from the page for full YAML control. No seeding: first run shows a frontend onboarding page. No backup_exclude shown.
- **Relevance**: only add-on found that documents option-vs-file precedence explicitly.

### Node-RED add-on
- **URL**: https://raw.githubusercontent.com/hassio-addons/addon-node-red/main/node-red/config.yaml ; .../DOCS.md
- **Type**: add-on manifest + docs
- **Key takeaway**: options: theme, http_node/http_static creds, ssl, `system_packages`, `npm_packages`, `init_commands`, `credential_secret`. map `addon_config:rw` + `homeassistant_config:rw` + media/share/ssl. `backup_exclude: ["node_modules"]`. No discovery. HA connection is pre-wired through Supervisor token ("no need to add/change the server connection settings"), troubleshooting note about the "I use the Home Assistant App" checkbox.
- **Relevance**: backup_exclude for dependency dir, option-based deps, flows stay in config folder (docs do not say they are seeded).

### Studio Code Server config.yaml
- **URL**: https://raw.githubusercontent.com/hassio-addons/addon-vscode/main/vscode/config.yaml (summarized)
- **Type**: add-on manifest
- **Key takeaway**: options `packages`, `init_commands`; optional `config_path`; map includes `all_addon_configs`, `addons`, `backup`, `media`, `share`, `ssl`, `homeassistant_config` at `/config`. No backup_exclude, no stage.
- **Relevance**: minimal-options code host.

## Survey Table

| Add-on | Options | Config map | Seeds starter | backup_exclude | Discovery (payload, first release?) | Channels |
|---|---|---|---|---|---|---|
| AppDaemon | system_packages, python_packages, init_commands, log_level | addon_config (moved from homeassistant_config/appdaemon), + homeassistant_config, share, media, ssl | Yes: copies sample files if `appdaemon.yaml` absent; migrates old dir | none seen | none; Supervisor token injected into config | single [no source found for others] |
| Node-RED | theme, http creds, ssl, system/npm_packages, init_commands, credential_secret | addon_config:rw (+homeassistant_config etc.) | not stated in docs | `node_modules` | none | not checked |
| Studio Code Server | packages, init_commands, config_path | all_addon_configs + homeassistant_config at /config | n/a | none | none | not checked |
| ESPHome | 3 optional bools/ints | config:rw (old style) | n/a | `*/*/` | `esphome`; host+port; integration added Jan 2023 (late) | dev variants exist [not verified] |
| Zigbee2MQTT | data_path, mqtt, serial, socat; options override YAML | homeassistant_config(/config) + app_config(/addon_config) | no (onboarding UI) | none | none (`mqtt:need`) | edge folder not verified (fetch 404) |
| Music Assistant | log_level, safe_mode | media:rw, ssl:ro (own data in /data) | n/a | cache.db, collage_images/*, .cache/*, library.db.backup | `music_assistant`; host, port, auth_token; added Nov 2025 with auth, NOT first release | beta, dev, nightly folders, same repo |
| Matter Server | log_level, beta, enable_test_net_dcl, time_sync | app_config rw | n/a | none | `matter`; host, port; from integration's first release (Dec 2022) | beta via option flag |
| Z-Wave JS | log, rf_region, 6 key fields, device | app_config:rw | n/a | none | `zwave_js`; host, port; from Jan 2021 integration support | single |
| Mosquitto | logins, certs, customize | ssl, share | n/a | none | `mqtt` (+`services mqtt:provide`); host, port, username, password, protocol, ssl; 2018 | single |

## Patterns Found

### Pattern 1: Near-empty options, config file is the product
**Used by**: Matter Server, Music Assistant, ESPHome, Z-Wave JS (log level + a few toggles); AppDaemon/Node-RED/VS Code (plus package lists).
**How it works**: options carry only operational toggles and dependency lists. User logic lives in the mapped config dir. Count: 8 of 8 surveyed.
**Strengths**: no dual source of truth. **Weaknesses**: Z2M shows the failure case when both exist (precedence must be documented).
**Example**: Z2M DOCS: "Settings configured through the app configuration page will take precedence over settings in the `configuration.yaml`".

### Pattern 2: app_config as the home of user code and config, seeded by sentinel
**Used by**: AppDaemon, Node-RED (addon_config), Matter, Z-Wave JS, Z2M (alongside homeassistant_config). 5 of 8 use app_config/addon_config; ESPHome and VS Code still use config/homeassistant_config.
**How it works**: init script migrates legacy dir if present, then seeds defaults only if a sentinel file is missing.
**Strengths**: backups include it automatically (app_config is part of the app backup); no overwrite. **Weaknesses**: host path (`/addon_configs/<hash>_<slug>`) is unintuitive; forum confusion when docs and path disagree.
**Example**: AppDaemon init-appdaemon run script (above).

### Pattern 3: Dependency installs via option lists, re-run at every start
**Used by**: AppDaemon (python_packages via uv, system_packages via apt, init_commands), Node-RED (npm_packages, system_packages, init_commands), VS Code (packages, init_commands). 3 of 3 code hosts.
**How it works**: lists in options; init script installs on each start; docs warn "many packages = longer start-up". Nobody documents requirements.txt in the config dir (not found for any of the three).
**Strengths**: visible in UI. **Weaknesses**: slow starts; hassette's `uv.lock`/requirements.txt in `/config` is an unprecedented but more natural approach. Whether AppDaemon caches between restarts [no source found].

### Pattern 4: Discovery carries connection data, integration confirms (or silently adopts)
**Used by**: mqtt, zwave_js, matter, esphome, music_assistant (+ 11 other core integrations with `async_step_hassio`: adguard, mealie, motioneye, mcp, deconz, otbr, pyload, uptime_kuma, vlc_telnet, wyoming, onewire).
**How it works**: add-on lists the service in `discovery:`, init script POSTs `{service, config:{host,port,...}}` to http://supervisor/discovery (no `hassio_api` needed). Core starts a flow with domain = service name, source `hassio`. Integration slug-guards (`discovery_info.slug`), validates, shows `hassio_confirm`, creates entry keyed on `uuid`/server id; on config entry removal core re-requests the discovery.
**Strengths**: zero user input; Music Assistant even passes an `auth_token`. **Weaknesses**: only core integrations seen using it; custom ones [no source found]. Discovery was sometimes added late (MA Nov 2025, ESPHome years later).
**Example**: core music_assistant/config_flow.py:136-190.

### Pattern 5: backup_exclude for rebuildable artifacts only
**Used by**: Node-RED (node_modules), ESPHome (`*/*/` build dirs), Music Assistant (caches, but keeps library.db). 3 of 8 surveyed; none use `backup: cold`.
**Strengths**: small backups. **Weaknesses**: none noted. DBs are not excluded (MA excludes only cache.db and the DB's backup copy).

### Pattern 6: Channels as sibling folders in one repo
**Used by**: Music Assistant (`music_assistant`, `_beta`, `_dev`, `_nightly`), HA docs suggest the alternative of branches (`#next`) with distinct repo names. Matter uses an in-option `beta: bool`.
**Strengths**: one repo, one add-repository link. **Weaknesses**: duplicated folder content.

### Pattern 7: Docs split
**Used by**: all (official guidance): README.md short store blurb, DOCS.md full config, CHANGELOG.md Keep-a-Changelog, icon.png 128x128, logo.png ~250x100, translations/en.yaml (configuration + network keys only), my.home-assistant.io create-link button in README. Z2M repo ships all six files (README, DOCS, CHANGELOG, config.json, icon, logo).

## Anti-Patterns

- Two live config locations with docs naming a different one (AppDaemon: README says /config/appdaemon, actual /addon_configs/a0d7b954_appdaemon; users end up with duplicate apps.yaml and stale state).
- Options silently overriding file settings without UI hint (Z2M documents it, only in DOCS.md).
- Installing a long package list on every start (all three code hosts warn about it).

## Emerging Trends

- Rename addon -> app across Supervisor 2026.05 (`app_config`, `all_app_configs`, discovery key `app`); legacy `addon_config` still validates, so old repos keep working. Developer docs now list `app_config` only.
- Token-in-discovery (Music Assistant, Nov 2025) as the way to avoid URL+token copy/paste.

## Gaps
- Q4: no add-on found using `backup: cold`; the MA/ESPHome docs were not checked for DB handling beyond config.yaml.
- Q8: translations/en.yaml examples, badges, and `stage: experimental` usage not directly confirmed; only the developer-docs wording.
- Q9: Z2M edge and ESPHome dev folder names not verified (404 on fetch).
- No custom/HACS integration using `async_step_hassio` found; only code-level inference.
- AppDaemon python_packages caching between restarts: [no source found].
