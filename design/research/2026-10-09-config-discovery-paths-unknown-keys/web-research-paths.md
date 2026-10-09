# Prior art: config discovery, config-dir override, relative-path anchor

Method: WebFetch of primary docs (the fetcher summarizes, so wording is approximate except where in quotes). Anything not confirmed is marked [no source found] or "unverified".

## Sources Found

### XDG Base Directory Specification
- **URL**: http://specifications.freedesktop.org/basedir/latest/
- **Type**: standard
- **Key takeaway**: `$XDG_CONFIG_HOME` defaults to `$HOME/.config` when unset or empty; `$XDG_CONFIG_DIRS` defaults to `/etc/xdg`. "The base directory defined by $XDG_CONFIG_HOME is considered more important than any of the base directories defined by $XDG_CONFIG_DIRS": user dir first, additive search, first wins.
- **Relevance**: The only real standard for user-level discovery. It says nothing about project/cwd configs or per-tool `*_CONFIG_DIR` vars (those are tool conventions).

### git-config
- **URL**: https://git-scm.com/docs/git-config
- **Type**: documentation
- **Key takeaway**: Layered and additive (system, `$XDG_CONFIG_HOME/git/config`, `~/.gitconfig`, `$GIT_DIR/config`; "last value found taking precedence"). `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` replace those layers. `include.path`: "If the value of the variable is a relative path, the path is considered to be relative to the configuration file in which the include directive was found."
- **Relevance**: Canonical, explicit "relative to the file that contains it" rule, including for conditional includes.

### Ruff configuration
- **URL**: https://docs.astral.sh/ruff/configuration/
- **Type**: documentation
- **Key takeaway**: Closest config in the directory hierarchy wins; no merging unless `extend`. Falls back to `${config_dir}/ruff/pyproject.toml` (user level). Relative paths (`exclude`, `src`) are relative to the config file's directory when discovered, but relative to CWD when the file is passed with `--config` or is the user-level file.
- **Relevance**: Best example of the "two anchors" wart: file-relative when discovered, cwd-relative when explicit. The inconsistency to avoid.

### ESLint configuration files
- **URL**: https://eslint.org/docs/latest/use/configure/configuration-files
- **Type**: documentation
- **Key takeaway**: Searches up from the target file's dir; `-c/--config` skips the search (exclusive). `files`/`ignores` resolve against the config file dir by default, but against CWD when `--config` is used.
- **Relevance**: Same two-anchor split as ruff.

### TypeScript tsconfig reference
- **URL**: https://www.typescriptlang.org/tsconfig/
- **Type**: documentation
- **Key takeaway**: `include`: "resolved relative to the directory containing the tsconfig.json file." With `extends`: "All relative paths found in the configuration file will be resolved relative to the configuration file they originated in."
- **Relevance**: Strongest statement of file-relative anchoring, and it survives inheritance.

### MkDocs configuration
- **URL**: https://www.mkdocs.org/user-guide/configuration/
- **Type**: documentation
- **Key takeaway**: `docs_dir`, `site_dir`, `theme.custom_dir`, `hooks`, config-file `watch` are "resolved relative to the directory containing your configuration file"; `-f` to another dir therefore moves them. `INHERIT`ed parent paths are not re-anchored.
- **Relevance**: A Python tool where `-f` moves the anchor (file-relative, not cwd-relative), plus an explicit inheritance caveat.

### mypy config file
- **URL**: https://mypy.readthedocs.io/en/stable/config_file.html
- **Type**: documentation
- **Key takeaway**: Walks up from cwd checking `mypy.ini`, `.mypy.ini`, `pyproject.toml`, `setup.cfg`; then `$XDG_CONFIG_HOME/mypy/config`, `~/.config/mypy/config`, `~/.mypy.ini`; first match only. `--config-file` errors if invalid. `mypy_path`: "Relative paths are treated relative to the working directory of the mypy command, not the config file"; `$MYPY_CONFIG_FILE_DIR` exists to opt into file-relative.
- **Relevance**: The main cwd-relative counterexample, and it needed an escape-hatch variable.

