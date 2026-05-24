# Configuration & Scripting

## Configuration

The CLI reads the same configuration files as the server to discover the server address. You do not need to pass the address on every command.

### Discovery order

1. **Environment variable** — `HASSETTE__WEB_API__HOST` and `HASSETTE__WEB_API__PORT`
2. **`.env` file** — loaded from the current directory or the path in `--env-file`
3. **`hassette.toml`** — loaded from the current directory or the path in `--config-file`
4. **Default** — `http://127.0.0.1:8126`

!!! tip "Remote instances"
    To query a remote Hassette instance, set the host in your environment:

    ```bash
    HASSETTE__WEB_API__HOST=192.168.1.100 hassette status
    ```

    Or persistently in a `.env` file:

    ```ini
    HASSETTE__WEB_API__HOST=192.168.1.100
    HASSETTE__WEB_API__PORT=8126
    ```

### Token

The access token (`HASSETTE__TOKEN`) is **not required** for CLI query commands. Query commands make unauthenticated reads against the REST API. The token is only required when starting the server.

## Output Modes

### Human-readable (default)

Tables for collections, key-value panels for single objects. Colors and formatting are applied when stdout is a TTY.

When piped, Rich automatically strips ANSI codes and disables column truncation so the full values are preserved:

```bash
# Piped output shows full values, no truncation
hassette listener --app my-app | grep error
```

### JSON (`--json`)

Structured output on stdout. The full response model is serialized — a superset of what the human table shows.

```
$ hassette status --json
{
  "status": "ok",
  "websocket_connected": true,
  "uptime_seconds": 45.15,
  "entity_count": 103,
  "app_count": 3,
  "services_running": [
    "EventStreamService",
    "DatabaseService",
    ...
  ],
  "version": "0.32.0",
  "boot_issues": [],
  "log_records_dropped": 9
}
```

When `--json` is active:

- stdout contains exactly one valid JSON document (or nothing on usage errors)
- All diagnostics (errors, warnings, connection issues) go to stderr
- Errors are formatted as a JSON object on stdout (see [Error Handling](#json-error-format) below)

### `NO_COLOR`

Set `NO_COLOR=1` to disable all ANSI color output regardless of TTY detection:

```bash
NO_COLOR=1 hassette status
```

## Scripting with `jq`

Combine `--json` with `jq` for monitoring scripts and automation:

```bash
# Extract the status field
hassette status --json | jq -r '.status'

# List all app keys
hassette app --json | jq -r '.[].app_key'

# Find listeners with errors
hassette listener --json | jq '.[] | select(.failed > 0)'

# Get the error rate class for a specific app
hassette app health my-app --json | jq -r '.error_rate_class'

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

### Alerting on error rate

```bash
#!/usr/bin/env bash
set -euo pipefail

hassette dashboard --json | jq -r '.[] | select(.health_status != "excellent") | "\(.app_key): \(.health_status)"' | while read -r line; do
  echo "ALERT: $line" >&2
done
```

## Shell Completion

Hassette supports tab completion for commands and subcommand names via [cyclopts](https://github.com/BrianPugh/cyclopts). The `--install-completion` flag generates and installs the completion script to the appropriate location for your shell.

### Bash

```bash
hassette --install-completion --shell bash
```

### Zsh

```bash
hassette --install-completion --shell zsh
```

### Fish

```bash
hassette --install-completion --shell fish
```

If `--shell` is omitted, the CLI auto-detects the current shell. After installation, restart your shell or source the relevant config file. Pressing Tab after `hassette ` then shows available subcommands. Subcommand-specific flags are also completed.

## Error Handling

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Server error (4xx/5xx) or usage error (invalid flag combination, bad `--since` format) |
| `2` | Network error — connection refused or request timed out |

### Common errors

**Connection refused:**

```
Network error: Connection refused: http://127.0.0.1:8126 ([Errno 111] Connection refused)
```

Hassette is not running, or the configured address is wrong. Start the server or check the address via environment variables or config files.

**Request timed out:**

```
Network error: Request timed out after 10s: http://127.0.0.1:8126/api/health
```

The server is reachable but not responding. Check server logs for blocking operations.

**Unknown instance name:**

```
Usage error: Instance 'office' not found for app 'my-app'. Available instances: 'default', 'kitchen'
```

Pass the instance name exactly as it appears in `hassette app`, or use the integer index.

### JSON error format

When `--json` is active, errors are written to stdout as a JSON object so scripts can detect them without parsing stderr:

```json
{"error": true, "status": null, "detail": "Connection refused: http://127.0.0.1:8126 ([Errno 111] Connection refused)"}
```

For server errors with an HTTP status:

```json
{"error": true, "status": 503, "detail": "Service unavailable"}
```

## Related Pages

- [Web UI](../web-ui/index.md) — the browser interface covering the same data
- [Database & Telemetry](../core-concepts/database-telemetry.md) — what telemetry is collected and how it is stored
- [Configuration Overview](../core-concepts/configuration/index.md) — config file locations and precedence
