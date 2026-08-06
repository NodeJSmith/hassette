# Configuration & Scripting

## Configuration

!!! warning "Upgrading from a previous version"
    Two behaviors changed with this release, and both fail at runtime rather than at parse time — a script relying on either keeps running, but its behavior changes underneath it:

    - **`HASSETTE__WEB_API__HOST=<non-loopback-host> hassette status`** no longer sends `<data_dir>/.web_api_token`. That recipe pointed the CLI at a remote host while reading the *local* instance's token file. Replace it with `--server-url` plus `--token-file`, `cli.token_file`, or `HASSETTE__CLI__AUTH_TOKEN`.
    - **`HASSETTE__WEB_API__AUTH_TOKEN`** now applies to loopback targets only. For a remote target, set `HASSETTE__CLI__AUTH_TOKEN` instead.

    A script relying on either now either starts failing with a 401, or — against a target with `auth_enabled = false` or a matching `trusted_proxies` entry — keeps succeeding without ever sending a credential.

### Discovery Order

The CLI is a client that queries a running Hassette server. It resolves a target and a credential independently, each through its own precedence chain — the `__` double underscore in variable names separates nested config sections, so `HASSETTE__CLI__SERVER_URL` sets `cli.server_url`.

Target resolution runs highest precedence first:

1. **`--server-url` / `-s`** — a full base URL: scheme, host, port, and an optional path prefix, e.g. `https://hassette.example.com`
2. **`cli.server_url`** — the same value from `HASSETTE__CLI__SERVER_URL`, a `.env` file, or `[hassette.cli]` in [`hassette.toml`](../core-concepts/configuration/index.md)
3. **Derived from `web_api.host`/`web_api.port`** — the last resort, used only when neither the flag nor the config value is set

Bind-all addresses are rewritten for the derived path: when `web_api.host` resolves to `0.0.0.0` the CLI connects to `127.0.0.1`, and `::` becomes `::1`. The server listens on all interfaces; the CLI talks to it over loopback.

An explicit `server_url` must include a scheme (`http://` or `https://`). It must not end in `/api` — command paths already start with `/api`, so a URL ending there would double to `/api/api/health`. A trailing slash is stripped automatically, and a path prefix survives through to every request: `--server-url https://hassette.example.com/hassette` reaches `https://hassette.example.com/hassette/api/health`.