### pytest customize / rootdir
- **URL**: https://docs.pytest.org/en/stable/reference/customize.html
- **Type**: documentation
- **Key takeaway**: `-c file` means use that file "and its directory as rootdir"; otherwise search the common ancestor of args and its parents; configs "never merged". The explicit file defines the anchor (rootdir).
- **Relevance**: Exclusive explicit file whose directory becomes the root. (Fetch could not confirm what `testpaths` is relative to; the ini-options reference was not fetched.)

### uv configuration files
- **URL**: https://docs.astral.sh/uv/concepts/configuration-files/
- **Type**: documentation
- **Key takeaway**: Project `uv.toml`/`pyproject.toml` in cwd or nearest parent; user `~/.config/uv/uv.toml`; system `/etc/uv/uv.toml`; layers MERGE (project > user > system). `--config-file` is used "in place of any discovered configuration files" (EXCLUSIVE). `--no-config` disables discovery. Relative-path anchor: not documented there.
- **Relevance**: Modern Python tool with the clean pattern: discovery layered, explicit flag exclusive, separate off-switch.

### pip configuration
- **URL**: https://pip.pypa.io/en/stable/topics/configuration/
- **Type**: documentation
- **Key takeaway**: Global, user (`$HOME/.config/pip/pip.conf`, respects XDG_CONFIG_HOME), site; `PIP_CONFIG_FILE` is ADDITIVE (loaded last, overrides), except `os.devnull` disables all, and if the file exists the user config is skipped.
- **Relevance**: Counterexample: additive env var with quirks.

### Poetry configuration
- **URL**: https://python-poetry.org/docs/configuration/
- **Type**: documentation
- **Key takeaway**: `POETRY_CONFIG_DIR` overrides the config dir; Linux default follows XDG (`~/.config/pypoetry`); local `poetry.toml` beats global; env vars beat both.
- **Relevance**: Example of a `<TOOL>_CONFIG_DIR` env var.

### Docker Compose: project directory, relative paths, multi-file, include
- **URL**: https://docs.docker.com/compose/how-tos/project-name/ ; https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/ ; https://docs.docker.com/reference/compose-file/services/ ; https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/ ; https://docs.docker.com/compose/how-tos/multiple-compose-files/include/
- **Type**: documentation
- **Key takeaway**: "The default project directory is the base directory of the Compose file", overridable with `--project-directory`; otherwise the first `-f` file's dir, else CWD. Bind mount "relative path is resolved from the Compose file's parent directory"; `env_file`: "Relative paths are resolved from the Compose file's parent folder". With merged files "Paths are evaluated relative to the base file"; override files are NOT resolved against their own location. `include`d files resolve "with its own project directory".
- **Relevance**: File-relative anchor with a separate override knob (`--project-directory`) that decouples "where config lives" from "what paths are relative to". Closest analog to hassette's `/config` vs `/apps` split.

### Alacritty config
- **URL**: https://raw.githubusercontent.com/alacritty/alacritty/master/extra/man/alacritty.5.scd
- **Type**: documentation
- **Key takeaway**: Ordered search: `$XDG_CONFIG_HOME/alacritty/alacritty.toml`, `$XDG_CONFIG_HOME/alacritty.toml`, `$HOME/.config/alacritty/alacritty.toml`, `$HOME/.alacritty.toml`, `/etc/alacritty/alacritty.toml`. `import` relative paths are "relative from the current config file".
- **Relevance**: Textbook XDG search order plus file-relative.

### Helix configuration
- **URL**: https://docs.helix-editor.com/configuration.html
- **Type**: documentation
- **Key takeaway**: Global `~/.config/helix/config.toml`; workspace `.helix/config.toml` MERGED over it; `-c/--config` loads a custom file (exclusivity unstated).
- **Relevance**: Project-over-user layering.

### Starship
- **URL**: https://starship.rs/config/
- **Type**: documentation
- **Key takeaway**: `STARSHIP_CONFIG` changes the default `~/.config/starship.toml` location; exclusivity not stated.
- **Relevance**: Pure `<TOOL>_CONFIG` = file-path env var pattern.

### Traefik
- **URL**: https://doc.traefik.io/traefik/getting-started/configuration-overview/
- **Type**: documentation
- **Key takeaway**: Static config searched in `/etc/traefik/`, `$XDG_CONFIG_HOME/`, `$HOME/.config/`, and the working directory; `--configFile` overrides.
- **Relevance**: System-first order (opposite of XDG precedence) with cwd last. File-provider relative path rules: [no source found].

