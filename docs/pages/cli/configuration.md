# Configuration & Scripting

## Configuration

!!! warning "Upgrading from a previous version"
    Three behaviors changed with this release, and all fail at runtime rather than at parse time — a script relying on any of them keeps running, but its behavior changes underneath it:

    - **`HASSETTE__WEB_API__HOST=<non-loopback-host> hassette status`** no longer sends `<data_dir>/.web_api_token`. That recipe pointed the CLI at a remote host while reading the *local* instance's token file. Replace it with `--server-url` plus `--token-file`, `cli.token_file`, or `HASSETTE__CLI__AUTH_TOKEN`.
    - **`HASSETTE__WEB_API__AUTH_TOKEN`** no longer reaches a remote target. Set `HASSETTE__CLI__AUTH_TOKEN` instead.
    - **A second instance on the same machine** no longer receives `web_api.auth_token` or `web_api.token_file`. Those sources now require a loopback target whose port equals `web_api.port`. Use `--token-file`, `cli.token_file`, or `HASSETTE__CLI__AUTH_TOKEN` for that instance.

    A script relying on any of them now either starts failing with a 401, or — against a target with `auth_enabled = false` or a matching `trusted_proxies` entry — keeps succeeding without ever sending a credential.

### Discovery Order

The CLI is a client that queries a running Hassette server. It resolves a target and a credential independently, each through its own precedence chain — the `__` double underscore in variable names separates nested config sections, so `HASSETTE__CLI__SERVER_URL` sets `cli.server_url`.

Target resolution runs highest precedence first:

1. **`--server-url` / `-s`** — a full base URL: scheme, host, port, and an optional path prefix, e.g. `https://hassette.example.com`
2. **`cli.server_url`** — the same value from `HASSETTE__CLI__SERVER_URL`, a `.env` file, or `[hassette.cli]` in [`hassette.toml`](../core-concepts/configuration/index.md)
3. **Derived from `web_api.host`/`web_api.port`** — the last resort, used only when neither the flag nor the config value is set

Bind-all addresses are rewritten for the derived path: when `web_api.host` resolves to `0.0.0.0` the CLI connects to `127.0.0.1`, and `::` becomes `::1`. The server listens on all interfaces; the CLI talks to it over loopback.

An explicit `server_url` must include a scheme (`http://` or `https://`). It must not end in `/api` — command paths already start with `/api`, so a URL ending there would double to `/api/api/health`. A trailing slash is stripped automatically, and a path prefix survives through to every request: `--server-url https://hassette.example.com/hassette` reaches `https://hassette.example.com/hassette/api/health`.

