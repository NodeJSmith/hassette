# CLI

The `hassette` CLI lets you query a running Hassette instance from the terminal. Check system health, inspect app status, browse listener invocations, tail logs, and review scheduled jobs — all without opening a browser or composing raw HTTP requests.

The CLI queries the same REST API used by the web UI. You get the same data, formatted for the terminal by default or serialized to JSON for scripting.

## Quick Start

With Hassette running, open a second terminal and try these commands:

```bash
# Is the system healthy?
hassette status

# What apps are loaded?
hassette app

# What happened in the last hour?
hassette log --since 1h
```

Expected output for `hassette status`:

```
Status          ok
WebSocket       connected
Uptime          2h 14m 33s
Apps            3
Entities        487
Version         0.26.0
```

If Hassette is not running, or if the server address does not match the default, you will see a connection error on stderr with the address that was attempted. See [Configuration](#configuration) and [Error Handling](#error-handling) below.

## Command Reference

### `hassette status`

System health summary: status, WebSocket connection, uptime, app count, entity count, and version.

```bash
hassette status
hassette status --json
```

**API endpoint:** `GET /api/health`

---

### `hassette app`

List all loaded apps with their key, display name, status, instance count, and recent invocation counts. Uses the manifests endpoint which includes per-app metadata; the simpler `GET /api/apps` status endpoint is available via `--json` and the REST API directly.

```bash
hassette app
```

**Subcommands:**

| Subcommand | Description | API endpoint |
|---|---|---|
| `hassette app` | List all apps | `GET /api/apps/manifests` |
| `hassette app health <key>` | Health metrics for one app | `GET /api/telemetry/app/{key}/health` |
| `hassette app activity <key>` | Recent activity feed for one app | `GET /api/telemetry/app/{key}/activity` |
| `hassette app config <key>` | Resolved configuration for one app | `GET /api/apps/{key}/config` |
| `hassette app source <key>` | Source file location for one app | `GET /api/apps/{key}/source` |

**Flags:**

| Flag | Applies to | Description |
|---|---|---|
| `--instance` | `health`, `activity` | Filter to a specific app instance (index or name) |
| `--since` | `health`, `activity` | Time window for metrics (e.g. `1h`, `7d`) |
| `--json` | all | Output as JSON |

**Examples:**

```bash
hassette app health my-app
hassette app health my-app --instance office --since 6h
hassette app activity my-app --since 30m --limit 20
hassette app config my-app
```

---

### `hassette listener`

List all registered event bus listeners, or view invocation history for a specific listener.

```bash
hassette listener
hassette listener <id>
```

Bare `hassette listener` lists all listeners with their topic, handler method, invocation counts, and average duration. Pass a listener ID to see the invocation history for that listener.

**API endpoints:**

- `hassette listener` → `GET /api/bus/listeners`
- `hassette listener --app <key>` → `GET /api/telemetry/app/{key}/listeners`
- `hassette listener <id>` → `GET /api/telemetry/handler/{id}/invocations`

**Flags:**

| Flag | Description |
|---|---|
| `--app <key>` | Filter to listeners belonging to this app |
| `--instance <n>` | Filter to a specific app instance (requires `--app`) |
| `--since <duration>` | Time window for invocation counts and history |
| `--limit <n>` | Maximum number of invocation records to return (when viewing a specific listener) |
| `--source-tier <tier>` | Filter by `app` (user automations) or `framework` (internal Hassette components). Server defaults to `app` |
| `--json` | Output as JSON |

**Examples:**

```bash
hassette listener
hassette listener --app my-app --since 1h
hassette listener --app my-app --instance 0
hassette listener 42
hassette listener 42 --limit 50
```

---

### `hassette job`

List all scheduled jobs, or view execution history for a specific job.

```bash
hassette job
hassette job <id>
```

**API endpoints:**

- `hassette job` → `GET /api/scheduler/jobs`
- `hassette job --app <key>` → `GET /api/telemetry/app/{key}/jobs`
- `hassette job <id>` → `GET /api/telemetry/job/{id}/executions`

**Flags:**

| Flag | Description |
|---|---|
| `--app <key>` | Filter to jobs belonging to this app |
| `--instance <n>` | Filter to a specific app instance (requires `--app`) |
| `--since <duration>` | Time window for execution history |
| `--limit <n>` | Maximum number of execution records to return (when viewing a specific job) |
| `--source-tier <tier>` | Filter by `app` or `framework`. Server defaults to `all` for global queries, `app` for per-app queries |
| `--json` | Output as JSON |

**Examples:**

```bash
hassette job
hassette job --app my-app
hassette job 7 --limit 20
```

---

### `hassette log`

Recent log entries from the in-memory log buffer.

```bash
hassette log
hassette log --since 1h
hassette log --app my-app --since 30m --limit 50
```

**API endpoint:** `GET /api/logs/recent`

**Flags:**

| Flag | Description |
|---|---|
| `--app <key>` | Filter to log entries from this app |
| `--since <duration>` | Time window filter (e.g. `1h`, `30m`) |
| `--limit <n>` | Maximum number of entries to return |
| `--json` | Output as JSON |

!!! note "Buffer size"
    Logs are kept in a ring buffer (default: 2000 entries). Entries older than the buffer window are not available. For persistent log storage, configure your process manager to capture stdout.

---

### `hassette execution`

Log entries and metadata for a specific execution, identified by its UUID.

```bash
hassette execution <uuid>
```

**API endpoint:** `GET /api/executions/{execution_id}`

**Flags:** `--limit`, `--json`

---

### `hassette event`

Recent Home Assistant events received by the WebSocket connection.

```bash
hassette event
hassette event --limit 100
```

**API endpoint:** `GET /api/events/recent`

**Flags:** `--limit`, `--json`

---

### `hassette config`

The resolved Hassette configuration as loaded from all sources (TOML, env vars, defaults).

```bash
hassette config
hassette config --json
```

**API endpoint:** `GET /api/config`

---

### `hassette service`

Home Assistant services available on the connected instance.

```bash
hassette service
hassette service --json
```

**API endpoint:** `GET /api/services`

!!! note
    Service data is proxied directly from Home Assistant and has a variable schema. The output mirrors the HA API response and is not normalized.

---

### `hassette telemetry`

Telemetry database statistics: record counts, retention window, and database size.

```bash
hassette telemetry
```

**API endpoint:** `GET /api/telemetry/status`

---

### `hassette dashboard`

App grid summary as shown on the web UI dashboard: per-app health status, invocation counts, and error rates.

```bash
hassette dashboard
hassette dashboard --json
```

**API endpoint:** `GET /api/telemetry/dashboard/app-grid`

---

## Shared Flags

These flags are supported across multiple commands. The table below shows which commands accept each flag.

| Flag | Format | Commands | Description |
|---|---|---|---|
| `--app <key>` | string | `listener`, `job`, `log` | Filter results to a specific app key |
| `--instance <n>` | int or string | `listener`, `job`, `app health`, `app activity` | Filter to a specific app instance. Accepts an integer index (`0`, `1`) or an instance name (`office`). Requires `--app`. |
| `--since <duration>` | relative or absolute | `listener`, `job`, `log`, `event`, `app health`, `app activity` | Time window for filtering. See formats below. |
| `--limit <n>` | integer | `log`, `event`, `execution`, `app activity`, and per-ID commands | Maximum number of records to return |
| `--source-tier <tier>` | `app` or `framework` | `listener`, `job`, `log`, `app health` | Filter by source tier. `app` returns user automation records; `framework` returns internal Hassette component records. Defaults to `app` for listener, job, and app health. |
| `--json` | — | all commands | Output as JSON. See [Output Modes](#output-modes). |

### `--since` format

`--since` accepts two formats:

**Relative durations** — a number followed by a unit suffix:

| Suffix | Unit |
|---|---|
| `s` | seconds |
| `m` | minutes |
| `h` | hours |
| `d` | days |
| `w` | weeks |

Examples: `30s`, `15m`, `1h`, `7d`, `2w`. Compound durations (`1h30m`) are not supported.

**Absolute timestamps** — ISO 8601 format, interpreted as local time:

- `2026-05-22T14:00:00` — date and time
- `2026-05-22` — date only (midnight local time)

Invalid formats exit non-zero with an error on stderr listing accepted formats.

### `--instance` resolution

`--instance` requires `--app`. It accepts:

- **Integer index** — passed directly to the API as `instance_index`. Most apps have a single instance at index `0`.
- **Instance name** — resolved to an index by fetching the app manifest. If no instance has the given name, the CLI exits non-zero and lists the available instance names.

`--instance` without `--app` exits non-zero with a usage error.

## Output Modes

### Human-readable (default)

Tables for collections, key-value panels for single objects. Colors and formatting are applied when stdout is a TTY. When piped, Rich strips ANSI codes automatically and disables truncation.

```bash
hassette listener --app my-app | grep error
```

### JSON (`--json`)

Structured output on stdout. The full response model is serialized — a superset of what the human table shows. Useful for scripting and automation.

```bash
hassette status --json
```

Output:

```json
{
  "status": "ok",
  "websocket_connected": true,
  "uptime_seconds": 8073.4,
  "entity_count": 487,
  "app_count": 3,
  "version": "0.26.0",
  ...
}
```

When `--json` is active:

- stdout contains exactly one valid JSON document (or nothing on usage errors)
- All diagnostics (errors, warnings, connection issues) go to stderr
- Errors are formatted as `{"error": true, "status": <http_status>, "detail": "..."}` on stdout

### `NO_COLOR`

Set `NO_COLOR=1` to disable all ANSI color output regardless of TTY detection:

```bash
NO_COLOR=1 hassette status
```

## Scripting Examples

Use `--json` with `jq` to build monitoring scripts and dashboards:

```bash
# Extract the status field
hassette status --json | jq '.status'

# Find listeners with errors
hassette listener --app my-app --json | jq '.[] | select(.error_count > 0)'

# Get the error rate for a specific app
hassette app health my-app --json | jq '.error_rate_class'

# List all app keys
hassette app --json | jq '.[].app_key'

# Count failed invocations in the last hour
hassette listener 42 --since 1h --json | jq '[.[] | select(.status == "error")] | length'
```

### Health check script

```bash
#!/usr/bin/env bash
set -euo pipefail

STATUS=$(hassette status --json | jq -r '.status')
if [[ "$STATUS" != "ok" ]]; then
  echo "Hassette is degraded: $STATUS" >&2
  exit 1
fi
echo "Hassette is healthy"
```

## Configuration

The CLI reads the same configuration files as the server to discover the server address. You do not need to pass the address on every command.

### Discovery order

1. **Environment variable** — `HASSETTE__WEB_API__HOST` and `HASSETTE__WEB_API__PORT`
2. **`.env` file** — loaded from the current directory or the path passed to `--env-file`
3. **`hassette.toml`** — loaded from the current directory or the path passed to `--config-file`
4. **Default** — `http://127.0.0.1:8126`

!!! tip "Remote instances"
    To query a remote Hassette instance, set the host in your environment:

    ```bash
    HASSETTE__WEB_API__HOST=192.168.1.100 hassette status
    ```

### Token

The access token (`HASSETTE__TOKEN`) is **not required** for CLI query commands. Query commands make unauthenticated reads against the REST API. The token is only required when starting the server.

## Shell Completion

Hassette supports tab completion for commands and subcommand names via [cyclopts](https://github.com/BrianPugh/cyclopts).

### Bash

Add to `~/.bashrc`:

```bash
eval "$(hassette --completion bash)"
```

Then reload your shell:

```bash
source ~/.bashrc
```

### Zsh

Add to `~/.zshrc`:

```bash
eval "$(hassette --completion zsh)"
```

Then reload your shell:

```bash
source ~/.zshrc
```

### Fish

Add to `~/.config/fish/config.fish`:

```fish
hassette --completion fish | source
```

Or save to a completions file for permanent installation:

```fish
hassette --completion fish > ~/.config/fish/completions/hassette.fish
```

After setup, pressing Tab after `hassette ` shows available subcommands. Subcommand-specific flags are also completed.

## Error Handling

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Server error — the server returned a 4xx or 5xx response |
| `2` | Network error — connection refused or request timed out |

Usage errors (unknown flag, invalid `--since` format, `--instance` without `--app`) exit non-zero with a plain-text message on stderr.

### Common errors

**Connection refused:**

```
Error: Connection refused: http://127.0.0.1:8126
       Is Hassette running? Check the server address with --config-file or HASSETTE__WEB_API__HOST.
```

Hassette is not running, or the configured address is wrong. Start the server with `hassette` or check the address in your config.

**Request timed out:**

```
Error: Request timed out after 10s: http://127.0.0.1:8126/api/health
```

The server is reachable but not responding. Check server logs for blocking operations.

**Unknown instance name:**

```
Error: No instance named "office" for app "my-app". Available: default, kitchen
```

Pass the instance name exactly as it appears in `hassette app`, or use the integer index.

### JSON error format

When `--json` is active, errors are written to stdout as a JSON object so scripts can detect them without parsing stderr:

```json
{"error": true, "status": 503, "detail": "Service unavailable"}
```

For network errors where no HTTP status is available:

```json
{"error": true, "status": null, "detail": "Connection refused: http://127.0.0.1:8126"}
```

## Related Pages

- [Web UI](../web-ui/index.md) — the browser interface covering the same data
- [Database & Telemetry](../core-concepts/database-telemetry.md) — what telemetry is collected and how it is stored
- [Configuration Overview](../core-concepts/configuration/index.md) — config file locations and precedence