### Home Assistant `hass` CLI and source
- **URL**: https://docs.ncnynl.com/en/home-assistant/docs/tools/hass/ (mirror of the official docs; official https://www.home-assistant.io/docs/tools/hass returned 404) ; https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/__main__.py ; https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/config.py ; https://git.jeena.net/jeena/home-assistant.github.io/src/branch/rc/source/_docs/installation/docker.markdown (old mirrored Docker install docs)
- **Type**: documentation + reference implementation
- **Key takeaway**: `-c/--config` = "Directory that contains the Home Assistant configuration". Source: default is `~/.homeassistant` (`CONFIG_DIR_NAME = ".homeassistant"`); `main()` does `config_dir = os.path.abspath(os.path.join(os.getcwd(), args.config))`, so the CLI value is cwd-relative. Container convention: mount a host folder at `/config`.
- **Relevance**: The dir is a single, CLI-only, exclusive root, resolved before any file is read. Whether `configuration.yaml` may name the config dir: [no source found]; by construction it cannot.

### AppDaemon
- **URL**: https://appdaemon.readthedocs.io/en/latest/CONFIGURE.html ; https://appdaemon.readthedocs.io/en/latest/INSTALL.html ; https://appdaemon.readthedocs.io/en/pydantic-hass/INTERNALS.html (these last two via search summaries, not fetched directly)
- **Type**: documentation
- **Key takeaway**: `-c` = config directory; if omitted, looks for `appdaemon.yaml` in `~/.homeassistant/` then `/etc/appdaemon`, error if neither. Apps default to `./apps` under the config dir; `appdaemon.app_dir` in the YAML overrides (docs example is absolute). Whether a relative `app_dir` resolves against the config dir: unconfirmed. `-C` changes the config file name.
- **Relevance**: Closest sibling to hassette. Config dir via CLI only (not in YAML); sub-dirs default config-dir-relative; YAML can override with an absolute path.

### Zigbee2MQTT
- **URL**: https://www.zigbee2mqtt.io/guide/configuration/ ; https://raw.githubusercontent.com/Koenkk/zigbee2mqtt/master/lib/util/data.ts
- **Type**: documentation + reference implementation
- **Key takeaway**: `ZIGBEE2MQTT_DATA` sets the data dir (config file "has to be located in the data directory"); default is `<install>/data` (module-relative, not cwd). `joinPath(file) = path.resolve(dataPath, file)`: relative paths anchor on the data dir; absolute passes through.
- **Relevance**: Env-var-only, exclusive, single root, everything relative to it. Matches the add-on/Docker model.

### Node-RED
- **URL**: https://nodered.org/docs/user-guide/runtime/configuration ; https://tessl.io/registry/tessl/npm-node-red/4.1.0/files/docs/cli.md (third-party CLI mirror, via search)
- **Type**: documentation
- **Key takeaway**: `userDir` default `$HOME/.node-red`; CLI `-u/--userDir` and `-s/--settings FILE` (default `~/.node-red/settings.js`). `userDir` is also a settings.js property, but the settings file's location comes from flags/defaults (forum answer in the search result: the file "can't tell Node-RED where to look for it"). Relative `flowFile` base: not stated.
- **Relevance**: The one tool found that permits the in-file form, and the file's own location is bootstrapped outside the file. Error vs ignore: [no source found].

### pydantic-settings
- **URL**: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/
- **Type**: documentation
- **Key takeaway**: `env_file`, `secrets_dir`: "either absolute or relative to the current working directory". A bare filename "will only check the current working directory and won't check any parent directories" unless `env_file_depth` is set. Lists allowed; later overrides earlier. Missing secrets_dir only warns. No config-dir convention or `*_CONFIG_DIR` env var. (yaml_file/toml_file handling not in the fetched portion.)
- **Relevance**: Library default is cwd-relative and provides no discovery, so hassette must define its own.

### Dynaconf
- **URL**: https://www.dynaconf.com/settings_files/ ; https://www.dynaconf.com/configuration/
- **Type**: documentation
- **Key takeaway**: Searches from the entry-point script's folder up to root, also checking a `config/` subfolder in each; `root_path` overrides the start and "is relative to cwd"; `includes`/`preload` relative paths use `root_path` as base (fallback: last settings dir, else CWD); `SETTINGS_FILE_FOR_DYNACONF` takes comma/semicolon lists.
- **Relevance**: Library with the `./config` subfolder convention; mixed anchors. In-file `root_path`: [no source found].

