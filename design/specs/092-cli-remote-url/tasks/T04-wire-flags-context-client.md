---
task_id: "T04"
title: "Wire global flags, CLIContext, and the HTTP client"
status: "planned"
depends_on: ["T03", "T05"]
implements: ["FR#6", "FR#10", "FR#11", "FR#12", "FR#14", "FR#16", "FR#17", "AC#1", "AC#5", "AC#9", "AC#10", "AC#11", "AC#17", "AC#18", "AC#20"]
---

## Summary

Connect the resolver from T03 to the actual CLI: three new global flags, three new `CLIContext` fields, and a `HassetteCLIClient` that builds its base URL and credential from `resolve_server_target` / `resolve_cli_auth_token` instead of inline construction. Also adds the transport and error-reporting behavior that makes remote failures diagnosable — TLS verification, redirect detection, target echoing, and an actionable 401.

## Target Files

- modify: `src/hassette/cli/context.py`
- modify: `src/hassette/cli/__init__.py`
- modify: `src/hassette/cli/client.py`
- modify: `tests/unit/cli/conftest.py`
- modify: `tests/unit/cli/test_client.py`
- modify: `tests/unit/cli/test_context.py`
- modify: `tests/unit/cli/test_parse_args.py`
- read: `tests/unit/cli/CLAUDE.md`
- read: `src/hassette/cli/target.py`
- read: `src/hassette/core/web_api_service.py`
- read: `design/specs/092-cli-remote-url/design.md`
- read: `design/specs/092-cli-remote-url/tasks/context.md`

## Prompt

**`CLIContext` (`src/hassette/cli/context.py`).** Add three fields to the frozen dataclass, which currently holds only `json_mode` and `debug_mode`:

- `server_url: str | None = None`
- `token_file: Path | None = None`
- `verify_ssl: bool | None = None`

`verify_ssl` is tri-state on purpose: `None` means "flag not passed, defer to config," which is what lets `resolve_server_target` distinguish an explicit `--no-verify-ssl` from an unset flag.

**Global flags (`src/hassette/cli/__init__.py`).** Add three parameters to the `@app.meta.default` launcher, following the existing `name=[...]` convention:

| Flag | Short | Maps to |
|---|---|---|
| `--server-url` | `-s` | `ctx.server_url` |
| `--token-file` | — | `ctx.token_file` |
| `--no-verify-ssl` | — | `ctx.verify_ssl = False` |

`-s` is free — the only short flags in use are `-c`, `-e`, `-v` (meta) and `-a`, `-t`, `-u` (subcommands). `--token-file` gets no short flag because `-t` is `hassette run --token`. On `--no-verify-ssl`, **omit** `negative=[]` — unlike the existing boolean flags, the negative form *is* the flag here.

Do **not** add an `--auth-token` flag. A flag taking a literal secret would leave it in shell history and `ps` output; `cli.auth_token` is config/env only.

Pass the new values into the `CLIContext` constructed in the launcher body.

**`HassetteCLIClient.__init__` (`src/hassette/cli/client.py`).** Replace the inline URL build at lines 98-100 and the `_resolve_cli_auth_token` call at line 104 with calls into `cli/target.py`. Delete `_resolve_cli_auth_token` outright — no shim. Keep `_BIND_ALL_SUBSTITUTIONS`, `_substitute_host`, and `_format_host` where they are; T03 imports `_format_host`.

`make_client(ctx)` is the single place that unpacks the context into keyword arguments:

```python
target = resolve_server_target(config, server_url_flag=ctx.server_url, verify_ssl_flag=ctx.verify_ssl)
token = resolve_cli_auth_token(config, target, token_file_flag=ctx.token_file)
```