!!! tip "Remote instances"
    Point the CLI at a remote Hassette instance with `--server-url`:

    ```bash
    hassette --server-url https://hassette.example.com status
    ```

    Or persistently in `hassette.toml`:

    ```toml
    [hassette.cli]
    server_url = "https://hassette.example.com"
    ```

    A remote target needs its own authentication: a bearer credential (see [Web API Token](#web-api-token) below), or, when the remote instance trusts the proxy in front of it, a `trusted_proxies` entry that skips the credential check entirely (see [Web UI](../web-ui/index.md#enabling-and-accessing)). `web_api.host`/`web_api.port` (and `HASSETTE__WEB_API__HOST`) answer "where does the server bind?", not "where does the CLI connect?" — they no longer supply a remote target.

### Token

The access token (`HASSETTE__TOKEN`) is the long-lived HA token that `hassette run` uses to connect to Home Assistant. Query commands (`status`, `app`, `listener`, and the rest) talk to Hassette's own web API instead, which requires a separate credential of its own — see [Web API Token](#web-api-token) below.

### Web API Token

The server's web API requires authentication for every request (see [Web UI](../web-ui/index.md)). The CLI attaches its credential automatically as `Authorization: Bearer <token>`, resolved from up to five sources. Which sources apply depends on the resolved target:

| Source | Scope | Applies to |
|---|---|---|
| `--token-file` | CLI | any target |
| `cli.token_file` | CLI | any target |
| `cli.auth_token` / `HASSETTE__CLI__AUTH_TOKEN` | CLI | any target |
| `web_api.auth_token` / `HASSETTE__WEB_API__AUTH_TOKEN` | server | loopback only |
| `<data_dir>/.web_api_token` | server | loopback only |

Precedence runs top to bottom: `--token-file` wins over `cli.token_file`, which wins over `cli.auth_token`, and so on.

`web_api.*` settings describe what the local instance accepts, not what a remote one does. `web_api.auth_token` is the value the running server checks incoming requests against; `<data_dir>/.web_api_token` is the file that server wrote for itself on first start. Neither is meaningful for a different instance, so the CLI attaches them only when the resolved target is loopback (`127.0.0.1`, `::1`, or `localhost`). For any other target it skips both and falls back to a `cli.*` source. Against a non-loopback target with no `cli.*` credential configured, the CLI still sends the request rather than failing before the network call — a `trusted_proxies` deployment needs no bearer token at all, and a genuinely missing credential surfaces as a 401 naming the remedy (see [Common Errors](#common-errors)).

No CLI flag accepts a literal token value as a bare argument. `--token-file` takes a path, not a token — passing a secret directly on the command line would leave it visible in shell history and `ps` output for the life of the process. A direct value is available only through config or the environment: `cli.auth_token` or `HASSETTE__CLI__AUTH_TOKEN`.

## Letting CLI Traffic Through a Reverse Proxy

A forward-auth gateway in front of Hassette authenticates browser traffic with its own login — see [Web UI: reverse proxy](../web-ui/index.md#enabling-and-accessing) for that setup. The same gateway usually rejects the CLI's bearer token, since it expects its own login flow instead. That mismatch is what produces the [redirect error](#common-errors) below.

The fix is a second route: one that matches `/api/*` on the same subdomain, skips the gateway's login middleware, and forwards straight to Hassette. Hassette's own bearer token — resolved the same way as any other `cli.*` credential — authenticates those requests once they arrive, so the gateway's login and Hassette's token check never both apply to the same request.

This works for subdomain routing, where `cli.server_url` points at a dedicated hostname (`https://hassette.example.com`) that proxies entirely to Hassette. Path-prefix routing — one hostname serving Hassette under a subpath like `/hassette` — is supported by `server_url` (the path prefix survives through to every request, see [Discovery Order](#discovery-order)), but no worked example ships here: it has not been verified end-to-end against a path-stripping proxy.

Add `trusted_proxies` (see [Web UI](../web-ui/index.md#enabling-and-accessing)) when the gateway's own login should stand in for Hassette's — the same trust relationship the web UI section documents, extended to the `/api/*` route. It composes with a bearer token rather than replacing it: peer trust admits requests that send no `Authorization` header, and any request carrying that header is still validated against Hassette's token.

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
  "services": [
    {"name": "EventStreamService", "status": "running", "role": "service", ...},
    ...
  ],
  "version": "0.32.0",
  "boot_issues": [],
  "log_queue_drops": 9,
  "db_write_queue_drops": 2
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
Network error: Request timed out after 10.0s connecting to http://127.0.0.1:8126
```

The server is reachable but not responding. Server logs may show blocking operations. The 10-second request timeout is fixed; it is not configurable.

**Port already in use (on `hassette run`):**

```
Port 8126 is already in use — is another hassette instance running?
```

Another process — usually a second Hassette instance — holds the web API port. Stop it, or change `port` under `[hassette.web_api]`. `run` exits with code 1.

**Unknown instance name:**

```
Usage error: Instance 'office' not found for app 'my-app'. Available instances: 'default', 'kitchen'
```

The instance name must match an `instances[].instance_name` value from `hassette app --json` exactly — the default `hassette app` table shows a per-app instance count, not the names themselves. The integer index also works and needs no lookup: `--instance 0` selects the first instance.

**Unauthenticated remote request (401):**

```text
Error 401: Unauthorized (no credential was attached to this remote request. Attach one
locally via --token-file, cli.token_file, or the HASSETTE__CLI__AUTH_TOKEN environment
variable — or, if this target sits behind a forward-auth proxy, configure trusted_proxies
on the remote instance, which requires access to that host and a restart)
```

The resolved target is non-loopback and no `cli.*` credential was found, so `web_api.auth_token` and `<data_dir>/.web_api_token` were withheld — see [Web API Token](#web-api-token). Fix it locally with `--token-file`, `cli.token_file`, or `HASSETTE__CLI__AUTH_TOKEN`. Fixing it remotely means adding the proxy's address or CIDR — the peer address Hassette actually observes, not the CLI's own host — to `trusted_proxies` on the target instance (see [Letting CLI Traffic Through a Reverse Proxy](#letting-cli-traffic-through-a-reverse-proxy)). Keep that entry narrow: a broad range can let unintended peers on the same network skip the bearer-token check too.

**Redirect response (3xx):**

```text
Error 302: Found (this response is a redirect — likely a forward-auth login page in front
of the target, not Hassette itself. See the reverse-proxy section of the CLI configuration
docs.)
```

A gateway in front of the target redirected the request instead of passing it through — usually a forward-auth login page. See [Letting CLI Traffic Through a Reverse Proxy](#letting-cli-traffic-through-a-reverse-proxy) above.

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
