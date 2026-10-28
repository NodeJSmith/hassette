# CLI

The `hassette` CLI queries a running Hassette instance over HTTP. Check system health, inspect apps, read logs, and trace handler executions from the terminal. No HA credentials needed — the CLI talks to Hassette's web API, not Home Assistant. Only `hassette run` itself needs your HA token.

The default address is `http://localhost:8126`. See [Configuration](configuration.md) to point the CLI at a remote instance.

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

`hassette status` shows connection state, uptime, and app count. `websocket_connected` shows whether Hassette has a live connection to Home Assistant — when `false`, no events fire. `services` lists internal services currently running. `boot_issues` lists any apps that failed to initialize; check `hassette log --app <key>` for the error. When an app instance needs a Hassette restart, a table below the panel names each one with its reason.

```console
$ hassette app
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ App             ┃ Status  ┃ Display     ┃ Instances ┃ Restart ┃ Invocations/1h ┃ Enabled ┃ Autostart ┃ File              ┃
┃                 ┃         ┃ Name        ┃           ┃         ┃                ┃         ┃           ┃                   ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ config_app      │ running │ ConfigApp   │ 1         │         │ 0              │ True    │ True      │ config_app.py     │
│ trivial_app     │ running │ TrivialApp  │ 1         │         │ 0              │ True    │ True      │ trivial_app.py    │
│ bus_handler_app │ running │ BusHandler… │ 1         │         │ 0              │ True    │ True      │ bus_handler_app.py│
└─────────────────┴─────────┴─────────────┴───────────┴─────────┴────────────────┴─────────┴───────────┴───────────────────┘
```

`hassette app` lists every loaded app. The `App` column is the identifier other commands take via `--app` — it comes from the `[hassette.apps.<key>]` section name in `hassette.toml`. `Instances` counts running copies of the app; most apps run one. `Restart` counts the app's instances that need a Hassette restart, and is blank when none do (see [Instances that need a restart](../operating/index.md#instances-that-need-a-restart)). `Invocations/1h` counts how many times the app's handlers ran in the last hour — 0 is normal for apps that react to infrequent events.

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

Start Hassette with `hassette run` (covered in [Getting Started](../getting-started/index.md)), then retry. See [Configuration](configuration.md) to connect to a remote instance.

## Next Steps

- [Command Reference](commands.md): every command with flags and output examples
- [Workflows](workflows.md): drill down from "something is wrong" to root cause
- [Configuration & Scripting](configuration.md): JSON output, `jq`, shell completion
