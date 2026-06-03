# CLI

The `hassette` CLI queries a running Hassette instance over HTTP. Check system health, inspect apps, read logs, and trace handler executions from the terminal. No HA credentials needed for read commands.

The default address is `http://localhost:8126`. See [Configuration](configuration.md) to point the CLI at a remote instance.

## Quick Start

```console
$ hassette status
╭────────────────────── System Status ──────────────────────╮
│  status               ok                                  │
│  websocket_connected  true                                │
│  uptime_seconds       17s                                 │
│  entity_count         103                                 │
│  app_count            3                                   │
│  services_running     EventStreamService, WebApiService,  │
│                       BusService, SchedulerService        │
│  version              0.32.0                              │
│  boot_issues          —                                   │
╰───────────────────────────────────────────────────────────╯
```

`hassette status` shows connection state, uptime, and app count. `boot_issues` lists any apps that failed to initialize.

```console
$ hassette app
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ App Key         ┃ Status  ┃ Display     ┃ Instances ┃ Invoc/1h ┃ Enabled ┃ File              ┃
┃                 ┃         ┃ Name        ┃           ┃          ┃         ┃                   ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ config_app      │ running │ ConfigApp   │ 1         │ 0        │ True    │ config_app.py     │
│ trivial_app     │ running │ TrivialApp  │ 1         │ 0        │ True    │ trivial_app.py    │
│ bus_handler_app │ running │ BusHandler… │ 1         │ 0        │ True    │ bus_handler_app.py│
└─────────────────┴─────────┴─────────────┴───────────┴──────────┴─────────┴───────────────────┘
```

`hassette app` lists every loaded app with its status and invocation count. `Invoc/1h` shows handler firings in the last hour. A count of 0 is normal for apps that react to infrequent events.

```console
$ hassette log --limit 5
┏━━━━━━━━━┳━━━━━━━┳━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ When    ┃ Level ┃ App ┃ Instance ┃ Function            ┃ Message                    ┃
┡━━━━━━━━━╇━━━━━━━╇━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 31s ago │ INFO  │     │          │ run_forever         │ Hassette is running.       │
│ 31s ago │ INFO  │     │          │ run_forever         │ All services started       │
│         │       │     │          │                     │ successfully.              │
│ 32s ago │ INFO  │     │          │ serve               │ Web API server starting    │
│         │       │     │          │                     │ on 0.0.0.0:8126            │
│ 32s ago │ INFO  │     │          │ _auto_wait_depend…  │ Waiting for dependencies:  │
│         │       │     │          │                     │ [RuntimeQueryService, …]   │
│ 32s ago │ INFO  │     │          │ _auto_wait_depend…  │ Waiting for dependencies:  │
│         │       │     │          │                     │ [BusService, StateProxy, …]│
└─────────┴───────┴─────┴──────────┴─────────────────────┴────────────────────────────┘
```

`hassette log` shows the most recent log entries. Narrow to a specific app with `--app <key>`, or go back further with `--since 1h`.

If Hassette isn't running, every command gives the same error:

```console
$ hassette status
Could not connect to Hassette at http://localhost:8126
```

Start Hassette with `hassette run`, then retry. See [Configuration](configuration.md) to connect to a remote instance.

## Next Steps

- [Command Reference](commands.md) — every command with flags and output examples
- [Workflows](workflows.md) — drill down from "something is wrong" to root cause
- [Configuration & Scripting](configuration.md) — JSON output, `jq`, shell completion
