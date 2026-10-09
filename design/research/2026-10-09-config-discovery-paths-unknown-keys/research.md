---
topic: "Config file discovery, path anchoring, and unknown-key handling"
date: 2026-10-09
status: Draft
---

# Prior Art: Config Discovery, Path Anchoring, and Unknown-Key Handling

## The Problem

Hassette runs in three places: a local project directory, Docker (`/config`, `/data` and `/apps` volumes), and soon a Home Assistant add-on. Three of its settings don't do what their names say:

- `config_dir` doesn't drive file lookup.
- `HASSETTE__APP_DIR` matches no setting and is silently ignored.
- Relative paths in `hassette.toml` resolve against cwd, so they mean different things depending on where Hassette was launched.

Spec 128 (`design/specs/128-config-paths-and-unknown-keys/design.md`) has 11 open decisions. This survey checks whether the ecosystem already has a convention to adopt wholesale.

## How We Do It Today

- **Lookup:** fixed lists in `config/defaults.py`, `[/config, ./, ./config]` for both `hassette.toml` and `.env`. `--config-file`/`--env-file` replace those lists. `config_dir` only creates its directory.
- **Relative paths** resolve against cwd.
- **Unknown keys:**
  - `HassetteConfig` has `extra="allow"`, so unknown top-level TOML keys and every `.env` key land in `model_extra` silently.
  - Unknown `HASSETTE__*` process env vars never reach `model_extra`.
  - Nested groups drop unknown keys.
- **Docker** sets env vars in the Dockerfile. `docker_start.sh` reads three script-only vars that use the settings prefix.

## Patterns Found

### Pattern 1: An explicit config location is exclusive, and the CLI flag beats the env var, which beats discovery
**Used by:**
- Home Assistant (`-c`)
- AppDaemon (`-c`)
- Zigbee2MQTT (`ZIGBEE2MQTT_DATA`)
- Node-RED (`--userDir`)
- uv (`--config-file` "in place of any discovered configuration files")
- Poetry

**How it works:** Long-running services take one explicit directory and read only from it. Dev tools (ruff, uv, mypy, pytest, ESLint) search upward from cwd, then the user's XDG dir, then system locations. When the user names a file or directory explicitly, discovery is skipped. Precedence is CLI > env > discovered files > defaults.

**Strengths:** No surprise layering, and an explicit value means exactly what it says.

**Weaknesses:** Env var names vary by tool (no universal `<TOOL>_CONFIG_DIR`).

**Exception:** pip's `PIP_CONFIG_FILE` is additive and has special cases. It is widely considered confusing.

### Pattern 2: The config location never comes from inside the config file
**Used by:**
- Home Assistant (resolves `-c` in `__main__` before reading YAML)
- AppDaemon (YAML can set `app_dir`, not the config dir)
- Node-RED (the settings file is found by `-s`/`-u`/defaults)

**How it works:** The bootstrap location is resolved before any file is read. No tool documents an error or ignore for a self-referential setting, because none of them offers the key at all [no source found for explicit handling].