### platformdirs / click.get_app_dir
- **URL**: https://platformdirs.readthedocs.io/en/latest/ ; https://click.palletsprojects.com/en/stable/api/
- **Type**: documentation
- **Key takeaway**: platformdirs "Honors XDG_DATA_HOME, XDG_CONFIG_HOME, and friends"; `click.get_app_dir("foo-bar")` returns `~/.config/foo-bar` on Linux (XDG env handling not confirmed on the page).
- **Relevance**: Standard Python libs for the user-level fallback; no override-env-var convention of their own.

## Patterns Found

### Pattern 1: Layered discovery, closest/project wins, user dir as fallback (Q1)

**Used by**: ruff, uv, mypy, pytest, ESLint, pip (user/site layers), Helix, Poetry, git, Alacritty, Traefik.
**How it works**: Walk up from cwd (or from the file being processed) for a project file; then user-level XDG (`$XDG_CONFIG_HOME/<tool>/...` defaulting to `~/.config`); then system (`/etc/<tool>` or `/etc/xdg`). Some MERGE layers (uv, git, pip, Helix); others take first match only (ruff, mypy, pytest: "never merged"). Walk-up is used by project-scoped dev tools; long-running services (HA, AppDaemon, Zigbee2MQTT, Node-RED) do not walk up.
**Strengths**: Zero config in the common case; matches XDG; monorepo-friendly.
**Weaknesses**: Walk-up is surprising for daemons and containers; merge vs first-match varies and must be documented.
**Example**: https://docs.astral.sh/uv/concepts/configuration-files/ ; https://mypy.readthedocs.io/en/stable/config_file.html

### Pattern 2: Explicit override is EXCLUSIVE (Q1, dominant)

**Used by**: uv (`--config-file` "in place of any discovered configuration files"), ESLint (`-c` skips search), pytest (`-c`), Home Assistant (`-c`), AppDaemon (`-c`), Zigbee2MQTT (`ZIGBEE2MQTT_DATA`), Node-RED (`-u`/`-s`), git (`GIT_CONFIG_GLOBAL`/`SYSTEM` replace that layer), mypy (`--config-file` highest precedence, errors if invalid), Starship (effectively).
**How it works**: Once a user names a dir/file, the tool uses only it. No silent fallback to cwd or `~/.config`. A missing explicit target is an error (mypy).
**Strengths**: Predictable; essential for containers/add-ons where the path is fixed.
**Weaknesses**: User loses cascaded user-level defaults unless the tool offers separate layers.
**Example**: https://docs.astral.sh/uv/concepts/configuration-files/ ; https://www.zigbee2mqtt.io/guide/configuration/

### Pattern 3: Explicit override is ADDITIVE (minority) (Q1)

**Used by**: pip `PIP_CONFIG_FILE` (loaded last, overrides; but skips user config if the file exists, `os.devnull` disables all). git `GIT_CONFIG_COUNT`/`-c` override values only.
**How it works**: The named file becomes the highest-precedence layer on top of the defaults.
**Strengths**: Good for overriding a few keys.
**Weaknesses**: pip's own special cases show the confusion; hard to reason about which files participated.
**Example**: https://pip.pypa.io/en/stable/topics/configuration/

### Pattern 4: Env var naming and precedence (Q1)

**Used by**: `ZIGBEE2MQTT_DATA` (dir), `POETRY_CONFIG_DIR` (dir), `STARSHIP_CONFIG` (file), `PIP_CONFIG_FILE` (file), `GIT_CONFIG_GLOBAL` (file). HA and AppDaemon: CLI flag `-c`, no documented env var.
**How it works**: Where documented, precedence is CLI flag > env var > config files > defaults (uv, pip, Poetry). Dir-valued vars are the norm for multi-file tools; file-valued for single-file tools.
**Strengths**: The env var is the container-friendly knob.
**Weaknesses**: No universal name; `<TOOL>_CONFIG_DIR` and `<TOOL>_DATA` both appear.
**Example**: https://python-poetry.org/docs/configuration/

