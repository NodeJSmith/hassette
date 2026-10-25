# Upgrading Hassette

## Check Your Current Version

Before upgrading, confirm what version you're running. The CLI reports it directly:

```bash
hassette --version
```

To check the version installed in your project:

```bash
uv pip show hassette
```

## Upgrade

How you upgrade depends on how you installed Hassette.

**pip**

```bash
pip install --upgrade hassette
```

**uv (project dependency)**

```bash
uv add hassette@latest
```

This updates `pyproject.toml` and installs the new version into your project environment. If you installed Hassette as a uv tool rather than a project dependency, run `uv tool upgrade hassette` instead.

A running Hassette process keeps the version it started with. After any of the commands above, restart Hassette, then run `hassette --version` to confirm the new version (`uv run hassette --version` for a uv project dependency, so it checks the project's copy rather than whatever `hassette` is on your `PATH`).

**Docker**

Pull the latest image and restart your container:

```bash
docker compose pull
docker compose up -d
```

This pulls whatever tag is configured in your `docker-compose.yml`. To pin a specific version, change the `image:` tag there.

## Reading the Changelog

The changelog lives in two places: `CHANGELOG.md` at the root of the repository, and the [GitHub Releases page](https://github.com/NodeJSmith/hassette/releases). Both contain the same content. GitHub Releases is easier to browse by version; `CHANGELOG.md` is useful if you have the repo checked out.

Each release's notes are curated by hand and grouped by topic, so they don't show raw commit messages or `feat!:`-style prefixes. Before upgrading, read the notes for every version between your current version and the target version. Two sections matter most:

- **Breaking Changes** comes first when a release has any. Each entry names what changed and what to do about it. Treat every entry there as something your app code or config may need to change for.
- **For App Authors: You Can Now Delete** lists workarounds the release makes unnecessary. Nothing breaks if you keep them; removing them is optional cleanup.

A release with no Breaking Changes section needs no changes to your app code.

## Major Version Upgrades

Hassette includes the major version in its data directory path. The current data directory is `~/.local/share/hassette/v0/`. A future v1 release will use `~/.local/share/hassette/v1/` and start with an empty database.

!!! warning "Back up before major upgrades"
    Copy your data directory (`~/.local/share/hassette/v0/` on Linux) to a safe location before upgrading across major versions. The new version starts with an empty database if paths are not explicitly set.

If you want to carry your history forward across a major version bump, set `data_dir` explicitly in your `hassette.toml` before upgrading:

```toml
[hassette]
data_dir = "/home/youruser/.local/share/hassette/v0"
```

With an explicit path set, Hassette uses it regardless of the built-in version default. You control when the data moves.

The default config directory is versioned the same way. Outside Docker it is `platformdirs.user_config_path("hassette", version="v<major>")`, which is `~/.config/hassette/v0/` on Linux. In Docker it is `/config`, which doesn't change between versions.

To keep reading config from the old versioned directory, point `--config-dir` (or `HASSETTE__CONFIG_DIR` in the process environment) at it:

```bash
hassette run --config-dir ~/.config/hassette/v0
```

`config_dir` can't go in `hassette.toml`, because Hassette needs it to find that file.

Docker data volumes carry over across major versions. Mount points are version-independent.

## `base_url` Paths

`base_url` (in `[hassette]` of `hassette.toml`, or `HASSETTE__BASE_URL`) is the address Hassette builds its Home Assistant URLs from. Versions up to 0.57 dropped any path in it. Newer versions keep the path as a prefix: `https://example.com/ha` connects to `https://example.com/ha/api/` and `wss://example.com/ha/api/websocket`.

If your `base_url` is just a scheme, host and port, such as `http://homeassistant.local:8123`, nothing changes. A trailing `/` makes no difference either.

If it has a path, decide whether Home Assistant is really served there. A reverse proxy that serves Home Assistant under `/ha` needs the path, so keep it. A path copied from the browser, such as `http://ha.local:8123/lovelace/0`, is not part of the address, so remove it:

=== "Before"

    ```toml
    [hassette]
    base_url = "http://ha.local:8123/lovelace/0"
    ```

=== "After"

    ```toml
    [hassette]
    base_url = "http://ha.local:8123"
    ```

Hassette logs the URLs it uses at startup. A leftover path shows up in that line, and in the `Cannot reach Home Assistant at ...` error that follows when the connection fails:

```text
Home Assistant URLs: REST http://ha.local:8123/lovelace/0/api/, WebSocket ws://ha.local:8123/lovelace/0/api/websocket
```

## Required `instance_name`

This applies when upgrading from 0.59 or earlier. Each app section in `hassette.toml` runs one instance of the app, or one per `[[...config]]` block (see [Multiple Instances](../core-concepts/apps/configuration.md#multiple-instances)). Every instance must now set `instance_name` in its `config`. Earlier versions filled in a missing name as `ClassName.<index>` (for example `PresenceApp.0`); Hassette no longer does. A section whose instance has no `instance_name` stops Hassette at startup with an error naming the app key and instance index. That includes a section with no `config` at all, and sections with `enabled = false` or `autostart = false`. Add a name to each:

=== "Before"

    ```toml
    [hassette.apps.presence]
    filename = "presence.py"
    class_name = "PresenceApp"
    config = { motion_sensor = "binary_sensor.hall" }
    ```

=== "After"

    ```toml
    [hassette.apps.presence]
    filename = "presence.py"
    class_name = "PresenceApp"
    config = { instance_name = "presence", motion_sensor = "binary_sensor.hall" }
    ```

A name:

- starts with a lowercase letter
- contains only lowercase letters, digits, and `_`
- doesn't end with `_`
- is at most 128 characters

`upstairs` and `kitchen_lights_2` are valid; `MyApp.0`, `Upstairs`, and `kitchen-lights` are not. Every name must be unique across the whole config, disabled apps included. [Instance Names](../core-concepts/apps/configuration.md#instance-names) has the full rules. `hassette run --check` reports a missing, invalid, or duplicate name without starting Hassette.

The old default `ClassName.<index>` isn't a valid name, so a few other things change with it:

- **`self.instance_name` and `self.unique_name`** both return exactly the instance name. Code that stored a cache key or compared an event's `source` against the old `MyApp.0` form needs the new name.
- **Logger names** are now `hassette.apps.<instance_name>`, with the app's bus, scheduler, and other loggers nested under it. Update `logging` config or log filters that referenced `hassette.MyApp.0` to `hassette.apps.my_app`.
- **Tests that use [`AppTestHarness`](../testing/harness.md)** must set `instance_name` in the harness `config` too, as in `AppTestHarness(MyApp, config={"instance_name": "my_app"})`. Without one, entering the harness raises `AppConfigurationError`.

## App Lifecycle Log Lines

This applies when upgrading from 0.59 or earlier. Hassette's lines about an app starting, stopping, and failing used to be written on the app's own logger. They now come from `hassette.apps.<instance_name>.Lifecycle`. That logger follows the app's `framework_log_level`, else `logging.app_handler`, never the app's `log_level`, and its lines are marked `framework`. To keep seeing an app's lifecycle detail at `DEBUG`, set `framework_log_level = "DEBUG"` in that app's `config`, or `logging.app_handler = "DEBUG"` for every app. [Per-App Log Levels](log-levels.md#per-app-log-levels) has the full breakdown.

## Config Paths and Unknown Keys

Upgrading from 0.56 or earlier, four changes can break an existing setup: Hassette resolves relative paths against the file that sets them, rejects setting names it doesn't recognize, keeps Docker apps inside the config mount, and has apps read the same `.env` files as Hassette. This section lists each one. The [Configuration](../core-concepts/configuration/index.md#file-locations) page has the full rules.

### Check Your Configuration

`hassette run --check` validates your configuration without starting Hassette. It prints the three resolved locations and exits 0:

```console
$ hassette run --check
CONFIG_DIR=/home/you/project/config
CONFIG_HOME=/home/you/project
APPS_DIR=/home/you/project/apps
```

A problem prints to stderr and exits 78, with the closest real setting name when one is near:

```console
$ hassette run --check
Invalid configuration: Unknown configuration keys (they match no Hassette setting):
  - base_ulr (from /home/you/project/config/hassette.toml): did you mean base_url?
See the configuration reference: https://hassette.readthedocs.io/en/stable/pages/core-concepts/configuration/
```

An apps directory that doesn't exist is a warning, not an error: the check still exits 0. If the path in `hassette.toml` was written relative to the working directory, the warning names the directory you probably meant and how to write it from the file's directory:

```console
$ hassette run --check
Warning: Apps directory /home/you/project/config/src/myapps does not exist. Did you mean /home/you/project/src/myapps? A path in a config file is relative to that file's directory, so from /home/you/project/config it is written ../src/myapps
CONFIG_DIR=/home/you/project/config
CONFIG_HOME=/home/you/project
APPS_DIR=/home/you/project/config/src/myapps
```

In Docker, run it inside the running container (the entrypoint would pass the extra arguments on to `hassette run`):

```bash
docker compose exec hassette hassette run --check
```

If the container isn't running, `docker compose run --rm --entrypoint hassette hassette run --check` does the same.

### Unknown Keys

**Unknown keys are startup errors.** A `HASSETTE__*` environment variable or `hassette.toml` key that matches no setting stops `hassette run` with exit code 78. Earlier versions ignored these silently. App definitions aren't checked: `[hassette.apps.<key>]` tables and `HASSETTE__APPS__<APP_KEY>__CONFIG__<FIELD>` overrides keep working as before.

**Retired items** fail as unknown keys. Replace each one:

| Retired | Replacement |
|---|---|
| `HASSETTE__APP_DIR` | `HASSETTE__APPS__DIRECTORY`, or put apps in `/config/apps` (Docker) |
| `HASSETTE__LOG_LEVEL` | `HASSETTE__LOGGING__LOG_LEVEL` (startup logging reads it too) |
| `HASSETTE__INSTALL_DEPS` | `HASSETTE_DOCKER_INSTALL_DEPS` |
| `HASSETTE__PROJECT_DIR` | `HASSETTE_DOCKER_PROJECT_DIR` |
| `HASSETTE__PRUNE_UV_CACHE` | `HASSETTE_DOCKER_PRUNE_UV_CACHE` |
| `[hassette.websocket] connect_retry_max_attempts` | Removed; reconnect pacing is fixed. See [Operating](index.md#websocket-reconnection) |
| `[hassette.websocket] connect_retry_initial_wait_seconds` | Removed; reconnect pacing is fixed. See [Operating](index.md#websocket-reconnection) |
| `[hassette.websocket] connect_retry_max_wait_seconds` | Removed; reconnect pacing is fixed. See [Operating](index.md#websocket-reconnection) |
| `[hassette.websocket] early_drop_stable_window_seconds` | Removed; reconnect pacing is fixed. See [Operating](index.md#websocket-reconnection) |
| `[hassette.websocket] early_drop_max_retries` | Removed; reconnect pacing is fixed. See [Operating](index.md#websocket-reconnection) |
| `[hassette.websocket] early_drop_backoff_initial_seconds` | Removed; reconnect pacing is fixed. See [Operating](index.md#websocket-reconnection) |
| `[hassette.websocket] early_drop_backoff_max_seconds` | Removed; reconnect pacing is fixed. See [Operating](index.md#websocket-reconnection) |
| `[hassette.websocket] max_recovery_seconds` | Removed; reconnect pacing is fixed. See [Operating](index.md#websocket-reconnection) |
| `run_app_precheck` | Removed; the precheck always runs. Set `allow_startup_if_app_precheck_fails = true` to start despite a failure |
| `disable_state_proxy_polling` | Removed; the state cache poll always runs. Tune it with `state_proxy_poll_interval_seconds` |
| `config_file` / `env_file` settings | the `--config-file` / `--env-file` CLI flags |
| `config_dir` in `hassette.toml` or `.env` | `--config-dir`, or `HASSETTE__CONFIG_DIR` in the process environment |
| An app's `AppConfig` `env_prefix` starting with `hassette__` (its variables are now checked as Hassette settings) | a prefix outside `HASSETTE__`: `env_prefix="hassette__myapp_"` becomes `env_prefix="myapp_"`, and `HASSETTE__MYAPP_API_KEY` becomes `MYAPP_API_KEY` |

An app's `env_prefix` is set on its config class, the `AppConfig` subclass the app is generic over, as `model_config = SettingsConfigDict(env_prefix=...)`. [App Configuration](../core-concepts/apps/configuration.md) covers how that class receives its values.

The container's start script reads the `HASSETTE_DOCKER_*` variables, not Hassette itself. They use a single underscore after `HASSETTE` because the double-underscore `HASSETTE__` namespace belongs to Hassette settings.

The renamed variables have no fallback. If an old name such as `HASSETTE__INSTALL_DEPS` is still set, the start script's config check rejects it as an unknown key, prints the "HASSETTE CAN'T START" banner, and the container exits with code 78 after its retry delay. The dependency install never runs under the old name.

**Alternate environment variable spellings are no longer read.** Hassette ignores them like any unrelated variable, so a setup that still uses one silently falls back to the default. Rename each one:

| Removed | Replacement |
|---|---|
| `LOG_LEVEL`, `HASSETTE_LOG_LEVEL` | `HASSETTE__LOGGING__LOG_LEVEL` |
| `HASSETTE_CONFIG_DIR` | `HASSETTE__CONFIG_DIR` |
| `HASSETTE_DATA_DIR` | `HASSETTE__DATA_DIR` |

### Relative Paths

**Relative paths resolve against the file that sets them.** A relative path in `hassette.toml` is relative to that file's directory, not the working directory. This breaks `./config/hassette.toml` layouts that wrote working-directory-relative paths. The rule covers `apps.directory`, `data_dir`, `database.path`, `cli.token_file`, and each app's `app_dir`.

=== "Before"

    ```toml
    # ./config/hassette.toml, run from ./
    [hassette.apps]
    directory = "src/myapps"
    ```

=== "After"

    ```toml
    # ./config/hassette.toml, run from ./
    [hassette.apps]
    directory = "../src/myapps"
    ```

In the old layout, `src/myapps` resolved from the working directory (`./`). Now it resolves from `./config/`, the directory holding `hassette.toml`, so the path needs `../` to reach `./src/myapps`.

### Docker: the `/apps` Volume Is Gone

The image no longer sets `HASSETTE__APP_DIR`, and `apps.directory` defaults to `/config/apps`. If you do nothing, no apps load, and startup warns that `/config/apps` doesn't exist or holds no apps. Moving the files under the config mount is the recommended fix:

1. Move `./apps` to `./config/apps`.
2. Remove the `./apps:/apps` line from the `volumes:` block in your compose file.
3. Remove any `HASSETTE__APP_DIR` entry, and rename any other retired variable from the table above.
4. Run `docker compose up -d`.

=== "Before"

    ```yaml
    environment:
      HASSETTE__INSTALL_DEPS: "1"
    volumes:
      - ./config:/config
      - ./apps:/apps
    ```

=== "After"

    ```yaml
    environment:
      HASSETTE_DOCKER_INSTALL_DEPS: "1"
    volumes:
      - ./config:/config   # apps now live in ./config/apps
    ```

To keep a separate mount instead, leave `./apps:/apps` in place and add `HASSETTE__APPS__DIRECTORY: /apps` to the compose `environment:` block.

Use `docker compose up -d` after editing the compose file, not `docker restart`, which keeps the container's old environment.

### App Config `.env` Files

`AppConfig` reads the same `.env` files as the running Hassette config, so values in a file passed with `--env-file` now reach your app settings. A subclass that sets `env_file` in its `model_config` keeps pydantic-settings' meaning: `env_file=None` reads no `.env` file. Under the testing harness, which reads no config files, `AppConfig` reads no `.env` file either; set test values directly instead.

### Verify the Upgrade

Run `hassette run --check` (in Docker, the `docker compose exec` form above) and confirm `APPS_DIR` points where your apps live.

Once Hassette is up, run [`hassette app`](../cli/commands.md#hassette-app). No app should show `failed` (it didn't import or initialize) or `degraded` (only some of its instances started). `stopped` is expected for an app with `autostart = false`, and `blocked` for apps excluded by `hassette run --app`. To see why an app failed, read the logs: they go to the terminal that runs `hassette run`, or in Docker, to `docker compose logs hassette`.
