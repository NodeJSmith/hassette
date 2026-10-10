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

**Docker**

Pull the latest image and restart your container:

```bash
docker compose pull
docker compose up -d
```

This pulls whatever tag is configured in your `docker-compose.yml`. To pin a specific version, change the `image:` tag there.

## Reading the Changelog

The changelog lives in two places: `CHANGELOG.md` at the root of the repository, and the [GitHub Releases page](https://github.com/NodeJSmith/hassette/releases). Both contain the same content. GitHub Releases is easier to browse by version; `CHANGELOG.md` is useful if you have the repo checked out.

Before upgrading, scan the entries between your current version and the target version. Pay attention to two signals:

- A `BREAKING CHANGE:` footer in a release note means something in your app code may need to change. The footer describes what changed and what you need to do.
- A `!` after the commit type (for example, `feat!:` or `fix!:`) marks a breaking change. If the entry has a `BREAKING CHANGE:` footer, that footer has the details. If it does not, the summary line is all you have. Read it carefully.

Entries without either signal are safe to take without changes to your app code.

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

To keep reading config from the old versioned directory, pass `--config-dir` or set `HASSETTE__CONFIG_DIR` in the process environment. `config_dir` can't go in `hassette.toml`, because Hassette needs it to find that file.

Docker data volumes carry over across major versions. Mount points are version-independent.

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
| `config_file` / `env_file` settings | the `--config-file` / `--env-file` CLI flags |
| `config_dir` in `hassette.toml` or `.env` | `--config-dir`, or `HASSETTE__CONFIG_DIR` in the process environment |
| An app's `AppConfig` `env_prefix` starting with `hassette__` (its variables are now checked as Hassette settings) | a prefix outside `HASSETTE__`: `env_prefix="hassette__myapp_"` becomes `env_prefix="myapp_"`, and `HASSETTE__MYAPP_API_KEY` becomes `MYAPP_API_KEY` |

The container's start script reads the `HASSETTE_DOCKER_*` variables, not Hassette itself. They use a single underscore after `HASSETTE` because the double-underscore `HASSETTE__` namespace belongs to Hassette settings.

The renamed variables have no fallback. If an old name such as `HASSETTE__INSTALL_DEPS` is still set, the start script's config check rejects it as an unknown key, prints the "HASSETTE CAN'T START" banner, and the container exits with code 78 after its retry delay. The dependency install never runs under the old name.

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

Run `hassette run --check` (in Docker, the `docker compose exec` form above) and confirm `APPS_DIR` points where your apps live. Then start Hassette and look for the `Apps directory:` line in the logs, followed by your apps loading.