### Pattern 3: Relative paths inside a config file anchor on the file's or project's directory, never cwd
**Used by:**
- Docker Compose (project dir = compose file's dir; `--project-directory` overrides it independently)
- tsconfig (also under `extends`)
- MkDocs (`docs_dir` relative to `mkdocs.yml`)
- git `include.path`
- Alacritty `import`
- Zigbee2MQTT
- pytest (config file dir becomes rootdir)

**How it works:**
- Paths written in a file are relative to that file's location.
- Values typed on the CLI are cwd-relative and absolutized once. Home Assistant does `abspath(join(getcwd(), args.config))`.

**Minority:**
- mypy's `mypy_path` and pydantic-settings paths are cwd-relative.
- ruff and ESLint switch to a cwd anchor under `--config`, which users report as confusing.

**Strengths:** A config file means the same thing wherever it's launched from, and it can be moved along with its siblings.

### Pattern 4: Unknown keys in config files are an error, or a warning with a strict opt-in
**Split with no single winner:**
- **Hard error:** ruff, Docker Compose, Traefik, kubectl (`--validate=strict` default)
- **Warning, strict mode opt-in:** pytest (`--strict-config` errors), Cargo (`warning: unused manifest key`, but exempts `package.metadata` as a sanctioned extension point), mypy

**Did-you-mean:**
- Not offered by any config-file tool tested (ruff, pytest, mypy, Cargo, Compose were run locally).
- clap offers it for CLI args only.

### Pattern 5: Prefixed env vars. Either own the whole namespace (and fail strictly), or don't check
- **Traefik** fails on unknown `TRAEFIK_*` vars. This works only because it owns that namespace outright.
- **Grafana** silently ignores unknown `GF_*`.
- **pydantic-settings** ignores unknown prefixed env vars even with `extra='forbid'`. Issue #985 is this exact case, and the maintainer declined it on the grounds that a shared prefix doesn't prove intent. Unknown `.env` entries do get validated.
- **No tool found warns-and-continues** for env vars.
- **Wrapper-script vars live outside the settings namespace:**
  - Zigbee2MQTT splits `ZIGBEE2MQTT_CONFIG_*` (settings) from `ZIGBEE2MQTT_DATA` (runtime dir).
  - linuxserver and AppDaemon images use unprefixed runtime vars (`PUID`, `PGID`, `TZ`).
  - No allowlist precedent found.

### Pattern 6: Docker images bake one fixed path and expect a volume, with no path ENV
- **Home Assistant** `/config`
- **AppDaemon** `/conf`
- **Node-RED** `/data` (its entrypoint passes `--userDir /data`)
- **Zigbee2MQTT** `/app/data`

None sets the app's paths via Dockerfile ENV. The app either defaults to the path or the entrypoint passes a CLI flag. User code (AppDaemon apps, Node-RED flows) lives *inside* the single config/data volume, not in a separate volume.

### Pattern 7: HA add-ons map `addon_config` → `/config`, with user code inside it
- **Mapping:** the AppDaemon and Node-RED add-ons map `addon_config:rw`, so `/config` in the container is `/addon_configs/<slug>` on the host. User config *and* apps live there.
- **Options:** UI options stay small (log level, package lists), read via bashio from `/data/options.json`. The AppDaemon run script hardcodes `-c /config`.
- **Docs check needed:** the current HA developer docs use the newer "app"/`app_config` naming. Verify which mapping key the Supervisor accepts before writing hassette's add-on `config.yaml`.

## Anti-Patterns

- **Additive explicit config** (pip's `PIP_CONFIG_FILE`): users can't predict which file won.
- **An anchor that changes with how the file was found** (ruff/ESLint under `--config`): it confuses users.
- **AppDaemon's move to `addon_config`** had no migration guide. Users lost `apps.yaml` entries. Any hassette layout change should ship with explicit migration steps.

## Relevance to Us

The convention maps onto spec 128 like this:

| Decision | Ledger state | Convention says | Fit |
|---|---|---|---|
| D1 `config_dir` drives lookup | Ratified A | Patterns 1, 6: one explicit config dir is how HA/AppDaemon/Z2M/Node-RED work | Matches |
| D2 explicit is exclusive | Ratified A | Pattern 1: exclusive, CLI > env > discovery | Matches |
| D3 `config_dir` inside the file | Ratified: startup error | Pattern 2: the key isn't offered from the file at all | Matches (an error is the closest a pydantic field gets to "not offered") |
| D4 relative-path anchor | Pending (recommended B, file dir) | Pattern 3: file/project-relative dominates. CLI and env values are cwd-relative, absolutized once | B matches |
| D5 Docker apps dir | Pending (recommended A, Dockerfile ENV) | Pattern 6: no path ENV. A fixed path the app defaults to or the entrypoint passes. User code inside the config volume (Pattern 7) | **Differs.** See recommendation |
| D6 script-only `HASSETTE__` vars | Pending (recommended allowlist) | Pattern 5: no allowlist precedent. Runtime vars live outside the settings namespace (Z2M split, linuxserver) | **Differs.** Rename |
| D7 `HASSETTE__LOG_LEVEL` | Pending (recommended B, flag it) | Pattern 5: the namespace means "settings" | Matches |
| D8/D9 unknown keys: scope and severity | Pending (recommended warn) | Pattern 4: files error (ruff/Compose) or warn with strict opt-in. Pattern 5: env vars are only checked when the tool owns the namespace, and then it errors | **Partly differs.** With D6 renamed, hassette owns `HASSETTE__*` and can error like Traefik |
| D10 apps-dir startup log | Pending | No convention found | Our call |
| D11 did-you-mean | Pending (recommended yes) | No config-file tool does it | Not a convention. Cheap, but optional |

## Recommendation

Adopt the **"services" convention** that Home Assistant, AppDaemon, Zigbee2MQTT and Node-RED share, since hassette is a long-running service that ships the same way they do. One rule set covers almost every decision.

1. **One config dir, located before anything is read.** CLI flag > env var > default (`/config` if present, else the project dir). Explicit is exclusive. It is never settable from the file. (D1–D3, already ratified this way.)
2. **Paths in a file are relative to that file.** Paths from CLI and env are cwd-relative and absolutized once. (D4 → B.)
3. **The settings namespace is owned outright.** `HASSETTE__*` means "a setting", full stop:
   - Script-only Docker vars move out of it (D6 → rename, e.g. a `HASSETTE_DOCKER_*` or unprefixed namespace; the exact name is a small sub-decision).
   - `HASSETTE__LOG_LEVEL` is flagged (D7 → B).
4. **Unknown keys are errors.** This applies to TOML keys and owned-namespace env vars, Traefik/ruff/Compose style, which fits the pre-1.0 "error now rather than later" principle. A warn-with-strict-opt-in mode (pytest/Cargo) is the softer, equally common alternative. Either way, detection is our own walk of `os.environ`, `.env` and TOML (pydantic-settings won't do it, issue #985). App definitions under `apps.*` are the sanctioned extension point, like Cargo's `package.metadata`. (D8/D9 re-open as "error vs warn".)
5. **Docker: user code inside the config volume.** This is the strongest divergence from today. Every comparable image and add-on keeps user code in its single config/data volume, and the hassette add-on will too (`/config/apps` under `addon_config`). Combined with rule 2, `apps.directory` could default to `apps` relative to the config dir. That would make Docker, the add-on and local `./config` layouts all work with no env var, and would retire the separate `/apps` volume and the Dockerfile ENV entirely. It is a bigger, breaking change to the Docker layout, so D5 should be re-asked with this option on the table, plus migration notes (the AppDaemon anti-pattern).

**Gaps:**
- HA core's official policy on unknown YAML keys is unconfirmed.
- The Zigbee2MQTT add-on layout is unconfirmed.
- Whether AppDaemon resolves a relative `app_dir` against its config dir is unconfirmed.
- linuxserver's `/config` convention was only partially verified.

## Sources

URLs were not live-verified. Full per-source notes are in `web-research-paths.md` and `web-research-keys-docker.md` in this directory.

### Reference implementations
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/__main__.py — HA resolves `-c` config dir before reading YAML
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/config.py — HA config loading
- https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/Dockerfile — AppDaemon image, fixed `/conf`
- https://raw.githubusercontent.com/Koenkk/zigbee2mqtt/master/docker/Dockerfile — Z2M image
- https://raw.githubusercontent.com/Koenkk/zigbee2mqtt/master/lib/util/data.ts — Z2M data-dir resolution (`ZIGBEE2MQTT_DATA`)
- https://raw.githubusercontent.com/node-red/node-red-docker/master/docker-custom/scripts/entrypoint.sh — Node-RED passes `--userDir /data`
- https://raw.githubusercontent.com/hassio-addons/addon-appdaemon/main/appdaemon/config.yaml — AppDaemon add-on maps
- https://raw.githubusercontent.com/hassio-addons/addon-appdaemon/main/appdaemon/rootfs/etc/s6-overlay/s6-rc.d/appdaemon/run — hardcoded `-c /config`
- https://raw.githubusercontent.com/hassio-addons/addon-node-red/main/node-red/config.yaml — Node-RED add-on maps
- https://raw.githubusercontent.com/esphome/home-assistant-addon/main/esphome/config.yaml — ESPHome add-on (still `config:rw`)
- https://github.com/pydantic/pydantic-settings/issues/985 — unknown prefixed env vars not detected; declined
- https://github.com/pydantic/pydantic-settings/issues/215, https://github.com/pydantic/pydantic-settings/issues/437, https://github.com/pydantic/pydantic/issues/12242 — related pydantic-settings extras behavior

### Blog posts & writeups
- https://developers.home-assistant.io/blog/2023/11/06/public-addon-config — introduction of `addon_config`
- https://community.home-assistant.io/t/appdaemon-add-on-config-files/965196 — AppDaemon `addon_config` migration pain
- https://internals.rust-lang.org/t/cargo-manifest-and-unused-manifest-key-allow-other-tools-to-extend-the-manifest/16333 — Cargo unused-key warning and `package.metadata`
- https://community.grafana.com/t/environment-variables-are-not-working-it-seems-im-not-alone/38631 — Grafana silently ignores unknown `GF_*`
- https://community.traefik.io/t/docker-compose-static-config-issue/10987 — Traefik strict static config
- https://community.home-assistant.io/t/extra-keys-error/101249 — HA "extra keys not allowed"

### Documentation & standards
- http://specifications.freedesktop.org/basedir/latest/ — XDG Base Directory spec
- https://docs.docker.com/reference/compose-file/, https://docs.docker.com/compose/how-tos/project-name/ — Compose project dir and relative paths
- https://docs.astral.sh/uv/concepts/configuration-files/ — uv exclusive `--config-file`
- https://docs.astral.sh/ruff/configuration/ — ruff discovery and unknown-key errors
- https://docs.pytest.org/en/stable/reference/customize.html — rootdir/inifile, `--strict-config`
- https://mypy.readthedocs.io/en/stable/config_file.html — mypy config
- https://pip.pypa.io/en/stable/topics/configuration/ — pip additive config
- https://python-poetry.org/docs/configuration/ — Poetry precedence
- https://eslint.org/docs/latest/use/configure/configuration-files — ESLint
- https://www.typescriptlang.org/tsconfig/ — tsconfig file-relative paths
- https://www.mkdocs.org/user-guide/configuration/ — MkDocs `docs_dir`
- https://git-scm.com/docs/git-config — git `include.path`
- https://doc.rust-lang.org/cargo/reference/manifest.html — Cargo manifest
- https://doc.traefik.io/traefik/getting-started/configuration-overview/ — Traefik env/static config
- https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/ — Grafana `GF_*`
- https://kubernetes.io/docs/reference/kubectl/generated/kubectl_apply/ — kubectl validate
- https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ — pydantic-settings
- https://platformdirs.readthedocs.io/en/latest/ — platformdirs
- https://appdaemon.readthedocs.io/en/latest/CONFIGURE.html, https://appdaemon.readthedocs.io/en/latest/DOCKER_TUTORIAL.html — AppDaemon config and Docker
- https://nodered.org/docs/getting-started/docker, https://nodered.org/docs/user-guide/runtime/configuration — Node-RED
- https://www.zigbee2mqtt.io/guide/configuration/, https://www.zigbee2mqtt.io/guide/installation/02_docker.html — Zigbee2MQTT
- https://www.home-assistant.io/docs/tools/hass — HA `hass -c`
- https://developers.home-assistant.io/docs/add-ons/configuration/ — add-on `map` options
- https://docs.linuxserver.io/general/understanding-puid-and-pgid/ — linuxserver runtime vars
- https://www.dynaconf.com/configuration/ — Dynaconf