!!! tip "Remote instances"
    A remote target needs its own credential: the remote instance's web API token. That instance writes it to `<data_dir>/.web_api_token` on first start, or reads it from its own `web_api.auth_token`. Copy that value into a file on the CLI's machine, then pass the file with `--token-file`:

    ```bash
    hassette --server-url https://hassette.example.com --token-file ~/.config/hassette/remote-token status
    ```

    Or persistently in `hassette.toml`:

    ```toml
    [hassette.cli]
    server_url = "https://hassette.example.com"
    token_file = "/home/me/.config/hassette/remote-token"
    ```

    `cli.token_file` expands `~`. A relative path resolves against the directory of the file that sets it, or the working directory for an environment variable.

    A remote instance that trusts the proxy in front of it needs no token. Its `trusted_proxies` entry skips the credential check (see [Web UI](../web-ui/index.md#enabling-and-accessing)).

    `web_api.host` and `web_api.port` still supply a target when no `server_url` is set: `HASSETTE__WEB_API__HOST=192.0.2.1 hassette status` connects to `192.0.2.1`. That target receives no server-scoped credential (`web_api.auth_token`, `web_api.token_file`), so it needs a `cli.*` credential like any other remote target. Use `--server-url` for remote instances; `web_api.*` describes where the local server binds.

### Token

The access token (`HASSETTE__TOKEN`) is the long-lived HA token that `hassette run` uses to connect to Home Assistant. Query commands (`status`, `app`, `listener`, and the rest) talk to Hassette's own web API instead, which requires a separate credential of its own — see [Web API Token](#web-api-token) below.

### Web API Token

The server's web API requires authentication for every request except three: the two health probes (`GET /api/health/live`, `GET /api/health/ready`) and `POST /api/auth/session` (see [Web UI](../web-ui/index.md)). The CLI attaches its credential automatically as `Authorization: Bearer <token>`, resolved from up to five sources. Which sources apply depends on the resolved target:

| Source | Scope | Applies to |
|---|---|---|
| `--token-file` | CLI | any target |
| `cli.token_file` | CLI | any target |
| `cli.auth_token` / `HASSETTE__CLI__AUTH_TOKEN` | CLI | any target |
| `web_api.auth_token` / `HASSETTE__WEB_API__AUTH_TOKEN` | server | loopback target on `web_api.port` |
| `web_api.token_file` (default `<data_dir>/.web_api_token`) | server | loopback target on `web_api.port` |

Precedence runs top to bottom: `--token-file` wins over `cli.token_file`, which wins over `cli.auth_token`, and so on.

`web_api.*` settings describe what the local instance accepts, not what a remote one does. `web_api.auth_token` is the value the running server checks incoming requests against; `web_api.token_file` is the file that server reads its token from, and writes on first start if it's missing or empty (`<data_dir>/.web_api_token` unless configured). Neither is meaningful for a different instance, so the CLI attaches them only when the resolved target is loopback (any `127.0.0.0/8` address, `::1`, `localhost`, or an IPv4-mapped form such as `::ffff:127.0.0.1`) and its port equals `web_api.port`. For any other target it skips both and falls back to a `cli.*` source. That includes a second instance on the same machine, which shares the host but listens on its own port. Against a non-loopback target with no `cli.*` credential configured, the CLI still sends the request rather than failing before the network call — a `trusted_proxies` deployment needs no bearer token at all, and a genuinely missing credential surfaces as a 401 naming the remedy (see [Common Errors](#common-errors)).

A `server_url` with `user:password@` userinfo conflicts with a resolved credential. The CLI sends userinfo as Basic authentication, and a request carries only one `Authorization` header. When both are present, the CLI exits with a usage error before sending anything (see [Common Errors](#common-errors)). Remove the userinfo from `server_url`, or remove the token setting.

No CLI flag accepts a literal token value as a bare argument. `--token-file` takes a path, not a token — passing a secret directly on the command line would leave it visible in shell history and `ps` output for the life of the process. A direct value is available only through config or the environment: `cli.auth_token` or `HASSETTE__CLI__AUTH_TOKEN`.

## Letting CLI Traffic Through a Reverse Proxy

A forward-auth gateway in front of Hassette authenticates browser traffic with its own login — see [Web UI: reverse proxy](../web-ui/index.md#enabling-and-accessing) for that setup. The same gateway usually rejects the CLI's bearer token, since it expects its own login flow instead. That mismatch is what produces the [redirect error](#common-errors) below.

The fix is a second route: one that matches `/api/*` on the same subdomain, skips the gateway's login middleware, and forwards straight to Hassette. Hassette's own bearer token — resolved the same way as any other `cli.*` credential — authenticates those requests once they arrive, so the gateway's login and Hassette's token check never both apply to the same request.

In Caddy, the bypass is a `handle /api/*` block placed ahead of the forward-auth catch-all. `authelia:9091` and its `uri` stand in for whichever gateway already guards the browser route:

```caddyfile title="Caddyfile"
--8<-- "pages/web-ui/snippets/reverse-proxy-caddy-cli-bypass.txt"
```

With the bypass in place, `hassette --server-url https://hassette.example.com status` returns the status panel instead of `Error 302`.

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
    {"name": "EventStreamService", "status": "running", ...},
    ...
  ],
  "version": "0.32.0",
  "boot_issues": [],
  "log_queue_drops": 9,
  "db_write_queue_drops": 2
}
```

In `--json` mode:

- stdout contains exactly one JSON document, either the success result or an error object. Argument parse errors are the exception: an invalid flag or unknown command leaves stdout empty and exits `2` (see [Exit Codes](#exit-codes)).
- Exit code distinguishes success (`0`) from failure (`1` for HTTP and usage errors, `2` for network and argument parse errors)
- No Rich formatting or human-readable text appears on stdout
- On success, stderr shows a `Target:` line naming a non-loopback instance that answered. It also shows a warning whenever `cli.verify_ssl = false` turns off TLS verification, for any target. On failure, these move into the error object as `target` and `tls_verified` (see [JSON Error Format](#json-error-format)). Human mode prints both lines on stderr on success and on HTTP errors. Human-mode network errors print only the TLS warning, not the `Target:` line.

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
mkdir -p ~/.zsh/completions
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

For Zsh, `--install-completion` writes to `~/.zsh/completions`, the same directory as the example above. Zsh loads completions only from directories on `fpath`, and Hassette never edits `~/.zshrc`. Add the directory to `fpath` in `~/.zshrc`, above the line that runs `compinit`:

```zsh
fpath=(~/.zsh/completions $fpath)
autoload -Uz compinit && compinit
```

Under oh-my-zsh, `--install-completion` writes to its custom completions directory instead, which is already on `fpath`.

Omitting `--shell` from either command triggers auto-detection of the current shell. Reload your shell config afterward (`source ~/.zshrc` for Zsh, `source ~/.bashrc` for Bash) or restart the terminal. To confirm it works, type `hassette ` and press Tab — available commands appear. Subcommand-specific flags complete alongside top-level commands.

## Error Handling

### Exit Codes

| Code | Meaning                                                                                                        |
| ---- | -------------------------------------------------------------------------------------------------------------- |
| `0`  | Success                                                                                                        |
| `1`  | Server error (4xx/5xx) or Hassette usage error (unknown instance name, conflicting config)                     |
| `2`  | Network error (connection refused or request timed out) or argument parse error (invalid flag, unknown command) |

The CLI parser rejects an invalid flag or unknown command before any Hassette code runs. It prints the error to stderr and exits `2`, even in `--json` mode. Scripts that need to tell a parse error from a network error check stdout: a network error writes a JSON error object there, a parse error writes nothing.

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

The server accepted the connection but did not respond in time, or the connection itself timed out. A connect timeout usually means an unreachable address, such as a firewalled host. A server that accepted the connection may be blocked; its logs may show blocking operations. The 10-second request timeout is fixed; it is not configurable.

**Port already in use (on `hassette run`):**

```
Web API could not bind to 0.0.0.0:8126 — is the port already in use (another hassette instance running?) or the host not a local address?
```

Another process — usually a second Hassette instance — holds the web API port. Stop it, or change `port` under `[hassette.web_api]`. Hassette shuts down cleanly, records the session as failed, and `run` exits with code 1.

**Unknown instance name:**

```
Usage error: Instance 'office' not found for app 'my-app'. Available instances: 'default', 'kitchen'
```

The instance name is required and unique for every configured instance, and must match an existing instance name exactly. [`hassette app instances <key>`](commands.md#hassette-app-instances-key) lists each instance by name. A number isn't a name: `--instance 0` fails the same way, listing the available instances.

**Authentication failure (401):**

Every 401 names the credential the CLI actually sent — or says that none was attached — and the remedies that apply. Which of the four variants appears depends on what resolved.

A credential resolved and was rejected:

```text
Error 401: Not authenticated (the credential sent came from web_api.token_file
(/data/.web_api_token — this machine's instance), and it was rejected. Point the CLI at
the target's own credential with --token-file, cli.token_file, or
HASSETTE__CLI__AUTH_TOKEN. See
https://hassette.readthedocs.io/en/stable/pages/cli/configuration/#web-api-token)
```

The named source is the diagnosis. `web_api.token_file` and `web_api.auth_token` belong to *this machine's* instance, and they reach only a loopback target on `web_api.port`. When the source named is one of those, the instance answering that port doesn't accept the value. Its configured token and the CLI's copy disagree, or another process holds the port. Against a remote target this variant adds one caveat: a forward-auth proxy in front of the target can answer 401 itself, so the rejection is not necessarily Hassette's.

Nothing resolved against the local instance:

```text
Error 401: Not authenticated (no credential was attached — nothing in the credential chain
resolved to a usable value (--token-file, cli.token_file, cli.auth_token,
web_api.auth_token, web_api.token_file). If one of those is configured, check that
the file exists, is readable, and is not empty; otherwise, has hassette been started?
Attach one with --token-file, cli.token_file, or HASSETTE__CLI__AUTH_TOKEN. See
https://hassette.readthedocs.io/en/stable/pages/cli/configuration/#web-api-token)
```

Usually the server has not started yet — it writes its token file (`<data_dir>/.web_api_token` by default) on first start. A running server paired with this message means the CLI resolved a different `data_dir` or `web_api.token_file` than the server uses, which an explicit credential settles.

The message names the whole chain rather than asserting which entries are unset, because it cannot tell the difference: a `cli.token_file` or `web_api.token_file` that is missing, unreadable, or empty falls through to the next source silently, exactly like one that was never configured. Check the file before concluding the setting is absent.

Nothing resolved against another port on this machine:

```text
Error 401: Not authenticated (no credential was attached — server-scoped sources
(web_api.auth_token, web_api.token_file) describe this machine's instance and are sent
only to a loopback target on web_api.port, which this target's port does not match.
Attach one with --token-file, cli.token_file, or HASSETTE__CLI__AUTH_TOKEN. See
https://hassette.readthedocs.io/en/stable/pages/cli/configuration/#web-api-token)
```

The target is a different instance from the one `web_api.port` describes, so the CLI withheld the local credential. Pass that instance's own token with `--token-file`, `cli.token_file`, or `HASSETTE__CLI__AUTH_TOKEN`. A port-mapped container is the same case when its published port differs from `web_api.port`.

Nothing resolved against a remote target:

```text
Error 401: Not authenticated (no credential was attached to this remote request —
server-scoped sources (web_api.auth_token, web_api.token_file) describe this
machine's instance and are never sent to a remote target. Attach one locally with
--token-file, cli.token_file, or HASSETTE__CLI__AUTH_TOKEN — or, if this target sits
behind a forward-auth proxy, configure trusted_proxies on the remote instance, which
requires access to that host and a restart. See
https://hassette.readthedocs.io/en/stable/pages/cli/configuration/#web-api-token)
```

The resolved target is non-loopback and no `cli.*` credential was found, so `web_api.auth_token` and `web_api.token_file` were withheld — see [Web API Token](#web-api-token). Fix it locally with `--token-file`, `cli.token_file`, or `HASSETTE__CLI__AUTH_TOKEN`. Fixing it remotely means adding the proxy's address or CIDR — the peer address Hassette actually observes, not the CLI's own host — to `trusted_proxies` on the target instance (see [Letting CLI Traffic Through a Reverse Proxy](#letting-cli-traffic-through-a-reverse-proxy)). Keep that entry narrow: a broad range can let unintended peers on the same network skip the bearer-token check too.

**Userinfo and token both configured:**

```text
Usage error: server_url carries user:password credentials and a hassette token is also
configured; a request can carry only one Authorization header. Remove one of them.
```

The resolved `server_url` contains `user:password@` (or just `user@` or `:password@`), and a credential also resolved from the chain in [Web API Token](#web-api-token). Drop the userinfo when Hassette's bearer token is the credential the target expects. Drop the token setting when a proxy in front of the target authenticates with Basic auth instead.

**Redirect response (3xx):**

```text
Error 302:  (this response is a redirect — likely a forward-auth login page in front of
the target, not Hassette itself. See the reverse-proxy section of the CLI configuration
docs.)
```

The text after `Error 302:` is the response body, not a reason phrase. A redirect body is often empty, as above, or an HTML page. A gateway in front of the target redirected the request instead of passing it through — usually a forward-auth login page. See [Letting CLI Traffic Through a Reverse Proxy](#letting-cli-traffic-through-a-reverse-proxy) above.

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
  Body:   {"type":"about:blank","title":"Internal Server Error","status":500,"detail":"Internal Server Error","code":"internal_error"}
```

JSON mode adds a `debug` key to the error object:

```json
{"error": true, "status": 500, "detail": "Internal Server Error", "debug": {"url": "http://127.0.0.1:8126/api/health", "method": "GET", "body": "{\"type\":\"about:blank\",\"title\":\"Internal Server Error\",\"status\":500,\"detail\":\"Internal Server Error\",\"code\":\"internal_error\"}"}}
```

Connection-refused and timeout errors include the target address in the default output. `--debug` does not change the format of any network error.

The body is the server's problem details response. [API Error Responses](../web-ui/api-errors.md) lists every `code` it can carry.

## Related Pages

- [CLI Overview](index.md): installation and quick start
- [Commands](commands.md): all commands and flags
- [Workflows](workflows.md): scripting patterns and `jq` recipes
