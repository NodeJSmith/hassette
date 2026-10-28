# CLI

The `hassette` CLI queries a running Hassette instance over HTTP. Check system health, inspect apps, read logs, and trace handler executions from the terminal. No HA credentials needed — the CLI talks to Hassette's web API, not Home Assistant. Only `hassette run` itself needs your HA token.

The `hassette` command installs with the `hassette` package. In a uv project, run it as `uv run hassette …`, or activate the project's virtual environment first. The query commands (`status`, `app`, `log`, `config`, and the rest) need a running Hassette instance to answer them.

The default address is `http://127.0.0.1:8126`, the loopback address of the machine running the CLI. See [Configuration](configuration.md) to point the CLI at a remote instance.

## Quick Start

```console
$ hassette status
╭────────────────────── System Status ──────────────────────╮
│  status               ok                                  │
│  websocket_connected  true                                │
│  uptime_seconds       17s                                 │
│  entity_count         103                                 │
│  app_count            3 tracked instances                 │
│  services             EventStreamService, BusService,     │
│                       SchedulerService, WebApiService      │
│  version              0.32.0                              │
│  boot_issues          —                                   │
╰───────────────────────────────────────────────────────────╯
```

`hassette status` shows connection state, uptime, and app count. `app_count` counts tracked app instances, not apps: one app configured with two instances counts as 2. `websocket_connected` shows whether Hassette has a live connection to Home Assistant — when `false`, no events fire. `services` lists internal services currently running. `boot_issues` lists any apps that failed to initialize; check `hassette log --app <key>` for the error.

```console
$ hassette app
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ App             ┃ Status  ┃ Display     ┃ Instances ┃ Invocations/1h ┃ Enabled ┃ File              ┃
┃                 ┃         ┃ Name        ┃           ┃                ┃         ┃                   ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ config_app      │ running │ ConfigApp   │ 1         │ 0              │ True    │ config_app.py     │
│ trivial_app     │ running │ TrivialApp  │ 1         │ 0              │ True    │ trivial_app.py    │
│ bus_handler_app │ running │ BusHandler… │ 1         │ 0              │ True    │ bus_handler_app.py│
└─────────────────┴─────────┴─────────────┴───────────┴────────────────┴─────────┴───────────────────┘
```

`hassette app` lists every loaded app. The `App` column is the identifier other commands take via `--app` — it comes from the `[hassette.apps.<key>]` section name in `hassette.toml` (see [Application Configuration](../core-concepts/apps/configuration.md#registering-an-app)). `Instances` counts running copies of the app; most apps run one. `Invocations/1h` counts how many times the app's handlers ran in the last hour — 0 is normal for apps that react to infrequent events.

```console
$ hassette log --limit 5
┏━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ When    ┃ Level   ┃ Author    ┃ App    ┃ Instance ┃ Function        ┃ Message                              ┃
┡━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 30s ago │ INFO    │           │ my_app │ my_app   │ on_initialize   │ Hello from Hassette!                 │
│ 45s ago │ WARNING │           │ my_app │ my_app   │ on_light_change │ Kitchen light reported no brightness │
│ 50s ago │ ERROR   │ framework │ my_app │ my_app   │ call_service    │ Failed to call service light.turn_on │
└─────────┴─────────┴───────────┴────────┴──────────┴─────────────────┴──────────────────────────────────────┘
```

`hassette log` shows the most recent log entries: every line your apps wrote, plus Hassette's own lines at ERROR and above. The `Author` column marks Hassette's lines `framework`, including ones it writes about your app, like the failed service call above. Add `--author all` to see the rest of Hassette's lines. Narrow to a specific app with `--app <key>` (the `App` column from the table above), or go back further with `--since 1h`.

If Hassette isn't running, every command gives the same error:

```console
$ hassette status
Network error: Connection refused: http://127.0.0.1:8126 (All connection attempts failed)
```

This error has two common causes: Hassette isn't running, or the CLI is pointed at the wrong address. Start Hassette with `hassette run` (covered in [Getting Started](../getting-started/index.md)), then retry. If Hassette is already running, check the address in the error against where Hassette listens. [Configuration](configuration.md#discovery-order) explains where the CLI gets its address and how to change it.

## Next Steps

- [Command Reference](commands.md): every command with flags and output examples
- [Workflows](workflows.md): drill down from "something is wrong" to root cause
- [Configuration & Scripting](configuration.md): JSON output, `jq`, shell completion
