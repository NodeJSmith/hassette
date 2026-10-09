Hassette finds `hassette.toml` and `.env` in one of two ways, depending on whether a config directory is named.

**With a config directory**, Hassette reads only `<config_dir>/hassette.toml` and `<config_dir>/.env`. Only the `--config-dir` CLI flag and the `HASSETTE__CONFIG_DIR` (or `HASSETTE_CONFIG_DIR`) environment variable set it. Hassette needs `config_dir` to locate `hassette.toml` and `.env`, so setting it inside either file is a startup error. A config directory that doesn't exist is a startup error too, so a misspelled path stops Hassette instead of running it on defaults.

!!! tip "Docker"
    The image sets `HASSETTE__CONFIG_DIR=/config`, so in Docker `/config/hassette.toml` is normally the only config file present, and `apps.directory` defaults to `/config/apps`.

**Without one**, Hassette reads every one of these locations that exists, in order (a later file wins):

1. The default config directory: `/config` if it exists, otherwise the platform config directory (for example `~/.config/hassette/v0` on Linux)
2. `./` (the current working directory)
3. `./config/`

Each location contributes its `hassette.toml` and its `.env`. When more than one `hassette.toml` exists, they merge and a later file replaces any top-level key or whole `[table]` it sets (tables are not merged key by key). Each file's `hassette.local.toml` overlay is then merged on top, key by key — see [Local Overrides](#local-overrides).

Settings resolution reads `.env` files in the same order, so a later `.env` file overrides a value an earlier one set. When `import_dot_env_files` is enabled (the default), each existing `.env` file is also loaded into `os.environ` at startup. That load has no guaranteed order and never overwrites a variable that's already set.

`--config-file / -c` and `--env-file / -e` replace the search list for their file with a single path, which must exist.

Startup logs `Config files read:` with every `hassette.toml`, overlay and `.env` file Hassette found, so you can confirm which ones took effect.

### Relative Paths {#relative-paths}

A relative path resolves against the place that set it:

| Where it is set | Relative to |
|---|---|
| `hassette.toml` | the directory containing that file (a `hassette.local.toml` overlay resolves against its own directory) |
| a `.env` file | the directory containing that `.env` file |
| a process environment variable or CLI flag | the current working directory |

This applies to every path setting: `apps.directory`, `data_dir`, `database.path`, `cli.token_file`, and each app's `app_dir`. In `./config/hassette.toml`, `directory = "../src/myapps"` points at `./src/myapps`.

`apps.directory` defaults to `apps` inside the *config home*, the anchor for config-relative defaults: the explicit `config_dir`; with none set, `/config` if it exists, otherwise the current working directory. In Docker that is `/config/apps`.

### Checking the Resolved Locations {#check-config}

`hassette run --check` loads and validates the configuration without importing apps or starting Hassette. It also requires a token and checks the app entries written in `hassette.toml`; autodetected apps aren't checked, since finding them imports their modules. On success it prints the resolved locations and exits 0:

```console
$ hassette run --check
CONFIG_DIR=/home/you/project/config
CONFIG_HOME=/home/you/project
APPS_DIR=/home/you/project/apps
```

On a configuration error it prints the problem to stderr, prints nothing to stdout, and exits 78 (see [Exit Codes](#exit-codes)). That makes it a cheap CI step.

### Unknown Keys {#unknown-keys}

`hassette run` refuses to start when a setting name matches nothing: a `HASSETTE__*` variable (in the process environment or a `.env` file) or a key in `hassette.toml`. The error lists each key with its source, suggests the closest real setting when one is near, and links back to this page.

The `HASSETTE__` prefix is reserved for Hassette settings, so an `AppConfig` `env_prefix` can't start with `hassette__`. App definition tables (`[hassette.apps.<key>]` and `HASSETTE__APPS__<KEY>__...`) aren't checked here. When the file watcher reloads a config that introduces a bad key, Hassette logs an ERROR and keeps the running config. Commands that query a running instance (`hassette status` and the like) skip the check.

### Exit Codes {#exit-codes}

`hassette run` exits with 78 for configuration problems: invalid values, unknown keys, `config_dir` set in a file, a config location you named that doesn't exist, a missing token, invalid app entries, and a failed app precheck. Everything else exits with 1, including a port already in use. Under systemd, `RestartPreventExitStatus=78` stops a config error from restart-looping.
