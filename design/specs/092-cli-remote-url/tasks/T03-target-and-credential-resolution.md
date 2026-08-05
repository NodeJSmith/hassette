---
task_id: "T03"
title: "Add target and credential resolution in cli/target.py"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#7", "FR#8", "FR#15", "AC#2", "AC#3", "AC#4", "AC#6", "AC#7", "AC#16"]
---

## Summary

Create `src/hassette/cli/target.py`, the module that decides *where* the CLI connects and *which credential* it may send. This is the core of the feature. Target resolution replaces the hardcoded `f"http://{host}:{port}"`; credential resolution replaces `_resolve_cli_auth_token` and adds the scope gate that keeps local-instance credentials off remote hosts. Nothing here touches the HTTP client or the CLI flags — T04 wires those in.

## Target Files

- create: `src/hassette/cli/target.py`
- create: `tests/unit/cli/test_target.py`
- modify: `src/hassette/exceptions.py`
- read: `src/hassette/cli/client.py`
- read: `src/hassette/utils/url_utils.py`
- read: `src/hassette/utils/net_utils.py`
- read: `src/hassette/config/models.py`
- read: `design/specs/092-cli-remote-url/design.md`
- read: `design/specs/092-cli-remote-url/tasks/context.md`

## Prompt

Create `src/hassette/cli/target.py` exposing:

```python
@dataclass(frozen=True)
class ServerTarget:
    base_url: str
    is_loopback: bool
    verify_ssl: bool


@dataclass(frozen=True)
class CredentialSource:
    name: str
    scope: Literal["cli", "server"]
    resolve: Callable[..., str | None]


CREDENTIAL_SOURCES: tuple[CredentialSource, ...] = (...)  # in FR#7 precedence order


def resolve_server_target(
    config: HassetteConfig, *, server_url_flag: str | None = None, verify_ssl_flag: bool | None = None
) -> ServerTarget: ...


def resolve_cli_auth_token(
    config: HassetteConfig, target: ServerTarget, *, token_file_flag: Path | None = None
) -> str | None: ...
```

