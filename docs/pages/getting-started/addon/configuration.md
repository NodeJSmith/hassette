# Add-on Configuration

The add-on reads settings from three places: the **Configuration** tab, `hassette.toml`, and settings the add-on pins. Pinned settings and options both outrank `hassette.toml`.

## Config Folder

The add-on's config folder is mounted at `/config` inside the container. From Samba, File editor or Studio Code Server, it is the folder ending in `_hassette` under `app_configs/`.

| Path | Holds |
|---|---|
| `hassette.toml` | Hassette's settings |
| `apps/` | Your apps |
| `.web_api_token` | The [web API token](#web-api-token) |
| `.env` | Optional environment overrides for Hassette settings; pinned settings still win |
| `pyproject.toml` and `uv.lock` | An optional locked project, installed on every start (see [Dependencies](#dependencies)) |

At start, an empty config folder gets a commented `hassette.toml` and an `apps/` folder with one example app. A folder that holds anything, hidden files included, is left alone.

The telemetry database and the package cache live in the add-on's private `/data` folder. Samba and the editors can't see it, and nothing there needs editing.

## Add-on Options

Set these on the add-on's **Configuration** tab.

| Option | Accepts | When unset | Effect |
|---|---|---|---|
| `log_level` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `logging.log_level` from `hassette.toml`, else `INFO` | Sets Hassette's log level, overriding `hassette.toml` |
| `python_packages` | Plain requirement specifiers, one per entry | Empty list | Installed on every start, after the `uv.lock` project |

In YAML, the options look like this:

```yaml
--8<-- "pages/getting-started/addon/snippets/config-options.yaml"
```

`python_packages` accepts plain requirement specifiers only, such as `requests`, `requests[socks]` or `httpx>=0.27`. Supervisor, the part of Home Assistant that runs add-ons, rejects URL and VCS specifiers (`git+https://...`) and markers with quoted values (`; python_version > '3.11'`) when you save. For those, use a `uv.lock` project (see [Dependencies](#dependencies)).

## hassette.toml

Every other setting goes in `hassette.toml`. The [configuration reference](../../core-concepts/configuration/index.md) lists the settings and the order Hassette resolves sources in. [App Configuration](../../core-concepts/apps/configuration.md) covers per-app settings.

Every app in `apps/` needs a `[hassette.apps.<key>]` section, where `<key>` is a name you choose. `filename` and `class_name` are required, and `config` gives the app its own settings. An app without a section doesn't run; startup logs a warning with the section to paste. The starter file ships the example app's section, with its `config` line commented out:

```toml
--8<-- "pages/getting-started/addon/snippets/config-app-section.toml"
```

## Settings the Add-on Owns

Nothing in this table needs setting: the add-on handles it. It sets these as environment variables on every start. Environment variables outrank `hassette.toml` and `/config/.env`, so changing these settings in either file has no effect.

| Setting | Value | Why |
|---|---|---|
| `base_url` | `http://supervisor/core` | Hassette reaches Home Assistant through Supervisor's proxy. |
| `token` | Supervisor's token | The proxy authenticates with it, so there is no token to paste. |
| `web_api.host` | `0.0.0.0` | The sidebar, health check and discovery rely on this address. |
| `web_api.port` | `8126` | Ingress, the health check and discovery use this port. |
| `web_api.run` | `true` | The sidebar, health check and discovery need the web server. |
| `web_api.run_ui` | `true` | The sidebar entry serves the UI. |
| `web_api.auth_enabled` | `true` | The direct port always requires the web API token. |
| `web_api.trusted_proxies` | `["172.30.32.2"]` | Supervisor's ingress gateway. Sidebar requests from it skip the token check. |
| `web_api.token_file` | `/config/.web_api_token` | Samba and the editors can see the config folder, so you can read the token. |
| `database.path` | `/data/hassette.db` | The backup snapshot, backup exclusions and restore all name this file. |
| `database.shutdown_snapshot_path` | `/data/backup/hassette-snapshot.db` | Backups carry this snapshot instead of the live database. See [Backups](operating.md#backups). |
| `logging.log_format` | `console` | The **Log** tab shows readable lines. Supervisor gives the add-on no terminal, so `auto` would pick JSON. |

!!! warning "Don't set `web_api.auth_token` in the add-on"
    A configured `web_api.auth_token` wins over the token file. Discovery still sends the file's token, so a paired integration gets a token that fails. Hassette logs a warning when this happens. Remove the setting to go back to the token file.

## Dependencies

The add-on installs dependencies on every start, in this order:

1. A `uv.lock` project.
2. The `python_packages` option.

Installs are cached. If the package index is unreachable, the add-on falls back to the cache. See [Startup](operating.md#startup) for what happens when that fails too. A package that conflicts with Hassette's own pins stops the add-on; see [the troubleshooting table](operating.md#the-add-on-stops-with-a-hassette-cant-start-banner).

To add a package:

1. Open the add-on's **Configuration** tab.
2. Add the requirement to `python_packages`.
3. Save, then restart the add-on from its page.
4. Check the **Log** tab for `python_packages install: complete`.

To install a locked project, put its `pyproject.toml` and `uv.lock` in the config folder or in `apps/`. The add-on uses the first `pyproject.toml` it finds, starting in `apps/`. A `pyproject.toml` without a `uv.lock` is skipped, and the log says to run `uv lock`. Run it on your own computer, then copy both files into the config folder. [Managing Dependencies](../docker/dependencies.md) covers creating the project and running `uv lock`.

Unlike the Docker image, the add-on never installs `requirements.txt` files. List those packages in `python_packages` or move them into a `uv.lock` project.

## Web UI and Direct Port

The sidebar entry serves the UI through Home Assistant ingress, behind Home Assistant's own login. Hassette has no separate login there.

!!! warning "The admin-only sidebar entry doesn't restrict access"
    The sidebar entry is shown to admins only, but that only hides it. Any logged-in Home Assistant user with the ingress URL gets the full UI. That includes starting, stopping and reloading apps. Give Home Assistant accounts only to people you trust with your apps.

### Direct port (optional)

The direct port maps the add-on's port `8126` to a host port you choose. It serves the same UI and API to the `hassette` CLI and to browsers outside Home Assistant. It is off until you enter a host port, and it always requires the [web API token](#web-api-token).

To turn it on:

1. Open the add-on's **Configuration** tab and find the **Network** section.
2. In the field labeled **Direct web UI and API (token login)**, enter a port number, such as `8126`.
3. Save, then restart the add-on.

At each start, the log shows the mapping, such as `Port mappings: 8126/tcp -> host port 8126`, or `none (ingress only)`. Point the CLI at `http://<home-assistant-host>:<host port>` with the token; see [CLI Configuration](../../cli/configuration.md). [Web UI](../../web-ui/index.md) covers authentication and trusted proxies in full.

## Web API Token

The sidebar needs no token. You need the web API token only for the direct port, the `hassette` CLI, or an integration you added by hand. Hassette generates it on first start and writes it to `.web_api_token` in the config folder.

To read it, open that file and copy the token. The file name starts with a dot, so it's hidden. Turn on hidden files in Samba or your editor to see it.

To rotate the token:

1. Delete `.web_api_token` from the config folder.
2. Restart the add-on from its page.

Hassette writes a new token on start. Browsers on the direct port must log in again. A Discovered-card integration picks up the new token after its next failed request. The CLI and a hand-added integration need the new token. For the integration, choose **Reconfigure** (see [Home Assistant Integration](../home-assistant-integration.md)).

The token is included in backups, like the rest of the config folder.