### Pattern 5: Config dir is bootstrapped OUTSIDE the config file (Q2)

**Used by**: Home Assistant (CLI `-c` resolved in `__main__` before any YAML is read), AppDaemon (`-c`/default dirs locate `appdaemon.yaml`), Zigbee2MQTT (env var), Node-RED (flags/defaults locate settings.js).
**How it works**: The location of the file cannot depend on its contents, so the dir comes from argv/env/default and only then is the file loaded. No surveyed tool documents an explicit error for a self-referential key; they simply have no such key. Node-RED is the exception: `userDir` is a settings.js key, but it governs user data, while the file's own location comes from `-s`/`-u`/defaults.
**Strengths**: No chicken-and-egg; one resolution step.
**Weaknesses**: A user who tries the in-file form gets a silent ignore unless the tool warns.
**Example**: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/__main__.py
**Error vs ignore documented?** [no source found] for any tool.

### Pattern 6: Relative paths in a config file are relative to the FILE's (or config dir's) directory (Q3, dominant)

**Used by**: Docker Compose, tsconfig (`extends` keeps the originating file), MkDocs, ESLint and ruff when the config is discovered, git `include.path`, Alacritty `import`, pytest (config's dir becomes rootdir), Zigbee2MQTT (data dir), AppDaemon (apps default `./apps` under config dir).
**How it works**: The config file's directory is the anchor, so the same file behaves identically regardless of cwd. Compose is clearest: default project dir = file's dir, and `--project-directory` overrides it independently of `-f`.
**Strengths**: Reproducible, cwd-independent, works under systemd/Docker/add-ons where cwd is arbitrary.
**Weaknesses**: Inheritance/merge needs care (MkDocs `INHERIT` does not re-anchor; Compose override files resolve against the base file).
**Example**: https://www.typescriptlang.org/tsconfig/ ; https://git-scm.com/docs/git-config

### Pattern 7: Relative paths are relative to CWD (minority; usual for CLI-typed values)

**Used by**: mypy `mypy_path`, ruff and ESLint when config is passed via `--config`, ruff user-level config, pydantic-settings `env_file`/`secrets_dir`, Dynaconf `root_path`, HA's own `-c` value.
**How it works**: Values typed on the command line are naturally cwd-relative (`-c ./foo`). Tools that apply the same rule to in-file values become cwd-dependent; mypy added `$MYPY_CONFIG_FILE_DIR` as an escape hatch.
**Strengths**: Matches shell intuition for CLI args.
**Weaknesses**: Same file behaves differently by cwd; ruff/ESLint switching anchor by how the config was found is a known source of confusion.
**Example**: https://mypy.readthedocs.io/en/stable/config_file.html

### Pattern 8: Split rule: CLI/env values cwd-relative, in-file values file/dir-relative (synthesis)

**Used by**: HA (CLI path vs files under config dir), Compose (`-f` relative to cwd, contents relative to file), git (`-c`/env vs `include.path`).
**How it works**: Resolve the CLI/env path to absolute once at startup, then anchor everything inside files on the file/dir. ruff/ESLint blur this by switching the in-file anchor to cwd for explicit files.
**Strengths**: Each surface follows its user's mental model.
**Weaknesses**: Needs one early absolutization step.
**Example**: [no source found] for a doc stating the split as a principle; inferred from the sources above.

## Tally

### Q1: dir/file override and search order

| Tool | Override mechanism | Explicit override is | Default search |
|---|---|---|---|
| XDG spec | `XDG_CONFIG_HOME`, `XDG_CONFIG_DIRS` | n/a (home first, then dirs) | `~/.config`, then `/etc/xdg` |
| git | `GIT_CONFIG_GLOBAL/SYSTEM` | replaces that layer | system, XDG, `~/.gitconfig`, repo (last wins) |
| ruff | `--config` file | applies to all files | closest up-tree, then `~/.config/ruff` |
| uv | `--config-file`, `--no-config` | EXCLUSIVE | project up-tree, user XDG, `/etc/uv` (merged) |
| mypy | `--config-file` | highest precedence; errors if bad | cwd up-tree, XDG, `~/.config/mypy`, `~/.mypy.ini` |
| pytest | `-c` | EXCLUSIVE, its dir = rootdir | ancestor of args, up-tree |
| ESLint | `-c` | EXCLUSIVE | up-tree from each linted file |
| pip | `PIP_CONFIG_FILE` | ADDITIVE (last) | global, user (XDG), site |
| Poetry | `POETRY_CONFIG_DIR` | replaces dir | XDG `~/.config/pypoetry`; local wins |
| Docker Compose | `-f`, `COMPOSE_FILE`, `--project-directory` | replaces `compose.yaml` lookup | `compose.yaml` in cwd |
| Home Assistant | `-c` (dir) | EXCLUSIVE | `~/.homeassistant`; `/config` in containers |
| AppDaemon | `-c` (dir), `-C` (name) | EXCLUSIVE | `~/.homeassistant/`, `/etc/appdaemon` |
| Zigbee2MQTT | `ZIGBEE2MQTT_DATA` | EXCLUSIVE | `<install>/data` |
| Node-RED | `-u` (dir), `-s` (file) | EXCLUSIVE | `~/.node-red` |
| Traefik | `--configFile` | replaces search | `/etc/traefik/`, XDG, `~/.config/`, cwd |
| Starship | `STARSHIP_CONFIG` | replaces (unstated) | `~/.config/starship.toml` |
| Helix | `-c` | unstated | `~/.config/helix/` + workspace `.helix/` merged |
| Alacritty | none in fetched page | n/a | XDG x2, `~/.config`, `~/.alacritty.toml`, `/etc` |
| pydantic-settings | per-field path or `_env_file=` | n/a | cwd only; `env_file_depth` for parents |
| Dynaconf | `ROOT_PATH_FOR_DYNACONF`, `SETTINGS_FILE_FOR_DYNACONF` | start point replaced | entry-script dir up-tree + `config/` |

### Q2: config-dir key inside the config file

| Tool | Behavior |
|---|---|
| Home Assistant | Dir fixed by argv/default before YAML load; no in-file key. Error vs ignore: [no source found] |
| AppDaemon | Dir by `-c`/defaults; YAML sets `app_dir` (a sub-dir), not the config dir itself (docs silent) |
| Node-RED | `userDir` allowed in settings.js, but the file's own location comes from `-s`/`-u`/defaults |
| Zigbee2MQTT | Env var only; no in-file key documented |
| git | `include.path` links files; root files at fixed locations |
| Dynaconf | In-file `root_path`: [no source found] |

### Q3: anchor of relative paths inside a config file

| Tool | Anchor |
|---|---|
| Docker Compose | Compose file dir / `--project-directory`; merged files use base file; `include` uses each file's own dir |
| tsconfig | the tsconfig containing the path (also under `extends`) |
| MkDocs | dir of `mkdocs.yml` (`-f` moves it); `INHERIT` not re-anchored |
| git `include.path` | the including file |
| Alacritty `import` | the importing file |
| ruff | config file dir (discovered); CWD (`--config` or user-level) |
| ESLint | config file dir (discovered); CWD (`--config`) |
| pytest | rootdir = dir of the config file |
| mypy | CWD for `mypy_path`; `$MYPY_CONFIG_FILE_DIR` for file-relative |
| Zigbee2MQTT | data dir (`path.resolve(dataPath, file)`) |
| AppDaemon | config dir (default `./apps`); relative `app_dir` unconfirmed |
| pydantic-settings | CWD |
| Dynaconf | `root_path` for includes (itself CWD-relative) |
| Home Assistant | `-c` value is CWD-relative; files inside use the config dir |

Dominance: Q1 explicit override is exclusive in every tool that documents it except pip. Q3 in-file paths are file/config-dir-relative; CLI-typed values are cwd-relative.

## Anti-Patterns

- Switching anchor depending on HOW the config was found (ruff, ESLint): same file, different meaning under `--config`.
- Additive "explicit override" with special cases (pip's `PIP_CONFIG_FILE`).
- cwd-relative in-file paths (mypy `mypy_path`) forced an extra variable (`$MYPY_CONFIG_FILE_DIR`).
- Relying on cwd walk-up for long-running services/containers: only dev-time tools (ruff, mypy, uv, pytest) walk up; services (HA, AppDaemon, Z2M, Node-RED) take an explicit dir.
- Inheritance without re-anchoring (MkDocs `INHERIT`, Compose override files): paths silently resolve against the wrong file.
