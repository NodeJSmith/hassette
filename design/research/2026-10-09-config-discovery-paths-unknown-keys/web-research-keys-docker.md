# Prior art: unknown config keys, prefixed env vars, Docker/HA add-on dir conventions

Date: 2026-10-09. "Verified locally" = I ran the tool (ruff 0.16.10, pytest 9.1.1, mypy via uvx, cargo, docker compose) in a scratch dir.

## Sources Found

### pydantic-settings docs (extra / env_prefix / dotenv)
- **URL**: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/
- **Type**: documentation
- **Key takeaway**: Unknown env vars are "ignored, even if they start with `env_prefix`". `extra` "validates inputs passed to the model; it does not check every name in `os.environ`". `.env` entries ARE validated (`extra='forbid'` raises `ValidationError`); `dotenv_filtering='match_prefix'` limits which dotenv vars reach the model.
- **Relevance**: Direct cause of the `HASSETTE__APP_DIR` bug. `extra='forbid'` fixes file keys and `.env` entries but cannot fix real environment variables.

### pydantic-settings issue #985 (maintainer declined a built-in fix)
- **URL**: https://github.com/pydantic/pydantic-settings/issues/985
- **Type**: reference implementation issue
- **Key takeaway**: Reporter: with `env_prefix` + `env_nested_delimiter="__"` + `extra="forbid"`, a typo inside a nested section (`PFX_TELEGRAM__BOT_TOKEM`) errors, but a top-level typo (`PFX_TELEGRAM_BOT_TOKEN`) is silently dropped. Maintainer (hramezani) declined an opt-in `env_extra="forbid"`: the env source looks up known fields rather than scanning `os.environ`, and "a shared prefix isn't a reliable sign that a variable was meant for the settings class". Docs updated instead (PR #986). `.env` files do reject extras because they are a bounded namespace.
- **Relevance**: Confirms there is no upstream fix coming. Any detection of unknown `HASSETTE__*` vars has to be hassette's own startup scan of `os.environ`. Nested typos (`HASSETTE__APPS__DIRECTRY`) are caught by forbid only if nested models forbid extras.

### Other pydantic-settings issues (env_prefix leakage)
- **URL**: https://github.com/pydantic/pydantic-settings/issues/437 , https://github.com/pydantic/pydantic-settings/issues/215 , https://github.com/pydantic/pydantic/issues/12242
- **Type**: issue threads
- **Key takeaway**: #215: in `.env`, unknown *prefixed* names raise "Extra inputs are not permitted" while unprefixed names are silently ignored. #437: unprefixed vars can be read when `env_prefix` is set. I found no issue requesting a "warn on unused env vars" feature other than #985.
- **Relevance**: Background on dotenv vs real-env asymmetry.

### pytest: unknown ini keys
- **URL**: https://docs.pytest.org/en/stable/reference/customize.html (page itself does not state the behavior); behavior verified locally; source mirror https://docs.pytest.org/en/9.0.x/_modules/_pytest/main.html
- **Type**: tool behavior (verified locally)
- **Key takeaway**: Default: `PytestConfigWarning: Unknown config option: addopts_typo` (warning). `--strict-config` turns it into `ERROR: Unknown config option: addopts_typo` and aborts. No did-you-mean.
- **Relevance**: The canonical "warn by default, opt-in error" model.

### ruff (verified locally)
- **URL**: [no doc page states it]; verified with ruff 0.16.10
- **Type**: tool behavior
- **Key takeaway**: `[tool.ruff] line-lenght = 100` aborts: `ruff failed / Cause: TOML parse error ... unknown field 'line-lenght'`. Hard error, no did-you-mean (the serde error lists no suggestion in the output I saw).
- **Relevance**: Hard-error model for a pre-1.0 tool config.

### mypy (verified locally)
- **URL**: https://mypy.readthedocs.io/en/stable/config_file.html (docs silent on unknown options)
- **Type**: tool behavior
- **Key takeaway**: `mypy.ini: [mypy]: Unrecognized option: warn_unsued_ignores = True`, printed, run continues and exits success. Warning model, no strict flag found.
- **Relevance**: Warn-and-continue example.

### Cargo
- **URL**: https://doc.rust-lang.org/cargo/reference/manifest.html
- **Type**: documentation + verified locally
- **Key takeaway**: Docs: "Cargo by default will warn about unused keys in `Cargo.toml` to assist in detecting typos and such." Exempt namespace: `package.metadata` ("completely ignored by Cargo and will not be warned about"). Verified: `warning: unused manifest key: package.authr`; no did-you-mean. Discussion of noise from custom keys: https://internals.rust-lang.org/t/cargo-manifest-and-unused-manifest-key-allow-other-tools-to-extend-the-manifest/16333
- **Relevance**: Best precedent for "warn about typos, but give tools a sanctioned namespace to avoid false positives" (analogous to a separate prefix for wrapper-script vars).

### Docker Compose (verified locally)
- **URL**: https://docs.docker.com/reference/compose-file/ (page silent on this)
- **Type**: tool behavior
- **Key takeaway**: `validating compose.yaml: services.a additional properties 'imge' not allowed`. Hard error from JSON-schema validation (`x-` extension keys are the sanctioned escape; docs page I fetched did not state that, from memory only [no source found]).
- **Relevance**: Hard error with a path to the offending key.

### kubectl apply --validate
- **URL**: https://kubernetes.io/docs/reference/kubectl/generated/kubectl_apply/
- **Type**: documentation
- **Key takeaway**: `--validate` default `strict`: "fail the request if invalid"; `warn` warns on unknown/duplicate fields; `ignore` "silently dropping any unknown or duplicate fields". Three-level knob, strict is default.
- **Relevance**: Strict-by-default precedent; a mode switch is what some tools add after complaints.

### Traefik
- **URL**: https://doc.traefik.io/traefik/v3.5/getting-started/faq/
- **Type**: documentation
- **Key takeaway**: "The 'field not found' error occurs, when an unknown property is encountered in the dynamic or static configuration." Fatal at startup. Community reports show the same failure for env vars: `failed to decode configuration from environment variables: field not found, node: domain` (https://community.traefik.io/t/docker-compose-static-config-issue/10987). Traefik decodes the whole `TRAEFIK_*` env namespace into the struct, so unknown prefixed vars fail startup.
- **Relevance**: The one tool I found that errors on unknown prefixed env vars, because it owns the whole prefix.

### Grafana env overrides
- **URL**: https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/
- **Type**: documentation
- **Key takeaway**: `GF_<SECTION>_<KEY>`; "Don't use environment variables to *add* new configuration settings." Unknown `GF_*` vars do nothing; docs do not say a warning is emitted. A community thread says startup logs list each applied override ("Config overridden from Environment variable") (https://community.grafana.com/t/environment-variables-are-not-working-it-seems-im-not-alone/38631, found via search, not fetched).
- **Relevance**: Ignore-silently, with an "applied overrides" log line as the observability substitute.

### Home Assistant core YAML validation
- **URL**: https://community.home-assistant.io/t/extra-keys-error/101249 ; https://developers.home-assistant.io/docs/core/integration/yaml_configuration
- **Type**: community thread (not official docs) / documentation
- **Key takeaway**: Voluptuous `extra keys not allowed @ data[...]` is the message. Community report says that since ~0.88 unsupported platform keys are flagged as warnings "to help with finding typos", with an intent to become errors later. I did not find official docs stating the current policy. [partial: official policy not confirmed]
- **Relevance**: HA convention is schema-validated with the offending path in the message.

### Zigbee2MQTT
- **URL**: https://www.zigbee2mqtt.io/guide/configuration/ ; https://www.zigbee2mqtt.io/guide/installation/02_docker.html ; https://raw.githubusercontent.com/Koenkk/zigbee2mqtt/master/docker/Dockerfile
- **Type**: documentation
- **Key takeaway**: Config env override prefix is `ZIGBEE2MQTT_CONFIG_` (e.g. `ZIGBEE2MQTT_CONFIG_MQTT_BASE_TOPIC`); a separate, non-`_CONFIG_` var `ZIGBEE2MQTT_DATA` selects the data dir. So Z2M already uses a split: settings under `..._CONFIG_*`, process-level vars elsewhere under the same product prefix. Startup refuses invalid configuration.yaml with per-field errors (forum evidence: https://community.simon42.com/t/zigbee2mqtt-configuration-is-not-valid/57458); I did not see the exact unknown-key text. Docker: mount `-v $(pwd)/data:/app/data`; Dockerfile sets only `ENV NODE_ENV=production`, `WORKDIR /app`, so `/app/data` is the code's default path relative to the app dir, not an ENV.
- **Relevance**: Direct precedent for splitting prefixes: settings = `PFX_CONFIG_*`, runtime/location vars = `PFX_<NAME>`.

### Dynaconf
- **URL**: https://dynaconf.readthedocs.io/en/docs_223/guides/configuration.html
- **Type**: documentation
- **Key takeaway**: Default prefix `DYNACONF_`, customizable via `envvar_prefix`. Validators check only the names they list. I found no source saying unknown prefixed vars warn. [no source found for warn behavior]
- **Relevance**: Not a precedent for warning.

### Spring Boot / Rails / Vector / Kong / Postgres / HA / cargo `CARGO_*`
- **URL**: [no source found]
- **Type**: —
- **Key takeaway**: My searches found no documented "warn on unrecognized prefixed env var" in these. Spring Boot's unknown-property handling: only IDE inspections found (https://jetbrains.com/help/inspectopedia/SpringBootApplicationYaml.html); runtime behavior for unbound keys not confirmed (my recollection is `ignoreUnknownFields=true` by default [no source found]). Vector, Kong, Rails, Postgres, `CARGO_*` not checked in depth.

### Home Assistant add-on developer docs (config.yaml / map)
- **URL**: https://developers.home-assistant.io/docs/add-ons/configuration/ ; https://developers.home-assistant.io/blog/2023/11/06/public-addon-config
- **Type**: documentation
- **Key takeaway**: Current docs have renamed "add-on" to "app": `addon_config` is now `app_config`, `local_addons` is `local_apps`, and the page I fetched does not mention `/addon_configs/<slug>` (the host path in the current text is `/app_configs/{REPO}_<slug>`). Fetching the 2023 blog gives: "the supervisor will create a folder for that add-on at `/addon_configs/<your addon slug>` and map that to `/config` within the add-on container"; `addon_config:rw` for write; cannot combine `config` and `addon_config` in `map`; HA's own config via `homeassistant_config` mounts at `/homeassistant`. Default for any `map` type: mounts at `/<type-name>`, read-only unless `:rw`; `data` always mapped writable at `/data`. `/data/options.json` holds user options; `schema` validates them (`schema: false` disables); read with `bashio::config 'key'`. Docs warn about leftover options "not in the schema" only for removed options.
- **Relevance**: `addon_config` is the sanctioned place for user config AND user code; it is included in backups, unlike `/config` or `share` (blog motivation).

### HA Container install
- **URL**: https://www.home-assistant.io/installation/linux/#install-home-assistant-container
- **Type**: documentation
- **Key takeaway**: Only user-facing contract: mount `-v /PATH:/config`, env `TZ`. No env var for the config path; image has a fixed `/config`.
- **Relevance**: Fixed-path-in-image convention.

### AppDaemon Docker + add-on
- **URL**: https://appdaemon.readthedocs.io/en/latest/DOCKER_TUTORIAL.html ; https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/Dockerfile ; https://appdaemon.readthedocs.io/en/latest/_sources/ADDON.md.txt ; https://raw.githubusercontent.com/hassio-addons/addon-appdaemon/main/appdaemon/config.yaml ; https://raw.githubusercontent.com/hassio-addons/addon-appdaemon/main/appdaemon/rootfs/etc/s6-overlay/s6-rc.d/appdaemon/run
- **Type**: documentation / reference implementation
- **Key takeaway**: Docker image: `VOLUME /conf`, `WORKDIR /conf`, `COPY ./conf /opt/conf`, ENTRYPOINT `/start.sh`; no ENV for the path. Docs: mount `-v <conf>:/conf`; documented env vars `HA_URL`, `TOKEN`, `DASH_URL`; extra flags appended after the image name (e.g. `-D DEBUG`). Add-on: `map: addon_config:rw, homeassistant_config:rw, media:rw, share:rw, ssl`; options are only `log_level`, `system_packages`, `python_packages`, `init_commands`; run script hardcodes `exec /opt/appdaemon/bin/appdaemon -c /config -D "${log_level}"` (bashio reads `log_level`; token comes from `SUPERVISOR_TOKEN`). Config folder is `/config` in the container, `/addon_configs/a0d7b954_appdaemon` over Samba, `/mnt/data/supervisor/addon_configs/a0d7b954_appdaemon` on host.
- **Relevance**: Closest sibling to hassette. Add-on = tiny options.json (packages, log level), real settings stay in the app's own config file in `addon_config`; path passed by CLI flag in the run script, not ENV.

### AppDaemon add-on migration from /config/appdaemon
- **URL**: https://github.com/hassio-addons/addon-appdaemon/blob/v0.2.5/README.md (old: "/config/appdaemon"); user reports https://community.home-assistant.io/t/appdaemon-add-on-config-files/965196 , https://community.home-assistant.io/t/judo-water-treatment/380936/81
- **Type**: README + community reports
- **Key takeaway**: Old README put config in `/config/appdaemon`; current is `addon_config`. I found no official migration guide or changelog entry; users report empty old dir after restore, files moved into `addon_configs/.../apps`, lost `apps.yaml` entries, and having to point `secrets` at `/homeassistant/secrets.yaml`. [official migration doc: no source found]
- **Relevance**: A path move with no migration tooling caused user pain; a pre-1.0 clean break should ship an explicit startup error/message pointing at the old path.

### Node-RED Docker + add-on
- **URL**: https://nodered.org/docs/getting-started/docker ; https://raw.githubusercontent.com/node-red/node-red-docker/master/docker-custom/scripts/entrypoint.sh ; https://raw.githubusercontent.com/hassio-addons/addon-node-red/main/node-red/config.yaml
- **Type**: documentation / reference implementation
- **Key takeaway**: Docs: "Node-RED uses the `/data` directory inside the container to store user configuration data." Entrypoint passes the dir as a CLI arg: `... red.js --userDir /data $FLOWS "${@}"`. Documented env vars use `NODE_RED_` prefix (`NODE_RED_ENABLE_SAFE_MODE`, `NODE_RED_ENABLE_PROJECTS`; `NODE_RED_CREDENTIAL_SECRET` is read by user's settings.js). Add-on: `map: addon_config:rw, homeassistant_config:rw, media:rw, share:rw, ssl`, options (theme, ssl, certfile, system_packages, npm_packages, init_commands, ...).
- **Relevance**: CLI arg in entrypoint, fixed in-image path; user-extensible via mounted volume.

### ESPHome add-on
- **URL**: https://raw.githubusercontent.com/esphome/home-assistant-addon/main/esphome/config.yaml ; https://esphome.io/guides/getting_started_hassio
- **Type**: reference implementation / documentation
- **Key takeaway**: Add-on `map: config:rw` (the legacy HA config mount); official guide says files live in `<HA config>/esphome/` (e.g. `/config/esphome/bedroom-light.yaml`). Not migrated to `addon_config` as of the file I fetched. Z2M add-on config not retrievable (404s) [no source found].
- **Relevance**: Not all add-ons migrated; `addon_config` is recommended but not universal.

### linuxserver.io
- **URL**: https://docs.linuxserver.io/general/understanding-puid-and-pgid/
- **Type**: documentation
- **Key takeaway**: PUID/PGID env vars map container user to host user (verified). The `/config` convention page was not fetched, so "`/config` is the single persistent volume in every lscr image" is from memory [no source found in this run].
- **Relevance**: Env vars used by the image/entrypoint (PUID, PGID, TZ) are un-prefixed process-level vars, separate from app settings.

## Patterns Found

### Pattern 1: Warn on unknown file keys, opt-in strict
**Used by**: pytest (`--strict-config`), Cargo (warning, `package.metadata` exempt), mypy (warning), kubectl (`--validate=warn|strict|ignore`), HA core platform keys (warning, per community thread).
**How it works**: Parse tolerant by default, report each unknown key by name, continue. pytest and kubectl give a switch to make it fatal. Cargo carves out a namespace (`package.metadata`) for tool-private data so the warning has no false positives.
**Strengths**: Never bricks a working setup on upgrade; catches typos.
**Weaknesses**: Warnings get ignored (the very bug here would have been a log line). No tool in my set does did-you-mean for config keys.
**Example**: pytest 9.1.1 output above; https://doc.rust-lang.org/cargo/reference/manifest.html

### Pattern 2: Error on unknown file keys (schema-validated)
**Used by**: ruff (verified), Docker Compose (verified), Traefik (docs), Zigbee2MQTT (startup validation), kubectl default (`strict`), pydantic `extra='forbid'`.
**How it works**: Schema/serde rejects unknown fields at load; the message names the key (and path for compose/HA). Process exits non-zero.
**Strengths**: Typos cannot hide; matches "pre-1.0, clean breaks".
**Weaknesses**: Upgrades that rename keys hard-fail users; shared files need an escape hatch (compose `x-`, Cargo `metadata`).
**Example**: `ruff failed ... unknown field 'line-lenght'`; `additional properties 'imge' not allowed`.

### Pattern 3: Env vars are NOT validated against settings (the dominant norm)
**Used by**: pydantic-settings (maintainer-confirmed in #985), Grafana (`GF_*` only override existing options; no documented warning), likely Dynaconf, Spring Boot [unconfirmed].
**How it works**: The env source looks up known fields; unknown names are never read. A shared prefix is deemed unreliable as intent.
**Strengths**: Safe when the prefix is shared with other processes.
**Weaknesses**: Typos silently ignored, exactly the reported bug.
**Example**: https://github.com/pydantic/pydantic-settings/issues/985

### Pattern 4: Own the whole prefix, fail on unknown (Traefik)
**Used by**: Traefik (`TRAEFIK_*` decode fails with `field not found`).
**How it works**: The product decodes every var under its prefix into its config struct; unknown means fatal.
**Strengths**: Typos caught immediately.
**Weaknesses**: Requires that nothing else (wrapper scripts, platform) use that prefix; this is what the hassette entrypoint vars (`HASSETTE__INSTALL_DEPS`, `HASSETTE__PROJECT_DIR`) violate.
**Example**: https://community.traefik.io/t/docker-compose-static-config-issue/10987

### Pattern 5: Split namespaces: settings prefix vs process/wrapper vars
**Used by**: Zigbee2MQTT (`ZIGBEE2MQTT_CONFIG_*` for settings, `ZIGBEE2MQTT_DATA` for location), Node-RED (`NODE_RED_*` run flags vs `settings.js` content), linuxserver (`PUID/PGID/TZ` un-prefixed), AppDaemon (`HA_URL/TOKEN/DASH_URL` un-prefixed).
**How it works**: Settings get a dedicated sub-prefix (or file); wrapper/runtime vars live outside it. With Z2M the sub-prefix is the only thing the config loader scans.
**Strengths**: Makes Pattern 4 possible without collision; no allowlist to maintain.
**Weaknesses**: Two prefixes to document.
**Example**: https://www.zigbee2mqtt.io/guide/configuration/

### Pattern 6: Docker image fixes the dir; user mounts a volume
**Used by**: Home Assistant (`/config`), AppDaemon (`VOLUME /conf`, `WORKDIR /conf`), Node-RED (`/data`, `--userDir /data` in entrypoint), Zigbee2MQTT (`/app/data`, default relative to `WORKDIR /app`; `ZIGBEE2MQTT_DATA` documented as override).
**How it works**: One conventional in-container path, documented as a mount point. Where the app needs to be told, the entrypoint passes a CLI arg (Node-RED `--userDir`, AppDaemon add-on `-c /config`), not a Dockerfile ENV. None of the four surveyed set a path ENV in the Dockerfile (Z2M Dockerfile ENV is just NODE_ENV; AppDaemon Dockerfile ENV is uv/python only).
**Strengths**: Users never set a path var; docs say "mount here".
**Weaknesses**: Fixed path means a custom layout needs an override.
**Example**: https://nodered.org/docs/getting-started/docker ; https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/Dockerfile

### Pattern 7: HA add-on = `addon_config:rw` at `/config`, `/data/options.json` for small UI options
**Used by**: AppDaemon add-on, Node-RED add-on (both map `addon_config:rw` + `homeassistant_config:rw` + `share:rw` + `media:rw` + `ssl`); ESPHome still uses `config:rw`.
**How it works**: User config and user code (apps, flows) live in `/config` inside the container = `/addon_configs/<slug>` on host. Options UI is minimal (log level, package lists, ssl); run script reads them via bashio and passes CLI flags/env; real settings stay in the app's own file. HA's own config (secrets) is a separate `/homeassistant` mount.
**Strengths**: Included in backups; scoped; official recommendation.
**Weaknesses**: Moving existing users from `/config/<app>` had no official migration tooling and caused breakage reports.
**Example**: https://developers.home-assistant.io/blog/2023/11/06/public-addon-config

## Tally

### Q1: unknown keys in files
| Tool | Behavior | Did-you-mean |
|---|---|---|
| ruff | error, exit (verified) | no |
| Docker Compose | error w/ key path (verified) | no |
| Traefik | error `field not found` (docs) | no |
| kubectl apply | `strict` default; `warn`/`ignore` modes (docs) | no |
| Zigbee2MQTT | startup refuses invalid config (forum) | not seen |
| pytest | warning; `--strict-config` -> error (verified) | no |
| Cargo | warning; `package.metadata` exempt (verified+docs) | no |
| mypy | warning, continues (verified) | no |
| HA core YAML | warning for platform keys per forum; extra-keys schema error | no |
| pydantic-settings | `forbid` errors for init/dotenv/nested; ignores top-level env | no |
| Dynaconf | [no source found] | — |
| ESPHome, ESLint, tsconfig | not checked [no source found] | — |
Did-you-mean: clap does it for CLI args (https://redirect.github.com/clap-rs/clap/pull/5075 discusses its suggestion engine); none of the config-file tools above did in my runs.

### Q2: unknown prefixed env vars
| Tool | Behavior |
|---|---|
| pydantic-settings | ignored, even with `forbid`; maintainer declined to change (#985) |
| Traefik | decode error `field not found` (community reports) |
| Grafana `GF_*` | no effect, no documented warning; logs applied overrides |
| Zigbee2MQTT | settings scoped to `ZIGBEE2MQTT_CONFIG_*`; `ZIGBEE2MQTT_DATA` outside it |
| Spring, Rails, Vector, Kong, Postgres, `CARGO_*`, Dynaconf | [no source found] |
Collision handling with wrapper vars: separate sub-prefix (Z2M, Node-RED) or unprefixed (linuxserver, AppDaemon). No allowlist example found. No tool found that warns-but-continues on unknown prefixed env vars.

### Q3: Docker dirs
| Image | Dir | How app is told |
|---|---|---|
| Home Assistant | `/config` | fixed in image; docs only mention `TZ` |
| AppDaemon | `/conf` (VOLUME+WORKDIR) | fixed; documented env `HA_URL`, `TOKEN`, `DASH_URL` |
| Node-RED | `/data` | entrypoint `--userDir /data`; env `NODE_RED_*` |
| Zigbee2MQTT | `/app/data` | default relative to WORKDIR; `ZIGBEE2MQTT_DATA` override documented |
| linuxserver | `/config` | [path convention not verified]; `PUID`/`PGID`/`TZ` verified |

### Q4: HA add-ons
| Add-on | map | Settings path |
|---|---|---|
| AppDaemon | `addon_config:rw`, `homeassistant_config:rw`, `media:rw`, `share:rw`, `ssl` | `/config` = `/addon_configs/a0d7b954_appdaemon`; options: log_level + package lists; run script `-c /config` |
| Node-RED | same set | options theme/ssl/packages; `/config` |
| ESPHome | `config:rw` | `/config/esphome` |
| Zigbee2MQTT | not retrievable | slug `45df7312_zigbee2mqtt` seen in forums |

## Anti-Patterns
- Relying on `extra='forbid'` alone to catch bad env vars (does not scan `os.environ`; #985).
- Sharing the product's env prefix with entrypoint/runtime vars while also scanning that prefix (breaks Traefik-style strictness; only Z2M's split avoids it).
- Moving a user data dir with no startup message or migration (AppDaemon add-on: empty dir after restore, lost app entries).
- Ignoring unknown keys with no log line (Grafana users resort to reading startup logs).

## Gaps (not confirmed)
Official HA core policy on unknown YAML keys; Spring Boot, Rails, Vector, Kong, Dynaconf unknown-env behavior; linuxserver `/config` page; Z2M and ESPHome add-on `addon_config` status; AppDaemon add-on official migration notes. The fetched HA developer docs now say "app"/`app_config`, so check whether the `addon_config` key name is still accepted by Supervisor before writing hassette's `config.yaml`.
