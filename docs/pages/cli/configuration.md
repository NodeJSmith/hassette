# Configuration & Scripting

## Configuration

### Discovery Order

The CLI is a client that queries a running Hassette server. It constructs the server address from the same configuration sources Hassette uses at runtime — the `__` double underscore in variable names separates nested config sections, so `HASSETTE__WEB_API__HOST` sets `web_api.host`.
Priority runs highest to lowest:

1. **Global flags**: `--config-file` and `--env-file` override which files are loaded
2. **Environment variables**: `HASSETTE__WEB_API__HOST` and `HASSETTE__WEB_API__PORT`
3. **`.env` file**: loaded from the current directory (or the path given to `--env-file`)
4. **[`hassette.toml`](../core-concepts/configuration/index.md)**: loaded from the current directory (or the path given to `--config-file`)
5. **Default**: `http://127.0.0.1:8126`

!!! tip "Remote instances"
    To query a remote Hassette instance, set the host in the environment:

    ```bash
    HASSETTE__WEB_API__HOST=192.168.1.100 hassette status
    ```

    Or persistently in a `.env` file:

    ```ini
    HASSETTE__WEB_API__HOST=192.168.1.100
    HASSETTE__WEB_API__PORT=8126
    ```

### Token

The access token (`HASSETTE__TOKEN`) is the long-lived HA token that `hassette run` uses to connect to Home Assistant. Query commands (`status`, `app`, `listener`, and the rest) talk to Hassette's own web API instead and need no token.

## Output Modes

### Human-Readable (Default)

The CLI renders tables for collections and key-value panels for single objects. Colors and formatting apply when output goes to a terminal.

When output is piped to another command or a file, color codes are stripped and full untruncated values are shown:

```bash
hassette listener --app my-app | grep error
```

### JSON (`--json`)

`--json` writes a single JSON document to stdout — the full data from the server, a superset of what the human table displays.

```console
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

In `--json` mode:

- stdout contains exactly one JSON document, either the success result or an error object
- Exit code distinguishes success (`0`) from failure (`1` for HTTP errors, `2` for network errors)
- No Rich formatting or human-readable text appears on stdout

### `NO_COLOR`

`NO_COLOR=1` disables all ANSI color output regardless of TTY detection:

```bash
NO_COLOR=1 hassette status
```

## Shell Completion

Hassette provides tab completion for commands and flags via [cyclopts](https://github.com/BrianPugh/cyclopts).

### Generate to stdout

`--generate-completion` prints the completion script to stdout:

```bash
# Zsh
hassette --generate-completion zsh > ~/.zsh/completions/_hassette

# Bash
hassette --generate-completion bash > ~/.local/share/bash-completion/completions/hassette

# Fish
hassette --generate-completion fish > ~/.config/fish/completions/hassette.fish
```

### Install to default location

`--install-completion` writes the completion script to the shell's default completion directory:

```bash
hassette --install-completion --shell zsh
```

Omitting `--shell` from either command triggers auto-detection of the current shell. Reload your shell config afterward (`source ~/.zshrc` for Zsh, `source ~/.bashrc` for Bash) or restart the terminal. To confirm it works, type `hassette ` and press Tab — available commands appear. Subcommand-specific flags complete alongside top-level commands.

## Error Handling

### Exit Codes

| Code | Meaning                                                                     |
| ---- | --------------------------------------------------------------------------- |
| `0`  | Success                                                                     |
| `1`  | Server error (4xx/5xx) or usage error (invalid flag, unknown instance name) |
| `2`  | Network error (connection refused or request timed out)                     |

### Common Errors

**Connection refused:**

```
Network error: Connection refused: http://127.0.0.1:8126 ([Errno 111] Connection refused)
```

Hassette is not running, or the configured address is wrong. The address comes from environment variables, `.env`, or `hassette.toml` — see [Discovery Order](#discovery-order) for which wins.

**Request timed out:**

```
Network error: Request timed out after 10s connecting to http://127.0.0.1:8126
```

The server is reachable but not responding. Server logs may show blocking operations.

**Unknown instance name:**

```
Usage error: Instance 'office' not found for app 'my-app'. Available instances: 'default', 'kitchen'
```

The instance name must match `hassette app` output exactly. The integer index also works — `--instance 0` selects the first instance.

### JSON Error Format

When `--json` is active, errors are written to stdout as a JSON object. Scripts can detect failures without parsing stderr.

Network error:

```json
{"error": true, "status": null, "detail": "Connection refused: http://127.0.0.1:8126 ([Errno 111] Connection refused)"}
```

Server error with HTTP status:

```json
{"error": true, "status": 503, "detail": "Service unavailable"}
```

### Debug Mode (`--debug`)

`--debug` appends the full HTTP response to error output. It applies to any command and affects only error responses. Successful responses are unchanged.

Human mode prints the request method, URL, and response body below the error message:

```
Error 500: Internal Server Error
  URL:    GET http://127.0.0.1:8126/api/health
  Body:   {"detail":"Internal Server Error","traceback":"..."}
```

JSON mode adds a `debug` key to the error object:

```json
{"error": true, "status": 500, "detail": "Internal Server Error", "debug": {"url": "http://127.0.0.1:8126/api/health", "method": "GET", "body": "{\"detail\":\"Internal Server Error\"}"}}
```

Network errors always include the target address in the default output. `--debug` does not change their format.

## Related Pages

- [CLI Overview](index.md): installation and quick start
- [Commands](commands.md): all commands and flags
- [Workflows](workflows.md): scripting patterns and `jq` recipes
