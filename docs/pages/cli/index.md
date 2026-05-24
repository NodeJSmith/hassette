# CLI

The `hassette` CLI lets you query a running Hassette instance from the terminal. Check system health, inspect app status, browse listener invocations, tail logs, and review scheduled jobs — all without opening a browser or composing raw HTTP requests.

The CLI queries the same REST API used by the web UI. You get the same data, formatted for the terminal by default or serialized to JSON for scripting.

## Quick Start

With Hassette running, open a second terminal:

```console
$ hassette status
╭──────────────────── SystemStatusResponse ────────────────────╮
│  status               ok                                     │
│  websocket_connected  True                                   │
│  uptime_seconds       16.57                                  │
│  entity_count         103                                    │
│  app_count            3                                      │
│  services_running     ["EventStreamService", ...]            │
│  version              0.32.0                                 │
│  boot_issues          []                                     │
╰──────────────────────────────────────────────────────────────╯
```

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

If Hassette is not running, you'll see a connection error:

```console
$ hassette status
Network error: Connection refused: http://127.0.0.1:8126
```

See [Configuration](configuration.md) for how to point the CLI at a different address.

## Next Steps

- **[Command Reference](commands.md)**: Every command with flags and output examples.
- **[Workflows](workflows.md)**: How to drill down from system status to a specific invocation.
- **[Configuration & Scripting](configuration.md)**: JSON mode, `jq` recipes, shell completion, error handling.