The client stores `self.base_url = target.base_url` and passes `verify=target.verify_ssl` to `httpx.Client(...)` (FR#6), which takes no `verify=` today. Leave `follow_redirects` at its default `False` (verified).

Catch the validation exceptions T03 raises (missing scheme, `/api` suffix, unreadable `--token-file`, non-header-safe credential) and route them through the existing `error_usage()` path so they render as usage errors rather than tracebacks. Set `json_mode` before any validation runs so the error renders in the right format.

**Error and observability behavior:**

- **FR#11 (401).** When a 401 arrives and a server-scoped source was suppressed, the message must separate remedies by where they apply: attaching a credential locally (`--token-file`, `cli.token_file`, `HASSETTE__CLI__AUTH_TOKEN`) versus configuring `trusted_proxies` on the **remote instance**, which needs access to that host and a restart. Do not emit one flat list — `trusted_proxies` is not something the reader can act on at the terminal where the error just printed. The existing `self._token_resolved` flag and the 401 branch at `client.py:260-264` are the hook.
- **FR#12 (3xx).** Add a 3xx branch to `_handle_http_error` identifying the response as a redirect, naming a forward-auth login redirect as the likely cause, and pointing at the reverse-proxy section of the CLI docs. Diagnosis alone is not enough — "forward auth" may be a new term to the affected reader.
- **FR#14.** Error messages report the full resolved base URL including scheme and path prefix. `_handle_network_error` already interpolates `self.base_url`; confirm the prefixed form survives.
- **FR#16.** When `target.is_loopback` is false, surface the target once per invocation on **both** paths: a `Target: <base_url>` line on stderr in human mode, a `"target"` key in the JSON envelope. Note what exists today: `_handle_network_error` echoes the URL unconditionally (`client.py:151-155`), but `_handle_http_error` only does so when `--debug` is set (`client.py:266-273`). So the HTTP-error echo must become unconditional for non-loopback targets, and the success-path echo is entirely new. Loopback stays silent on both.
- **FR#17.** When `verify_ssl` is false **and sourced from config rather than the `--no-verify-ssl` flag**, warn: a stderr line naming the unverified target in human mode, `"tls_verified": false` in JSON mode. The flag is a conscious per-invocation choice and does not need the nag; a value persisted in a profile does, because it silently keeps applying after `cli.server_url` is repointed. Follow the precedent in `WebApiService.on_initialize()` (`core/web_api_service.py:115-121`).

**Tests.** Extend `CLIClientFactory` and `_make_config_for_auth` in `tests/unit/cli/conftest.py` to accept a `CLIContext` and to build non-loopback targets. Do **not** write new local `make_*`/`build_*` builders — `tools/check_test_factories.py` flags those, and `.claude/rules/test-conventions.md` requires extending the shared ones.

`tests/unit/cli/test_context.py` asserts `CLIContext()` defaults for the two existing fields; add assertions for the three new ones alongside them.

**Wiring tests are mandatory here.** `tests/unit/cli/CLAUDE.md` requires a `parse_args` test for every new flag, and documents why: a `--since 7d` bug shipped because every test called the command function directly with pre-converted values, so the cyclopts layer bridging user input to the function was never executed. Three new global flags is exactly that risk. Add cases to `tests/unit/cli/test_parse_args.py` using `app.meta.parse_args(argv)` (the global-flag form — `app.parse_args` is for subcommand flags), extending the existing `TestGlobalFlagWiring` class rather than starting a new one. Cover `--server-url`, `-s`, `--token-file`, and `--no-verify-ssl`, asserting each lands on the resulting `CLIContext` with the right type — including that `--no-verify-ssl` yields `verify_ssl=False` while its absence yields `None`, not `True`.

## Focus

**`TestBaseUrl`'s four tests in `tests/unit/cli/test_client.py` must pass completely unmodified.** They are the regression signal that the zero-config local path is byte-identical. If they need editing, the derived fallback in T03 is wrong — fix that rather than the tests.

`TestCredentialAttachment`'s twelve tests use `_make_config_for_auth(tmp_path)`, which builds a loopback target, so they stay green as-is. Extend the helper for the non-loopback cases rather than changing its default.

`tests/unit/cli/test_context.py:16-19` (`TestCLIContextDefaults.test_defaults`) currently asserts exactly two fields — it will not fail when fields are added, but leaving it unextended means the new defaults are untested. This was flagged by the plan's reverse-dependency gap check.

Six command modules import `make_client` (`app.py`, `job.py`, `listener.py`, `log.py`, `misc.py`, `status.py`) — none should need changes, since the signature `make_client(ctx)` is unchanged. Confirm with `grep -rn "make_client" src/hassette/cli/commands/` after the change.

`tests/system/test_cli_smoke.py:67` hardcodes `f"http://127.0.0.1:{port}"` and must keep passing untouched — it exercises the derived path against a real server.

Credential assertions read the captured request header, never an internal attribute — see the Convention Examples in `context.md`.

## Verify

- [ ] FR#6: A unit test asserts `httpx.Client` receives `verify=False` when `cli.verify_ssl` is false and `verify=True` by default.
- [ ] FR#10: A unit test asserts the transport receives a request for a non-loopback target with no resolvable credential, rather than the CLI exiting before the call.
- [ ] FR#11: A unit test asserts the 401 message names `--token-file`, `cli.token_file`, `HASSETTE__CLI__AUTH_TOKEN`, and `trusted_proxies`, and that the `trusted_proxies` mention is qualified as applying to the remote instance.
- [ ] FR#12: A unit test asserts a 302 response produces an error mentioning a redirect, forward auth, and a docs pointer.
- [ ] FR#14: A unit test asserts a network error and an HTTP error against `https://example.com/hassette` each report that full base URL.
- [ ] FR#16: Unit tests assert the target appears on a successful non-loopback request, is absent on a successful loopback request, and appears on a 401 against a non-loopback target **without** `--debug`.
- [ ] FR#17: A unit test asserts a config-sourced `verify_ssl=false` emits the warning while the `--no-verify-ssl` flag does not.
- [ ] AC#1: `uv run pytest tests/unit/cli/test_client.py tests/unit/cli/test_parse_args.py tests/unit/cli/test_context.py -v` passes, with `TestBaseUrl`'s four tests unmodified (`git diff` shows no change to that class) and new `app.meta.parse_args` cases covering `--server-url`, `-s`, `--token-file`, and `--no-verify-ssl`.
- [ ] AC#5: The `verify=` assertions from FR#6 pass.
- [ ] AC#9: The request-issued assertion from FR#10 passes.
- [ ] AC#10: The 401 message assertion from FR#11 passes, asserted on the qualifying phrase rather than substring presence alone.
- [ ] AC#11: The 302 message assertion from FR#12 passes.
- [ ] AC#17: The three target-surfacing assertions from FR#16 pass.
- [ ] AC#18: The `verify_ssl` warning assertion from FR#17 passes.
- [ ] AC#20: The full-base-URL assertions from FR#14 pass.
