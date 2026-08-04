# Web UI

The web UI shows app health, handler invocation history (a handler is a function your app runs when a Home Assistant event occurs), structured logs, and system configuration.

![Apps page](../../_static/web_ui_apps.png)

## Enabling and Accessing

The web UI is enabled by default. Open your browser to:

```
http://<host>:8126/
```

The default bind address is `0.0.0.0:8126`. The `host` and `port` fields under `[hassette.web_api]` in `hassette.toml` control the bind address.

!!! note "Authentication is on by default"
    Hassette requires a credential for every `/api/*` route. On first start
    with no token configured, Hassette generates one, logs it once, and writes
    it to `<data_dir>/.web_api_token` (mode `0600`). Open the dashboard and
    paste that token into the login screen, or send it as
    `Authorization: Bearer <token>` from a script — see
    [CLI Configuration](../cli/configuration.md) for how the `hassette` CLI
    picks up the same token automatically.

    Setting `host = "127.0.0.1"` under `[hassette.web_api]` adds an extra layer
    for local-only access, but it isn't what stops an unauthenticated peer from
    reaching the API — the token does that regardless of bind address.

    Running a reverse proxy in front of Hassette — Caddy, Traefik, nginx, or
    the Home Assistant add-on's own ingress proxy — and listing its address
    under `trusted_proxies` relocates trust to that proxy: Hassette skips its
    own token check for requests from that peer. The Caddyfile below is a
    bare proxy hop and adds no login by itself — pair it with a forward-auth
    layer such as Authelia or tinyauth (or the add-on's own ingress auth) to
    put a login prompt at the gateway instead of Hassette's token:

    ```caddyfile title="Caddyfile"
    --8<-- "pages/web-ui/snippets/reverse-proxy-caddy.txt"
    ```

    ```toml title="hassette.toml"
    --8<-- "pages/web-ui/snippets/trusted-proxies.toml"
    ```

    `trusted_proxies` matches only the raw peer address of the request — never
    a client-suppliable header like `X-Forwarded-For` — so a bad actor on the
    same network can't spoof their way past it.

The UI can be disabled independently while the REST API stays active:

```toml title="hassette.toml"
--8<-- "pages/web-ui/snippets/disable-ui.toml"
```

!!! note "First run"
    A fresh Hassette install shows empty tables and zero counts until automations
    run and handlers fire. As your apps react to Home Assistant activity, the
    tables fill in with timing data, log entries, and run history.

## Configuration

??? "Configuration quick reference"

    | Setting | Type | Default | Description |
    |---------|------|---------|-------------|
    | `[hassette.web_api] run` | bool | `true` | Enables the web API service (REST API + UI backend) |
    | `[hassette.web_api] run_ui` | bool | `true` | Serves the web UI (requires `run = true`) |
    | `[hassette.web_api] host` | string | `"0.0.0.0"` | Bind host |
    | `[hassette.web_api] port` | int | `8126` | Bind port |
    | `[hassette.web_api] auth_enabled` | bool | `true` | Requires a credential for every `/api/*` route |
    | `[hassette.web_api] auth_token` | string | *(generated)* | Bearer token; generated and persisted to `<data_dir>/.web_api_token` when unset |
    | `[hassette.web_api] trusted_proxies` | tuple | `()` | IPs, CIDRs, or hostnames exempt from the token check |
    | `[hassette.web_api] session_ttl` | int | `3600` | Seconds before a browser login session cookie expires |
    | `[hassette.web_api] cors_origins` | tuple | `("http://localhost:3000", "http://localhost:5173")` | Allowed CORS origins |
    | `[hassette.web_api] log_buffer_size` | int | `2000` | How many log entries the UI keeps in memory |
    | `[hassette.web_api] job_history_size` | int | `1000` | Job execution records to keep |
    | `[hassette.web_api] ui_hot_reload` | bool | `false` | Live-reload on static file changes |

    See [Global Settings](../core-concepts/configuration/index.md) for the full reference.

## Layout

The UI has three persistent navigation elements.

The **sidebar** lists every app grouped by lifecycle status: `FAILING`, `BLOCKED`, `SLOW`, `RUNNING`, `STOPPED`, and `DISABLED`. A search field filters the list by app name. The command palette opens from the search area or with Ctrl+K (Cmd+K on macOS).

![Sidebar](../../_static/web_ui_detail_sidebar.png)

The **status bar** runs across the top. It holds a time-preset selector (Since restart, 1h, 24h, 7d) that scopes all history views. A connection indicator, uptime counter, and theme toggle sit alongside it.

![Status bar](../../_static/web_ui_detail_status_bar.png)

The **command palette** opens with Ctrl+K or Cmd+K. It jumps to pages, apps, handlers, and actions without navigating through the sidebar.

![Command palette](../../_static/web_ui_detail_command_palette.png)

**Alert banners** appear below the status bar when something needs attention. Red banners indicate failed apps. Amber banners mean telemetry is degraded — the database is dropping writes (queue overflow, backpressure, or an unreachable file), so some execution history may be missing. Check the database service logs for the cause.

## Pages

- **[Manage Apps](manage-apps.md)**: start, stop, and reload apps; check health and status
- **[Debug a Failing Handler](debug-handler.md)**: find why a handler is not firing or is throwing errors
- **[Execution Detail](execution-detail.md)**: status, traceback, and logs for a single run
- **[Read and Filter Logs](logs.md)**: search, filter, and stream logs in real time
- **[Inspect Configuration and Code](inspect-config-code.md)**: view global and per-app config, read app source
- **[Check Framework Health](diagnostics.md)**: confirm internal services are running, see boot issues and telemetry drops
- **[Configure Health Checks](health-endpoints.md)**: choose the right endpoint for restart automation, traffic routing, or monitoring
