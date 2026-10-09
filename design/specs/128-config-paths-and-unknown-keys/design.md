# Design: Config paths that do what they say, and errors for settings that match nothing

**Date:** 2026-10-09
**Status:** ratified
**Mode:** sketch

## Summary

Three related bugs, one PR (closes #1850, #1854, #2626; the last blocker for the HA add-on, #71). Each is a setting that silently doesn't do what its name says. The PR also closes #985 (D12): the fixes below turn silent misconfiguration into startup errors, and without #985 every one of those errors becomes a Docker restart loop.

- **#1850:** The Docker image sets `HASSETTE__APP_DIR=/apps` (`Dockerfile:109`), which matches no settings field. `AppsConfig.directory` defaults to `Path.cwd() / "apps"` (`src/hassette/config/models.py:581`), and the image's `WORKDIR` (see Assumed) makes the real default `/app/apps`. Users who follow the Docker quick start see "Found 0 active apps" and nothing else. `docs/pages/getting-started/docker/troubleshooting.md:35` wrongly says apps are read from `/apps`.
- **#1854:** Nothing reports a `HASSETTE__*` env var or a `hassette.toml` key that matches no setting. That is how the `APP_DIR` bug went unnoticed. The Docker script's own vars use the settings prefix (what `docker_start.sh` reads is in Assumed; renamed in D6), and the Docker docs tell users to set them.
- **#2626:** `HassetteConfig.config_dir` (`src/hassette/config/config.py:164`) is only used to create the directory (`config.py:330-335`). File lookup comes from fixed lists in `src/hassette/config/defaults.py:11-12`. `docs/pages/operating/upgrading.md:64-72` tells users to set `config_dir` inside `hassette.toml`, which can't work.

The work touches these areas:

- config loading: `config/config.py`, `config/defaults.py`, `config/helpers.py`, `config/classes.py`, `app/app_config.py`, plus a new typed `ConfigError` in the exceptions module
- the CLI launcher: `cli/__init__.py` and `cli/commands/run.py` (`cmd_run` constructs `HassetteConfig` outside the `try`, see D12; exit codes are in D12's table; new `--check` flag)
- startup logging: `core/core.py` `startup_tasks`
- the reload path: `core/app_lifecycle_service.py` (`refresh_config`) and `core/app_change_detector.py`
- the file watcher's watched files (`get_watchable_files`, built from `env_files`/`toml_files`) and the web config view
- the hermetic test config: `testing/config.py`
- the Docker image, `scripts/docker_start.sh`, and the docs that describe config locations and Docker setup
- schema regeneration through `scripts/export_schemas.py`

D13 and D14 are structural changes to how a config is constructed and how its locations are resolved, not just fixes for the three bugs above.

Files that must change with this design:

- Docs that state config locations or the Docker app path, all of which must match the result:
  - `docs/pages/core-concepts/configuration/snippets/file_discovery.md`
  - `docs/pages/core-concepts/configuration/index.md:32`
  - `docs/pages/operating/upgrading.md:64-72`
  - `docs/pages/getting-started/docker/index.md` (including line 28)
  - `docs/pages/getting-started/docker/troubleshooting.md:35` and `:55-74`
  - `docs/pages/getting-started/docker/dependencies.md:16,22,37,62-67,88` (renamed Docker vars, `/apps` project dir)
- Callers that encode the old names, layout or path semantics:
  - `hassette.schema.json:305,407`: "relative to current working directory" descriptions, regenerated per D4
  - `tests/test_docker_integration.py:61,68,165,283`: old Docker var names and the `/apps` mount
  - `tests/test_docker_integration.py:246,351`: assert a non-zero exit on script paths that now halt (D12)
  - `scripts/docker/ha-demo.yml:52` and `tests/test_docker_integration.py:47`: set `HASSETTE__APPS__DIRECTORY` explicitly
  - `tests/support/web_mocks.py:136,176`, `tests/support/web_response_helpers.py:135`, `frontend/src/test/config-fixtures.ts:24,100`: `config_dir` fixture values shown by the web config view

Out of scope:

- the uid-1000 container user vs host bind-mount ownership question (#1850 part d)
- the add-on itself (#71)
- unknown keys inside `[hassette.apps.<key>]` manifest tables: they stay opaque here because `AppManifest`'s documented extras-to-`config` path would need retiring first. Tracked in #2633.

## Decisions

### D1: What does `config_dir` mean?

**Deciding factor:** `config_dir` does what its name says, without breaking existing setups.

| | A: `config_dir` drives where `hassette.toml` and `.env` are looked up | B: Remove `config_dir` |
|---|---|---|
| Fixes the #2626 repro (toml outside cwd) | Yes | No. Users must pass `--config-file`/`--env-file`, and need both flags for both files |
| Docker | `HASSETTE__CONFIG_DIR=/config` (already in the image) becomes the real mechanism instead of a coincidence of list order | Image must drop the env var. `docker_start.sh` still reads it to find `requirements.txt` |
| Add-on (#71, `/config` via `addon_config`) | The add-on sets `HASSETTE__CONFIG_DIR=/config`, same as the image | Relies on the hard-coded `/config` entry |
| Breakage | None for current working setups: `/config` stays the default when it exists | Anyone setting `HASSETTE__CONFIG_DIR` gets an unknown-key error (D9), including every existing compose file that copied the image's env |
| Surface area | Adds a `--config-dir` CLI flag, which can't come from the file | Removes a field and the platformdirs config default |

**Recommendation:** A. It makes a documented, image-baked setting work, and it doesn't make every existing Docker setup warn.
**Pick B instead if** you'd rather keep a single lookup mechanism (the explicit file flags) and accept the compose churn.
**Reversibility:** hard (once users rely on `config_dir` lookup, removing it is a breaking change)
**Ratified:** Chose making `config_dir` drive the `hassette.toml`/`.env` lookup over removing it, so the image-baked `HASSETTE__CONFIG_DIR` setting actually works, accepting a new `--config-dir` CLI flag.

### D2: Where does Hassette look when `config_dir` is or isn't set explicitly?

**Deciding factor:** an explicit `config_dir` is honored exactly, and setups that never set it see no change.

"Explicit" is defined in D14 (resolver inputs). D14's resolver replaces today's case-sensitive env reading in `default_config_dir()` (`config/helpers.py:60-76`). "Unset" means the resolver found no explicit value, so it falls back to `/config` if that exists and otherwise the platformdirs path. In each list below, later files win, as today.

| | A: Explicit → only `config_dir`. Unset → `[default_config_dir(), ./, ./config/]` | B: Always `[config_dir, ./, ./config/]` | C: Always only `config_dir` |
|---|---|---|---|
| #2626 repro | Fixed | Fixed, but a stray `./hassette.toml` in cwd still overrides the explicit dir | Fixed |
| Docker (image sets `CONFIG_DIR=/config`, cwd `/app`) | Only `/config`. Same effective behavior as today, since `/app` holds no config | Same as today | Same as A |
| Local, no env var (e.g. hautomate runs `./config/hassette.toml` from the project root) | Unchanged, plus the platformdirs dir now searched first (lowest priority) | Same as A | Breaks: cwd and `./config/` no longer searched |
| Predictability | An explicit setting means exactly that dir | Explicit dir is lowest priority, which is surprising | Simplest rule, but breaks the quick start |

The `--config-file` / `--env-file` flags (list replacement: see Assumed) beat `config_dir` for the file they name.

**Recommendation:** A. An explicit setting means what it says, and the default search only adds the platformdirs location at the lowest priority.
**Pick B instead if** people layer a cwd `hassette.toml` over a shared `config_dir` on purpose. **Pick C instead if** you want one rule and accept breaking cwd-based setups.
**Reversibility:** easy (the lookup list lives in one place)
**Ratified:** Chose an exclusive explicit `config_dir` with the unset default `[default_config_dir(), ./, ./config/]` over an always-additive or always-exclusive list, so an explicit setting means exactly that dir while cwd-based setups keep working, accepting that platformdirs joins the default search at lowest priority.

### D3: What happens when `config_dir` is set inside `hassette.toml` or a `.env` file?

**Deciding factor:** a setting that can't take effect from where it's written says so, instead of half-working.

A `.env` file is found through `config_dir` too, so the same circularity applies to it as to `hassette.toml`.

| | A: Ignore it and log a WARNING naming `HASSETTE__CONFIG_DIR` / `--config-dir` | B: Startup error | C: Accept it silently (today) |
|---|---|---|---|
| `config.config_dir` matches the dir actually used for lookup | Yes | n/a (never starts) | No. The field holds the file's value while lookup used another dir |
| Users following the old `upgrading.md` advice | Keep running and are told the fix | Hassette won't start until they edit the file | Nothing tells them |
| Effect on `ensure_directories` | Creates the dir actually used for lookup | n/a | Creates the file's value, as today |

**Recommendation:** B. Hassette is pre-1.0, so an error now costs less than one added later, and the old advice never worked, so no one has a working setup to protect.
**Pick A instead if** users who followed the old `upgrading.md` advice must keep running.
**Reversibility:** easy
**Ratified:** Chose a startup error (naming `HASSETTE__CONFIG_DIR` / `--config-dir` and the file the key was found in) over ignore-and-warn, because Hassette is pre-1.0 and shouldn't carry compatibility behavior it would only have to turn into an error later, accepting that users who followed the old `upgrading.md` advice must edit their file before Hassette starts.

### D4: What are relative paths in `hassette.toml` relative to?

**Deciding factor:** a relative path written in a config file is relative to that file, the dominant convention among services (prior art: `design/research/2026-10-09-config-discovery-paths-unknown-keys/research.md`). CLI and env values are cwd-relative, absolutized once.

Affected settings: every `Path`-typed field, found from the model's field annotations rather than a hand list. Today that is `apps.directory`, `data_dir`, `database.path`, `cli.token_file` and each app's `app_dir` in `[hassette.apps.<key>]`. A `.env` file is a config file too, so a relative path value in it is relative to the `.env` file's directory (Compose's rule): `HASSETTE__DATA_DIR=data` in `/config/.env` means `/config/data`. Relative paths from the process env and CLI flags resolve against cwd once, at load. File-relative anchoring happens per source, before the `resolve_paths` validator (`config/config.py:320-327`) absolutizes anything against cwd. Today `resolve_paths` covers only `config_dir` and `data_dir`; the loader absolutizes every `Path` field. Schema descriptions that say "relative to current working directory" (`hassette.schema.json`) are regenerated through `scripts/export_schemas.py`.

| | A: The working directory (today) | B: The directory of the file that set them | C: `config_dir` |
|---|---|---|---|
| Config in cwd (`./hassette.toml`, the quick start) | Works | Works (file dir == cwd) | Breaks locally: `config_dir` defaults to platformdirs, not cwd |
| `./config/hassette.toml` with cwd-relative paths (e.g. hautomate's `directory = "src/hautomate"`) | Works | Breaking: must become `"../src/hautomate"` | Breaks |
| Docker, `directory = "apps"` in `/config/hassette.toml` | Resolves to `/app/apps`, an image-internal dir, so always wrong | Resolves to `/config/apps` | Resolves to `/config/apps` |
| Meaning depends on where Hassette was launched | Yes | No | No, but it depends on `config_dir` instead |
| Prior art | Minority (mypy `mypy_path`, pydantic-settings) | Dominant (Compose, tsconfig, MkDocs, git `include.path`, pytest rootdir, Zigbee2MQTT) | Close to B for services with one config dir |
| Code change | Docs only | Path values resolved per file in `HassetteTomlConfigSettingsSource` before files and `.local` overlays merge (each overlay against its own dir) | Resolve after load |

**Recommendation:** B, the dominant convention. A path in a config file means the same thing wherever Hassette was launched from.
**Pick A instead if** a breaking change to `./config/hassette.toml` layouts isn't acceptable. **Pick C instead if** every relative path should share one anchor.
**Reversibility:** hard (switching anchors later breaks whichever layout depended on the old one)
**Ratified:** Chose file-relative over cwd-relative and `config_dir`-relative, following the dominant convention (Compose, tsconfig, MkDocs, pytest, Zigbee2MQTT) so a config file's paths don't depend on where Hassette was launched, accepting a breaking change for `./config/hassette.toml` layouts with cwd-relative paths that needs a `BREAKING CHANGE:` note and migration guidance.

### D5: Where do user apps live in Docker, and what is `apps.directory`'s default?

**Deciding factor:** user code lives inside the config volume, so one layout works in Docker, the add-on and locally with no env var (prior art: `design/research/2026-10-09-config-discovery-paths-unknown-keys/research.md`).

Comparable images (Home Assistant `/config`, AppDaemon `/conf`, Node-RED `/data`, Zigbee2MQTT `/app/data`) and the AppDaemon and Node-RED add-ons (`addon_config` → `/config`) keep user code inside the one config volume, and none sets paths through Dockerfile `ENV`. "Config home" is defined in D14: the explicit `config_dir`, else cwd. D14's resolver is also the source of `apps.directory`'s default `<config home>/apps`: the nested `AppsConfig` `default_factory` (`models.py:581`) can't see the parent's location, so the loader fills the field from the resolver when it is unset.

| | A: Keep the `/apps` volume. `Dockerfile` sets `HASSETTE__APPS__DIRECTORY=/apps` | B: Apps live in the config home. `apps.directory` defaults to `<config home>/apps`. The image drops the `/apps` volume (removing `HASSETTE__APP_DIR` is D6) |
|---|---|---|
| Fixes #1850 | Yes | Yes |
| Docker quick start | `./apps:/apps` mount plus a baked env var | `./config:/config` only. Apps go in `./config/apps` |
| Add-on (`/config` mapped) | Must set its own env var | Works with only `HASSETTE__CONFIG_DIR=/config` set (D1), no apps setting |
| Local `./hassette.toml` | `./apps`, unchanged | `./apps`, unchanged |
| Local `./config/hassette.toml` with no `directory` set | `./apps`, unchanged | `./apps`, unchanged (no explicit `config_dir` → config home is cwd) |
| Existing Docker users (`./apps:/apps`) | No change | Breaking: move apps under the config mount, or set `apps.directory`. Needs the D11 migration notes (AppDaemon's `addon_config` move shipped without them and lost users' `apps.yaml` entries) |
| `docker_start.sh` | The script's apps and project dirs default to `/apps` | Paths come from Hassette, with project-dir walk-up (D14) |
| Prior art | No comparable image sets path `ENV` | Matches HA, AppDaemon, Node-RED, Zigbee2MQTT and the add-ons |

**Recommendation:** B. It is the convention, and it makes the add-on (#71) need no special apps setting. The cost is a breaking Docker layout change, shipped with the D11 migration notes.
**Pick A instead if** you don't want to break existing Docker compose files in this PR.
**Reversibility:** hard (moving the apps location again is another breaking change for Docker users)
**Ratified:** Chose apps inside the config home (`apps.directory` defaults to `<config home>/apps`, the image drops the `/apps` volume) over keeping the `/apps` volume, adopting the HA/AppDaemon/Node-RED/Z2M convention so Docker, the add-on and local layouts work without an env var, accepting a breaking change to the Docker layout, shipped with the D11 migration notes and D14's `/apps` migration hint.

### D6: How are `docker_start.sh`'s script-only vars kept out of the settings namespace?

**Deciding factor:** `HASSETTE__*` means "a setting", with no exceptions (prior art: `design/research/2026-10-09-config-discovery-paths-unknown-keys/research.md`).

`HASSETTE__APP_DIR` is dropped from the `Dockerfile` and from `docker_start.sh`. Comparable images keep runtime and wrapper vars outside the settings prefix: Zigbee2MQTT splits `ZIGBEE2MQTT_CONFIG_*` from `ZIGBEE2MQTT_DATA`, and linuxserver images use unprefixed `PUID`/`TZ`. No allowlist precedent was found.

| | A: Allowlist in the config package | B: Rename to a non-settings prefix, no fallback |
|---|---|---|
| Meaning of `HASSETTE__` | "a setting, or one of N named exceptions" | "always a setting" |
| Users still setting the old names | Work unchanged | Old names are still in the `HASSETTE__` namespace, so the `hassette run --check` the entrypoint runs before installing (D14) fails on them, and the container halts (D12) before running with defaults. The renames are listed in the D11 migration notes |
| Docs and test churn | None | Docker docs, snippets, `tests/test_docker_integration.py` |
| Prior art | None found | Zigbee2MQTT, linuxserver |

The three script-only vars are renamed `HASSETTE__INSTALL_DEPS` → `HASSETTE_DOCKER_INSTALL_DEPS`, `HASSETTE__PROJECT_DIR` → `HASSETTE_DOCKER_PROJECT_DIR`, `HASSETTE__PRUNE_UV_CACHE` → `HASSETTE_DOCKER_PRUNE_UV_CACHE`. The new names use a single-underscore prefix with a `DOCKER` segment. These sit outside the double-underscore settings namespace and name the layer that reads them. Existing single-underscore aliases (`HASSETTE_CONFIG_DIR`, `HASSETTE_DATA_DIR`, `HASSETTE_LOG_LEVEL` in `config/helpers.py`) are untouched.

**Recommendation:** B, because `HASSETTE__` should always mean a setting.
**Pick A instead if** compose files must keep working unchanged.
**Reversibility:** easy
**Ratified:** Chose renaming to `HASSETTE_DOCKER_*` with no fallback over an allowlist, following the Zigbee2MQTT/linuxserver practice of keeping wrapper vars outside the settings namespace, accepting a breaking change for compose files that set the old names (surfaced by D8/D9's check and the Docker docs).

### D7: What happens to `HASSETTE__LOG_LEVEL`?

**Deciding factor:** an env var in the settings namespace is a setting or gets flagged (same reasoning as D6; prior art: `design/research/2026-10-09-config-discovery-paths-unknown-keys/research.md`).

`helpers.get_log_level()` (`config/helpers.py:114-116`) reads `HASSETTE__LOG_LEVEL`, then `HASSETTE_LOG_LEVEL`, then `LOG_LEVEL`. It feeds only pre-config bootstrap logging (`__main__.py:7`, `get_dev_mode`). The real setting is `HASSETTE__LOGGING__LOG_LEVEL`.

| | A: Read `HASSETTE__LOGGING__LOG_LEVEL` first and keep `HASSETTE__LOG_LEVEL` as an exception | B: Read `HASSETTE__LOGGING__LOG_LEVEL` instead. `HASSETTE__LOG_LEVEL` is flagged by the unknown-key check |
|---|---|---|
| Bootstrap logging matches the configured level | Yes | Yes |
| `HASSETTE__` means "a setting" | No | Yes |
| `HASSETTE_LOG_LEVEL` / `LOG_LEVEL` | Unchanged | Unchanged |

**Recommendation:** B, because `HASSETTE__` should always mean a setting.
**Pick A instead if** setups depend on `HASSETTE__LOG_LEVEL` for early output.
**Reversibility:** easy
**Ratified:** Chose reading `HASSETTE__LOGGING__LOG_LEVEL` and flagging `HASSETTE__LOG_LEVEL` over keeping it as an exception, so the settings prefix always means "a setting", accepting that users of the old name lose its effect on the first few bootstrap log lines.

### D8: What does the unknown-key check inspect?

**Deciding factor:** catches the typos that hide bugs (top-level and nested, env and TOML) with no false positives on documented usage. Prior art confirms we have to do this scan ourselves: pydantic-settings ignores unknown prefixed env vars even with `extra='forbid'`, and declined to change that (pydantic-settings#985).

Today's behavior of unknown keys in each source is in the first Assumed bullet (probe results).

| | A: Walk the raw sources the config actually read against the field tree | B: Report `model_extra` (top level only) | C: `extra="forbid"` on the top level and the nested groups |
|---|---|---|---|
| `HASSETTE__APP_DIR` in the process env (the #1850 bug) | Caught | Missed | Missed (the env source drops it before validation) |
| Nested typos (`[hassette.apps] directry`, `HASSETTE__APPS__DIRECTRY`) | Caught | Missed | TOML caught, env missed |
| `.env` keys for apps without the `HASSETTE__` prefix | Ignored | Flagged (false positive) | Rejected |
| App definitions (`[hassette.apps.<key>]` tables, `HASSETTE__APPS__<KEY>__CONFIG__...`) | Opaque, not checked (Hassette's equivalent of Cargo's `package.metadata`) | n/a | Needs special-casing |
| Hermetic test config (init kwargs only) | Nothing to scan | Same | Already `forbid` |

Under A:

- **Sources:** the raw keys each settings source recorded while building the config (D13). These are the startup process-env snapshot (`HASSETTE__` keys only), `HASSETTE__` keys in the `.env` files actually loaded, and the keys of the TOML files actually loaded, after the `[hassette]` hoist and `.local` overlays. Each key is reported once, with its source.
- **Known names:** field names and their aliases, recursing into nested groups.
- **Opaque app definitions:** under `apps`, any table- or dict-valued key, and any `HASSETTE__APPS__<KEY>__…` with a further segment. A JSON-dict-valued `HASSETTE__APPS__<KEY>` env var is opaque too (it is an app definition); only a scalar-valued `HASSETTE__APPS__<KEY>` is flagged.
- **Foreign top-level tables:** `hassette.toml` belongs to Hassette. An unknown top-level key or table (e.g. another tool's `[tool.x]`) is an unknown key like any other.
- **Parsing rules:**
  - Names are compared case-insensitively, including a lowercase `hassette__` in `.env`.
  - Validation aliases (e.g. `token`'s `ha_token`, `home_assistant_token`) are matched unprefixed, as pydantic-settings matches them, so `HASSETTE__HA_TOKEN` is not a known name.
  - A JSON-valued env var (e.g. `HASSETTE__APPS='{...}'`) is one key.
  - The known-name set is derived from pydantic-settings' own per-field env-name computation, not re-implemented.
  - Tests pin each rule, plus `HASSETTE__APPS__<KEY>` (flagged) vs `HASSETTE__APPS__<KEY>__…` (opaque).
- **The `HASSETTE__` prefix is reserved for settings, with no escape hatch:** an `AppConfig` subclass whose `env_prefix` starts with `hassette__` has its env vars flagged, and the fix is renaming the app's prefix. The unknown-key error says the prefix is reserved for Hassette settings. No real app in the corpus uses it (hautomate uses `CAR_STATUS_`, `CAR_CLIMATE_`, `OTF_`).

**Recommendation:** A. It is the only option that catches the #1850 bug and nested typos without flagging app env vars.
**Pick B instead if** a minimal change matters more than catching env vars, though B fails #1854's own acceptance criteria. **Pick C instead if** you only care about TOML typos.
**Reversibility:** easy
**Ratified:** Chose walking the raw sources (process env `HASSETTE__` keys, loaded `.env` and TOML files) against the field tree over `model_extra` or `extra="forbid"`, to catch process-env and nested typos without flagging app env vars, accepting a hand-written scan that must mirror pydantic-settings' parsing rules, and that an `AppConfig` env prefix starting with `hassette__` is an error with no escape hatch.

### D9: What happens when the check finds unknown keys?

**Deciding factor:** unknown keys are errors, matching ruff, Docker Compose, Traefik and kubectl (prior art: `design/research/2026-10-09-config-discovery-paths-unknown-keys/research.md`), plus the pre-1.0 principle from D3. Traefik is the precedent for erroring on an owned env prefix, which D6/D7 make `HASSETTE__` into.

The prior art splits on this. ruff, Compose, Traefik and kubectl error; pytest, Cargo and mypy warn, with a strict opt-in (pytest `--strict-config`).

| | A: Error | B: Warning | C: Warning by default, error with a strict setting |
|---|---|---|---|
| `hassette run` with a typo | Fails to start, listing every unknown key with its source | Starts, logs one WARNING for env vars and one for TOML keys | B by default |
| Config reload (file watcher) introducing a typo | Reload rejected and logged as an ERROR. The running config stays in place (mechanism: D13) | Reload applied, WARNING logged | B by default |
| CLI client commands (`hassette status`, `log`, …) | Not checked (D13 builds them in `client` mode) | Same | Same |
| Pre-1.0 principle (D3: error now, not later) | Matches | Defers the error decision | Adds a setting to carry forward |
| Prior art | ruff, Compose, Traefik, kubectl | Cargo (unused manifest key), mypy | pytest, Cargo/mypy-style |

The check runs inside each config build for `hassette run` (startup and every reload), as D13 places it. When nothing is unknown, there is no output at all.

**Recommendation:** A. It is the convention for a tool that owns its namespace, and it matches D3's pre-1.0 principle.
**Pick B instead if** a typo should never stop automations from running. **Pick C instead if** CI or test setups should be strict while home installs stay lenient.
**Reversibility:** easy (relaxing an error to a warning later is non-breaking)
**Ratified:** Chose an error over a warning or a strict opt-in, following the ruff/Compose/Traefik practice for an owned namespace and D3's pre-1.0 principle, accepting that a typo stops `hassette run` from starting and that a reload introducing one is rejected (the running config stays, an ERROR is logged).

### D10: What does startup log about the apps directory?

**Deciding factor:** a wrong apps directory can be diagnosed from the logs alone. No convention was found, so this is Hassette's call.

| | A: INFO `Apps directory: <resolved path>` every startup, plus a WARNING if the directory doesn't exist | B: A, plus a WARNING when the directory exists but no apps were found or configured | C: INFO line only |
|---|---|---|---|
| Directory missing (the #1850 symptom) | Warns, naming the path | Warns | INFO only |
| Wrong subdirectory (exists, holds no apps) | INFO only | Warns | INFO only |
| Fresh install with an intentionally empty apps dir | Quiet | One warning | Quiet |

The WARNING fires when the resolved apps directory does not exist, or when it exists and the final manifest set (configured plus autodetected) is empty.

**Recommendation:** B. It covers both ways the directory can be wrong, and an empty app set is rare enough that one warning is fine.
**Pick A instead if** empty-on-purpose deployments are common.
**Reversibility:** easy
**Ratified:** Chose an INFO line with the resolved path plus a WARNING when the directory is missing or holds no apps over the narrower options, so both ways the directory can be wrong show up in the logs, accepting one warning on intentionally empty installs.

### D11: Do unknown-key messages suggest the likely intended name?

**Deciding factor:** the message names the fix, not just the problem.

None of the config-file tools tested offers this (clap does for CLI arguments only), so it is optional polish rather than convention. It costs a `difflib.get_close_matches` over the dotted names D8 already walks.

**Recommendation:**

- Yes: each unknown key gets a "did you mean" suggestion when a close match exists. This is for typos, e.g. `apps.directry` suggests `apps.directory`, and `HASSETTE__APPS__DIRECTRY` suggests `HASSETTE__APPS__DIRECTORY`.
- Keys with no close match get no suggestion.
- Suggestions come only from real setting names.
- Retired names (renames this PR makes, e.g. `HASSETTE__APP_DIR`, `HASSETTE__LOG_LEVEL`, the old Docker vars) are not typos and get no special mapping. Fuzzy matching can suggest the wrong setting for them (`HASSETTE__APP_DIR` scores closest to `HASSETTE__DATA_DIR`), which is accepted.
- Every unknown-key error ends with a link to the docs-site configuration reference page: `https://hassette.readthedocs.io/` plus `core-concepts/configuration/` (the `site_url` in `mkdocs.yml` plus the page path).
- The migration section in `docs/pages/operating/upgrading.md` is the single list of retired items and their replacements. It must cover `HASSETTE__APP_DIR`, `HASSETTE__LOG_LEVEL`, D6's three renamed Docker vars, `config_dir` set inside a file (D3), the `/apps` volume (D5), file-relative paths (D4) and unknown keys becoming errors (D9). The PR's `BREAKING CHANGE:` footer summarizes what breaks and points to that section without repeating each name. There is no retired-name table in code, so nothing needs upkeep as names change.

**Pick no suggestions instead if** you want the smallest message and code.
**Reversibility:** easy
**Ratified:** Chose did-you-mean suggestions for typos, drawn from real setting names, plus a config-reference link in every unknown-key error, over listing keys only or a retired-name table, so the D9 error names the fix without rename upkeep in code, accepting that a retired name may get an unhelpful suggestion.

### D12: How does the Docker image avoid a restart loop on unrecoverable startup errors? (folds in #985)

**Deciding factor:** no hot loop and no repeated expensive work, while keeping Docker's self-healing and a simple entrypoint.

Under `restart: unless-stopped`, Docker restarts a container that exits non-zero, with exponential backoff capped at 60 seconds. It has no "don't restart me" signal (moby/moby#49397). D3 and D9 add new deterministic startup errors, and #985's four `exit 1` paths in `docker_start.sh` (venv check, uv timeout, dependency conflict, missing `fd`) already loop. A dependency conflict can re-run up to 300 seconds of `uv` on every attempt. Prior art is in `design/research/2026-06-07-docker-restart-loop-prevention/research.md`.

No child-process wrapper is needed: the entrypoint runs `hassette run --check` (D14), which applies the D3 and D8/D9 checks, *before* `exec hassette run`, so config errors reach the script as that command's exit status. After `exec`, the main remaining deterministic failure is the app precheck (it imports user code).

| | A: Bounded halt in the script: banner, idle N seconds (default 300), then exit so Docker retries. `exec hassette run` stays | B: Indefinite halt in the script, plus a marker file and `HEALTHCHECK` | C: No halt: print the banner and exit, relying on Docker's backoff |
|---|---|---|---|
| Hot loop and log noise | One attempt and banner per N seconds | One banner total | One per ≤60 seconds |
| Repeated dependency installs on a conflict | Once per N seconds | Never | Once per ≤60 seconds |
| Self-heals (mount not ready after an outage, network-dependent install) | Yes, within N seconds | No: needs a manual `docker restart` | Yes |
| Entrypoint complexity | Interruptible idle plus trap; no child wrapper | Same, plus marker and healthcheck | Unchanged |
| Opt-out for CI and orchestrators | `HASSETTE_DOCKER_RETRY_DELAY=0` exits immediately | Needs its own setting | Inherent |

Behavior the build must pin:

- The script halts on (a) any non-zero exit from `hassette run --check` (D14), which covers config errors, and (b) #985's four unrecoverable paths.
- A halt prints the banner once, runs the exit-trap cleanup, idles for `HASSETTE_DOCKER_RETRY_DELAY` seconds (default 300), then exits with 78 only when `--check` itself exited 78, otherwise with `--check`'s own non-zero code. #985's four script paths exit 1 after the idle.
- The idle is interruptible: `docker stop` during a halt returns promptly, not after the stop timeout.
- `HASSETTE_DOCKER_RETRY_DELAY=0` exits immediately.
- The banner says what failed and the remedy for that failure:
  - a mounted-file problem: edit the file, then `docker restart`
  - an environment problem: edit the compose file, then `docker compose up -d` to recreate the container, since `docker restart` keeps the old environment
- `hassette run` exits 78 (`EX_CONFIG`) for deterministic startup errors that reach it, chiefly app precheck failure. Exit 78 is a contract for systemd (`RestartPreventExitStatus=78`) and the add-on's s6 `finish` script. Under Docker these fall back to Docker's own backoff: an app-precheck failure after `exec` still retries on that backoff. This is accepted, because `--check` catches config errors first and precheck failures are rare.
- Exit codes. This table is the single home for exit codes. The config rows apply to both `hassette run` and `hassette run --check`; the manifest-validation, app-precheck and port/`FatalError` rows apply to `hassette run` only (`--check` never validates manifests, imports user code or starts Hassette):

  | Cause | Applies to | Exit |
  |---|---|---|
  | Config `ValidationError` during construction | both | 78 |
  | Unknown key (D9) | both | 78 |
  | `config_dir` set inside a file (D3) | both | 78 |
  | Manifest-validation error (reserved or unsafe app keys from `set_validated_app_manifests`) raising `ConfigError` | `run` only | 78 |
  | App precheck failure (`AppPrecheckFailedError`, when startup isn't allowed to continue) | `run` only | 78 |
  | Port in use, `FatalError` | `run` only | 1 |
  | Anything unexpected | both | 1 |

- D3, D9, wrapped construction `ValidationError`s and manifest-validation errors (today `set_validated_app_manifests` raises `ValueError`, `config.py` ~439-451) raise one typed `ConfigError`. `cmd_run` (`src/hassette/cli/commands/run.py`, whose `HassetteConfig(...)` construction currently sits outside the `try`) maps `ConfigError` and `AppPrecheckFailedError` to 78, with construction inside the mapped region. A test pins that `hassette run` with an unknown key exits 78.

**Recommendation:** A. It ends the hot loop and the repeated installs, keeps the self-healing Docker gives today, and needs no child-process wrapper.
**Pick B instead if** a broken setup should sit idle until a human acts. **Pick C instead if** a ≤60-second retry cadence is acceptable and the entrypoint should stay unchanged.
**Reversibility:** easy
**Ratified:** Chose a bounded halt in the script (default 300 seconds, `HASSETTE_DOCKER_RETRY_DELAY` to change it, 0 to exit immediately) with `exec hassette run` kept, over an indefinite halt or plain exit, to end the hot loop and repeated installs while keeping Docker's self-healing, accepting a retry every N seconds while a setup stays broken.

### D13: How is a config built and reloaded?

**Deciding factor:** a failed load never touches the running config, and every check sees exactly the inputs the config was built from.

Today these fail together, and all share one root cause:

- **In-place reload:** `reload()` re-runs `__init__` on the live object (`config/config.py:349-358`). If anything raises afterwards, the live config is left with empty `apps.manifests`. `refresh_config` logs the error and pushes the empty set (`core/app_lifecycle_service.py:1278-1284`), and the change detector stops every app (`core/app_change_detector.py:185`). This is reachable today through `set_validated_app_manifests`' reserved/unsafe-key errors.
- **Stale `.env` values:** `startup_tasks` copies `.env` into `os.environ` and never unsets it (`core/core.py:174-178`). The env source outranks the dotenv source, so an edited `.env` value is ignored on reload.
- **Scan inputs:** a scan reading `os.environ` would report `.env` keys twice, and would keep flagging a fixed `.env` typo.

| | A: One loader builds a candidate from a startup snapshot of the process env plus `.env`/TOML read fresh. Sources record the raw keys they consumed. D3, D8/D9 and manifest validation run on those records inside the build. Reload swaps the candidate in only on success | B: Candidate build and swap on reload, but the scan stays a separate pass over a process-env snapshot that re-reads the files |
|---|---|---|
| Failed reload leaves the live config and apps untouched | Yes | Yes |
| `.env` typos reported once; a fixed one clears on reload | Yes | Yes |
| Edited `.env` values take effect on reload | Yes: the env source reads the snapshot, not the mutated `os.environ` | No |
| Scanned inputs equal the config's inputs | Yes, by construction | Re-derived, so it can drift |
| Size | Custom env/dotenv sources that record keys (the TOML source is already custom, `config/classes.py`) | Smaller |

Behavior the build must pin:

- **The snapshot:** a copy of the whole process environment, taken once at CLI entry before `startup_tasks` loads any `.env` into `os.environ`. It therefore covers every variable the settings sources read: `HASSETTE__*`, the single-underscore aliases (`HASSETTE_CONFIG_DIR`, `HASSETTE_DATA_DIR`, `HASSETTE_LOG_LEVEL`) and the unprefixed validation aliases (`HA_TOKEN`, `HOME_ASSISTANT_TOKEN`, `LOG_LEVEL`). Every build, including reloads, reads process env from it.
- **Reload inputs:** a reload builds the candidate with the same init kwargs as the original build, replaying `hassette run` flags such as `--app`, as `reload()` does today (`src/hassette/config/config.py:349-358`).
- **Scope of freshness:** `startup_tasks` keeps loading `.env` files into `os.environ` (for `import_dot_env_files` users). D13's freshness guarantee covers the settings sources only. `AppConfig` and user code reading live `os.environ` are unchanged by this design.
- **A failed build:** startup or reload raises the typed config error (see D12) before any live state changes. On reload, the error is logged at ERROR, the running config and the app registry are unchanged, and the next save triggers a fresh attempt.
- **A successful reload:** the candidate, including validated manifests, replaces the live config's state as a whole.
- **Loader modes:**
  - `run`: settings sources, D3, D8/D9 and manifest validation. Used by `hassette run`.
  - `check`: settings sources, D3 and D8/D9, with no manifest validation and no app import. Used by `hassette run --check` (D14).
  - `client`: settings sources only, no checks. Used by CLI client commands (`hassette status`, `log`, …).
- **The hermetic test config** (init kwargs only, `src/hassette/testing/config.py`) records nothing, so the checks have nothing to scan.

**Recommendation:** A. It fixes all three symptoms at the root, and the checks can't disagree with the config because both read the same records.
**Pick B instead if** the smallest diff matters more and the `.env` reload bug gets filed separately.
**Reversibility:** hard (the loader becomes the single construction path that the CLI, core and reload all depend on)
**Ratified:** Chose a candidate-building loader over a startup env snapshot, with source-recorded keys and swap-on-success reload, rather than a separate scan pass. This fixes the reload wipe, the stale-`.env` reload bug and the scan's double-reporting at one root, accepting custom env/dotenv sources and a single loader every construction path goes through.

### D14: Who resolves the config, apps and project locations?

**Deciding factor:** one owner computes every location once, and every consumer reads that answer.

Today the same fact is computed in at least six places:

- the static class-level `model_config` lists (`config/config.py:57-60`)
- `default_config_dir()`'s case-sensitive `os.getenv` (`config/helpers.py:60-76`)
- the `env_files`/`toml_files` properties that drive the file watcher (`config/config.py:235-258`)
- `AppConfig`'s own static `env_file` (`app/app_config.py:17-23`)
- the launcher mutating both classes' `model_config` (`cli/__init__.py:165-169`)
- `docker_start.sh`, which reads env vars only (`scripts/docker_start.sh:29-33`)

Building a full config can't run before the entrypoint installs dependencies, because `autodetect_apps` imports user modules (`utils/app_utils.py:238`).

| | A: One resolver computes locations once per process; the entrypoint asks Hassette | B: Same resolver in Python; `docker_start.sh` keeps env-only path logic |
|---|---|---|
| Paths set in TOML or via `--config-dir` reach the script | Yes | No |
| Project dir for hautomate (`.:/apps`, apps dir `/apps/src/hautomate`, `uv.lock` at `/apps`) | Found by walk-up | Found only while the apps dir comes from env |
| `/apps` migration hint knows the real apps dir | Yes | Guesses |
| Entrypoint depends on the `hassette` CLI starting | Yes (`hassette run --check`, no app import) | No |

Under A:

- **Resolver inputs:** the CLI flags (`--config-dir`, `--config-file`, `--env-file`) and D13's env snapshot. `config_dir` is **explicit** when any of these is given: `--config-dir`, `HASSETTE__CONFIG_DIR` or `HASSETTE_CONFIG_DIR` (matched case-insensitively, as pydantic-settings matches env names), or a `config_dir` init kwarg. With none of them, `config_dir` is unset (D2 gives the fallback). The resolver replaces `default_config_dir()`'s own env reading.
- **Resolver outputs:** `config_dir`, whether it was explicit, the ordered TOML and `.env` lists (D2), and the config home.
- **Consumers:** D13's loader, the file watcher's watched files, the `.env` list `AppConfig` reads, the D8 scan and the web config view all read the resolver's output. It replaces the launcher's class-level `model_config` mutation.
- **Hermetic test config:** keeps empty lists.
- **Config home:** the explicit `config_dir`, else cwd. It never depends on which files exist.
- **Settings-only command, `hassette run --check [same flags as hassette run]`:** builds the config in D13's `check` mode: location resolution, settings sources, and the D3 and D8/D9 checks. It does no manifest validation and no app autodetect or import (autodetect imports user code, `src/hassette/utils/app_utils.py:238`). It does not start Hassette.
  - On success stdout is exactly three shell-quoted `KEY=VALUE` lines and nothing else: `CONFIG_DIR=<abs path>` (the resolved `config_dir`), `CONFIG_HOME=<abs path>` (the config home above: the explicit `config_dir`, else cwd) and `APPS_DIR=<abs path>`. Exit 0.
  - All logging goes to stderr in `--check` mode, so stdout stays exactly the three lines even when a warning fires. Today `__main__.entrypoint()` calls `enable_basic_logging(...)` (`src/hassette/__main__.py:7`), whose `stream` defaults to `sys.stdout` (`src/hassette/logging_.py:499-530`), and config loading can log warnings such as `warn_log_level_not_valid`. The `--check` path must pass `stream=sys.stderr`. A test pins that a warning during `--check` leaves stdout as only the three lines.
  - The script reads only lines matching `^(CONFIG_DIR|CONFIG_HOME|APPS_DIR)=`.
  - On failure it prints the error to stderr. Exit codes are in D12's exit-code table.
  - Outside Docker it doubles as a "will this config start?" validator for CI and local use.
- **Entrypoint:** `docker_start.sh` runs `hassette run --check "$@"` before installing dependencies, reads `CONFIG_DIR`, `CONFIG_HOME` and `APPS_DIR` from its output, then runs `exec hassette run "$@"`, so both resolve with identical flags. `--config-dir` is a global launcher flag alongside `--config-file`/`--env-file` (the meta launcher in `src/hassette/cli/__init__.py`). The build must confirm the meta launcher accepts global flags after the `run` subcommand token, or the script must place them before `run`. A test pins that a `--config-dir` passed as container args reaches both invocations. Any non-zero exit from `--check` triggers D12's halt, so a config typo halts before any install.
- **Script defaults:** the requirements scan roots are `CONFIG_DIR` and `APPS_DIR`. The project dir is D6's renamed project-dir var if set, else the nearest directory at or above `APPS_DIR` that contains `pyproject.toml` (the uv/pytest walk-up convention), else `CONFIG_HOME`.
- **Migration hint:** when `/apps` is non-empty and the resolved apps dir is not inside it, the script prints a migration message naming both paths before launching.

**Recommendation:** A. Hassette is the only component that knows the paths, and the walk-up handles real layouts with no new setting.
**Pick B instead if** the entrypoint must work even when the `hassette` CLI can't start.
**Reversibility:** easy
**Ratified:** Chose one resolver consumed everywhere, with the entrypoint asking `hassette run --check` and the project dir found by walking up from the apps dir (config home being the explicit `config_dir`, else cwd), over env-only script logic, so every consumer gets one answer and hautomate-style layouts work with no setting, accepting that the entrypoint depends on the `hassette` CLI starting.

## Assumed

- Unknown `HASSETTE__*` process env vars do not appear in `HassetteConfig.model_extra`. All `.env` keys, including ones without the prefix, do. Nested config groups drop unknown keys. Evidence: 2026-10-09 probe against this branch. `HASSETTE__APP_DIR`, `HASSETTE__APPS__DIRECTRY` and `HASSETTE__INSTALL_DEPS` in the env, plus `bogus_top`, `[hassette.apps] directry` and `[hassette.logging] levle` in TOML, and `HASSETTE__DOTENV_TYPO`/`OTHER_VAR` in `.env`, gave `model_extra == {'bogus_top', 'dotenv_typo', 'other_var'}` and nested `model_extra is None`.
- `HassetteConfig` and `AppConfig` both take `env_file` from `ENV_FILE_LOCATIONS` (`config/config.py:59`, `app/app_config.py:20`). `--env-file` overrides both (`cli/__init__.py:165-169`), so any new lookup has to feed both classes.
- `--config-file` / `--env-file` replace the search list with a single path (`cli/__init__.py:165-169`, `docs/pages/core-concepts/configuration/snippets/file_discovery.md`).
- `startup_tasks` loads each existing `.env` file into `os.environ` when `import_dot_env_files` is on, then logs the active and inactive app counts (`core/core.py:167-185`).
- The hermetic test config builds from init kwargs only, with `toml_file`/`env_file` set to `None` and `extra="forbid"` (`src/hassette/testing/config.py:103-112`).
- App definitions can be passed through env vars as `HASSETTE__APPS__<KEY>__CONFIG__<FIELD>`. Evidence: documented in `docs/pages` (`HASSETTE__APPS__PRESENCE__CONFIG__MOTION_SENSOR`).
- Docker: final-stage `WORKDIR /app` (`Dockerfile:89`), `VOLUME ["/config", "/data", "/apps", "/uv_cache"]` (`Dockerfile:116`). `docker_start.sh:29-33` reads `HASSETTE__APPS__DIRECTORY`, `HASSETTE__APP_DIR` and `HASSETTE__CONFIG_DIR`, plus the three script-only vars D6 renames.
- The maintainers' own tooling already uses the correct name: `tests/test_docker_integration.py:47` and `scripts/docker/ha-demo.yml:52` set `HASSETTE__APPS__DIRECTORY`.
- Real user layout (evidence: `~/source/hautomate/config/hassette.toml:33`): `~/source/hautomate` keeps `config/hassette.toml` with `[hassette.apps] directory = "src/hautomate"`, runs locally from the project root, and in Docker mounts `./config:/config` with `HASSETTE__APPS__DIRECTORY=/apps/src/hautomate`.
- For #71, not this PR: the current HA developer docs use the newer "app"/`app_config` naming. Whether Supervisor still accepts the `addon_config` map key is unverified. Either way the add-on maps the user's config at `/config`, which is all this design relies on. Evidence: `design/research/2026-10-09-config-discovery-paths-unknown-keys/web-research-keys-docker.md`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [ ] Ship-time challenge

**Calls made during the build:**

- The loader is `HassetteConfig.__init__` itself, with a `check_keys` flag instead of D13's three named modes: D13's `run` and `check` differ only in manifest validation, and that stays a separate step, so a mode enum would carry a value the loader never reads.
- Initial startup validates manifests in `startup_tasks`, after the `.env` import; reload candidates validate inside `reload()` before the swap: autodetect imports app modules, which may read `os.environ` at import (`tests/integration/test_apps_env.py`), and D13 keeps the `.env` import in `startup_tasks`.
- The environment snapshot is taken at a config's first build and stored on it for reloads: that build happens at CLI entry for `hassette run`, before `startup_tasks`, and it also covers configs built outside the CLI.
- The dead `config_file`/`env_file` settings fields are removed; `--config-file`/`--env-file` arrive as `HassetteConfig` init arguments. Setting either name now fails as an unknown key, listed in the `upgrading.md` migration table.
- A subclass can pin its files with `model_config["toml_file"]`/`["env_file"]` (`None` searches, `[]` reads none); the hermetic test config passes `config_file=[]`/`env_file=[]` as init arguments instead, because pydantic-settings warns about a pinned `toml_file` on a class whose sources omit a TOML source.
- `apps.directory` and `data_dir` defaults come from `default_factory` functions that read the build in progress (`config/build.py`), not from a lowest-priority source, so a subclass's own field default (TestConfig's scratch `data_dir`) still wins.
- `ConfigError` subclasses `ValueError`, and `HassetteConfig` wraps construction `ValidationError`s into it in every mode, and the settings sources raise it for a config file they can't read or parse (naming the file), so any invalid config raises one type.
- `AppConfig` reads the running Hassette config's `.env` list (or the default search outside one) unless a subclass sets `env_file` (its base default is the `HASSETTE_ENV_FILES` marker, so a subclass's `None` keeps pydantic-settings' "no `.env`" meaning), so it now sees values from a custom `--env-file` without `import_dot_env_files`, as it already did for the default files.
- Bootstrap logging (`__main__.entrypoint`) writes to stderr for every command, not only `--check`: stdout is data for `--json` and `--check`, and `hassette run` switches to its configured stream once Hassette starts.
- `hassette run --check` prints a config error as plain text rather than logging it, so the multi-line message stays readable when stderr isn't a terminal (logging renders JSON there).
- TOML did-you-mean suggestions match the last segment against settings in the same table, so `logging.levle` gets no suggestion instead of `logging.all_events`.
- D10's warning decision is `utils.app_utils.apps_dir_warning`, unit-tested on its return value; `startup_tasks` only logs it.
- `docker_start.sh`: when `--check` prints no locations (container args like `--help`/`--version`), it skips installs and goes straight to `exec hassette run`; it drops a user-supplied `--check` from its own check call (passing the flag twice is a usage error); a non-78 failure of the check halts with a container-arguments remedy.
- The project-dir walk-up stops below `/app`, the image's own install, which holds Hassette's `pyproject.toml` and `uv.lock` (reachable when `apps.directory` is under `/app`, as in `scripts/docker/ha-demo.yml`).
- The requirements scan skips the apps dir as a separate root when it is inside the config dir, so each `requirements.txt` is installed once.
- The web config view fixtures (`tests/support/web_mocks.py`, `web_response_helpers.py`, `frontend/src/test/config-fixtures.ts`) needed no change: `config_dir` is still a field with the same shape.
- D14's per-failure remedy comes from `--check` itself: on a config error its stdout carries `CONFIG_ERROR_SOURCE=environment|file`, which `docker_start.sh` reads, not the error text. An unknown process-env key, or a construction `ValidationError` on a field a process-env variable set, raises `EnvironmentConfigError` (a `ConfigError` subclass defined in `config/checks.py`, since `exceptions.py` sits at the 800-line cap). Every other config error is `file`.
- File-relative paths have `..` collapsed (`os.path.normpath`, no symlink resolution), and `--check` prints `APPS_DIR` resolved: the entrypoint compares and walks these paths as strings.
- D11's reference link is `https://hassette.readthedocs.io/en/stable/pages/core-concepts/configuration/`: the published path includes `pages/` (`docs_dir: docs`), and `stable` matches every other docs link in the repo. A test checks the URL names a page under `docs/`.
- A `.env` file that sets `HASSETTE_CONFIG_DIR` (single underscore) fails D3's check like `HASSETTE__CONFIG_DIR`, instead of being silently ignored.
- Config loading is split into `config/locations.py` (resolver, including the old `helpers.default_config_dir`), `config/build.py` (the build in progress), `config/sources.py` (settings sources, including the TOML source formerly in `classes.py`) and `config/checks.py` (unknown keys, D3); pointers above to the old homes predate the split.
- Explicit `config_dir`, `--config-file` and `--env-file` keep the user's spelling (no symlink resolution beyond the resolved cwd that relative ones anchor at), like searched files, so a file reached through a symlinked directory anchors its relative paths at the link however it was named.
- The environment snapshot is kept out of `repr` on `LoadInputs` and `ConfigBuild`, since it holds every secret in the process environment.
- `LoadInputs` records the build's `cwd` and `reload()` replays it, so relative location inputs resolve the same way on reload even if the process cwd changed.
- A test walks the settings model tree and fails on any path-bearing field shape `anchor_paths` can't anchor (D4's "every Path field").
- The TOML settings source takes the resolver's absolute file list directly; the `toml_paths` normalizer it no longer needs is deleted.

## Addendum