**Target resolution (FR#1).** Precedence: `server_url_flag` → `config.cli.server_url` → derived `http://{_format_host(config.web_api.host)}:{config.web_api.port}`. Import `_format_host` from `hassette.cli.client` rather than re-deriving the bind-all substitution — `_BIND_ALL_SUBSTITUTIONS` already exists in two places and must not gain a third. A blank or whitespace-only `config.cli.server_url` is treated as unset and falls through to the derived branch.

The derived branch must produce byte-identical results to today's `f"http://{host}:{port}"`, because `TestBaseUrl`'s four existing tests pin it and must pass unmodified.

**URL normalization (FR#2–FR#5).** Parse an explicitly supplied URL with `yarl.URL`, following the style in `src/hassette/utils/url_utils.py:27-42` — strip whitespace and surrounding quotes (`.strip().strip("'\"")`), one exception type per failure mode, each message echoing the offending value. **Do not call `_build_ha_url` or `_parse_and_normalize_url`**: they discard the path via `URL.build(..., path="/api/")` and reject IPv6, which would break both path-prefix support and the existing `::1` handling.

Rules: require a scheme (`http` or `https`); reject a path ending in `/api`; strip a trailing slash; drop any query string or fragment. Set `is_loopback` by calling `is_loopback_host()` from `hassette.utils.net_utils` on `yarl.URL.host` (already unbracketed, so `::1` and `[::1]` converge here). `verify_ssl` is `verify_ssl_flag` when not `None`, else `config.cli.verify_ssl`.

Add two `FatalError` subclasses to `src/hassette/exceptions.py` alongside the existing `BaseUrlRequiredError` / `IPV6NotSupportedError` / `SchemeRequiredInBaseUrlError` (lines 48-56): one for a missing scheme, one for a path ending in `/api`. The second message must name the corrected URL — the issue's own example (`https://hassette.example.com/hassette/api`) is the broken form, so a user copying it needs to be told to drop the `/api`.

**Credential resolution (FR#7, FR#8).** Build `CREDENTIAL_SOURCES` in precedence order:

| # | name | scope | source |
|---|---|---|---|
| 1 | `--token-file` | `cli` | `token_file_flag` |
| 2 | `cli.token_file` | `cli` | `config.cli.token_file` |
| 3 | `cli.auth_token` | `cli` | `config.cli.auth_token` |
| 4 | `web_api.auth_token` | `server` | `config.web_api.auth_token` |
| 5 | `<data_dir>/.web_api_token` | `server` | `config.data_dir / TOKEN_FILENAME` |

`resolve_cli_auth_token` walks this list in order and returns the first non-empty value, **skipping any entry whose `scope` is `"server"` when `target.is_loopback` is false**. It must make that decision from the `scope` field, never by naming individual sources — a sixth source added later must be gated by declaring its scope, not by someone remembering to extend a skip condition.

Blank/whitespace-only values are treated as unset at every source, matching the existing `_resolve_cli_auth_token` behavior. The CLI never generates a token.

Failure modes for the two file-backed sources differ deliberately (see `## Edge Cases` in the design doc):
- `--token-file` (flag) missing or unreadable → raise, so the caller can render a usage error naming the path. A file named on the command just typed is a fresh, attributable mistake.
- `cli.token_file` (config) missing or unreadable → fall through to the next source, matching today's behavior at `client.py:80-84`. A config path is reused unattended and goes stale in ways the operator is not present to see.

**Credential content validation (FR#15).** Before returning any resolved value, reject content that is not header-safe — fails `.isascii()` or contains control characters — by raising so the caller renders a usage error naming the source. Verified: `httpx2.Client(headers={"Authorization": "Bearer café-token"})` raises `UnicodeEncodeError` inside the constructor, before any CLI error handling runs, producing a bare traceback. A smart quote or accented character from a copy-paste, or simply pointing the flag at the wrong file, is the most likely real-world mistake with this flag.

Write `tests/unit/cli/test_target.py` covering everything above. These are pure-function tests; no HTTP client is needed.

## Focus

`resolve_server_target` returns `is_loopback` so the credential resolver does not recompute it — the classification is a property of the target, decided once where the target is built.

Neither function takes `CLIContext`. It is a cyclopts-only carrier type (`src/hassette/cli/context.py:9-19`); taking it here would make these functions untestable without fabricating one, and would block any future non-CLI caller. T04 owns the `make_client(ctx)` unpacking.

`yarl` is already available transitively via `aiohttp` (pinned 1.22.0) and is already imported in `url_utils.py`, `exceptions.py`, and `harness.py` — no new dependency.

`TOKEN_FILENAME` is importable from `hassette.web.auth`; `client.py` already does this, so the cli→web import is established and not a new boundary crossing.

Verified `httpx2` base-URL join behavior, which is why no call site needs changing:

```
'http://h:8126'                       + /api/health -> http://h:8126/api/health
'https://x.example.com/hassette'      + /api/health -> https://x.example.com/hassette/api/health
'https://x.example.com/hassette/'     + /api/health -> https://x.example.com/hassette/api/health
'https://x.example.com/hassette/api'  + /api/health -> https://x.example.com/hassette/api/api/health   ← the FR#4 hazard
```

Watch the IPv6 round-trip: `http://[::1]:8126` must survive normalization and come back out bracketed in `base_url` (an unbracketed IPv6 host in a URL is invalid), while `is_loopback` is computed from the unbracketed `yarl.URL.host`.

`config.cli.auth_token` is `SecretStr` — unwrap with `.get_secret_value()` only at the point of use, and never log the value.

## Verify

- [ ] FR#1: A unit test asserts the precedence `server_url_flag` > `config.cli.server_url` > derived-from-`web_api`, including that a blank `config.cli.server_url` falls through to the derived branch.
- [ ] FR#2: A unit test asserts `https://example.com/hassette` resolves to a `base_url` that, joined with `/api/health` by `httpx2`, yields `https://example.com/hassette/api/health`; a second asserts `http://[::1]:8126` round-trips with brackets intact in `base_url` and yields `is_loopback=True`.
- [ ] FR#3: A unit test asserts a scheme-less URL raises the missing-scheme exception with the offending value in the message.
- [ ] FR#4: A unit test asserts a URL whose path ends in `/api` raises, and that the message names the corrected form.
- [ ] FR#5: A unit test asserts `https://example.com/hassette/` and `https://example.com/hassette` produce identical `base_url` values.
- [ ] FR#7: Unit tests walk each of the five precedence tiers, including `--token-file` overriding `cli.auth_token` and `cli.auth_token` overriding `web_api.auth_token`.
- [ ] FR#8: Unit tests assert `resolve_cli_auth_token` returns `None` for a non-loopback target whose only credential is `web_api.auth_token`, and separately `<data_dir>/.web_api_token`, while returning the value for `cli.auth_token`; plus a test iterating `CREDENTIAL_SOURCES` asserting every entry declares a `scope` of `"cli"` or `"server"`.
- [ ] FR#15: A unit test asserts a token file containing a non-ASCII character raises rather than returning the value.
- [ ] AC#2: `uv run pytest tests/unit/cli/test_target.py -v` passes the path-prefix composition test.
- [ ] AC#3: `uv run pytest tests/unit/cli/test_target.py -v` passes the scheme-less and `/api`-suffix rejection tests with corrected-form assertions on the messages.
- [ ] AC#4: `uv run pytest tests/unit/cli/test_target.py -v` passes the trailing-slash normalization test.
- [ ] AC#6: `uv run pytest tests/unit/cli/test_target.py -v` passes the full credential-precedence chain.
- [ ] AC#7: `uv run pytest tests/unit/cli/test_target.py -v` passes the suppression tests and the `CREDENTIAL_SOURCES` scope-declaration test.
- [ ] AC#16: `uv run pytest tests/unit/cli/test_target.py -v` passes the non-ASCII token test, asserting the raised error names the file path.
