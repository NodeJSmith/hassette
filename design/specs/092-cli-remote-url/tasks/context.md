# Context: CLI Support for Targeting a Remote API URL

## Problem & Motivation

The `hassette` CLI can only reach a Hassette instance over plain HTTP on a bind address. `HassetteCLIClient.__init__` builds its connect target as `f"http://{host}:{port}"` from `web_api.host`/`web_api.port` — settings whose own docstrings say "Host to bind the web API server to." Reusing a bind address as a connect target is the root defect: it works for loopback, coincidentally works for a plain-HTTP LAN host, and breaks for anything else, because the scheme is a hardcoded f-string literal with no override.

This blocks the workflow PR #1521 opened up. An operator can now put Hassette behind a reverse proxy with TLS and a login, but the CLI they administer it with cannot follow it there.

A second defect rides along. `_resolve_cli_auth_token` resolves a credential from `web_api.auth_token` and then `<data_dir>/.web_api_token` and attaches it to whatever target the CLI resolves. Both describe the *local* instance. The currently documented way to query a remote instance — `HASSETTE__WEB_API__HOST=192.168.1.100 hassette status` — therefore transmits a local credential to that host, where it is both a leak and useless.

## Visual Artifacts

None.

## Key Decisions

1. **A new `[hassette.cli]` config group**, not a `web_api.client_url` field. `web_api.host`/`port` answer "where does the server bind?"; `cli.server_url` answers "where does the client connect?" Putting both on one model leaves a relationship that is genuinely hard to write a docstring for.

2. **Credential sources are a declared list, not a hand-written skip.** `CREDENTIAL_SOURCES` holds `(name, scope, resolver)` records; the resolver skips any `scope="server"` entry when the target is non-loopback, never naming individual sources. The alternative — a two-item skip condition — is the exact shape of a bug already found once in this design, where `web_api.auth_token` sat above the token file with no gate. Adding a sixth source must force a scope declaration, not require someone to remember an unwritten rule.

3. **One loopback classifier, shared.** `_is_loopback_host` moves from `core/web_api_service.py` to `utils/net_utils.py` and both the CLI and `WebApiService` import it. Two independently-written classifiers feeding the same trust decision can silently disagree about `::ffff:127.0.0.1`; that is a security bug, not a style nit.

4. **Fail open, not fast.** A non-loopback target with no credential still issues the request. Failing fast would break `trusted_proxies` deployments, where a forward-auth gateway's own authentication stands in for Hassette's and no bearer token is the correct configuration. Cost: one wasted round-trip, paid back by FR#11's error message and FR#16's target echo.

5. **Resolvers take plain keyword parameters, not `CLIContext`.** `CLIContext` is built solely by the cyclopts meta launcher. Passing it into the resolver would make "independently testable" mean "testable once you hand-build a cyclopts carrier type." `make_client(ctx)` is the single place that unpacks it.

6. **Path prefixes need no call-site changes.** `httpx2`'s `base_url` merging preserves the base path, verified directly. The one hazard is a URL ending in `/api`, which doubles to `/api/api/health` — hence FR#4's validator.

7. **Hard breaking rename, no aliases.** `hassette run --base-url`/`-u`/`--url` collapses to `--ha-url`/`-u`. Three names for one flag was the underlying confusion; keeping one alias keeps two.

## Constraints & Anti-Patterns

- **Do not reuse `_build_ha_url` or `_parse_and_normalize_url`** (`src/hassette/utils/url_utils.py`). Both discard the path via `URL.build(..., path="/api/")`, destroying path-prefix support, and `_parse_and_normalize_url` rejects IPv6 outright, regressing the CLI's existing `::1` handling. Reuse the *style*, not the functions.
- **Do not write a second loopback classifier.** Move `_is_loopback_host` to `utils/net_utils.py` and import it in both places. The reason it can't be imported from `core/web_api_service.py` directly is layering (a `Service`-layer module), not semantics.
- **Do not add a third copy of the bind-all substitution map.** `_BIND_ALL_SUBSTITUTIONS` already exists in `cli/client.py:26-30` and `web/auth.py:63-73`. Route through the `cli/client.py` copy.
- **Do not resolve DNS to classify loopback.** A DNS answer can change between classification and request. Literal matching fails safe.
- **Do not accept a bare token value as a CLI argument.** No `--auth-token` flag. `--token-file` takes a path; `cli.auth_token` is config/env only.
- **Do not set `follow_redirects=True`.** A forward-auth login redirect must surface as a clear error, not silently follow to an HTML login page that then fails JSON parsing.
- **Do not modify `TestBaseUrl`'s four existing tests.** They are the regression signal that the zero-config local path is unchanged.
- **Do not write new local `make_*`/`build_*` test builders.** Extend `CLIClientFactory` and `_make_config_for_auth` in `tests/unit/cli/conftest.py` — see `.claude/rules/test-conventions.md`.
- **Non-goals:** server-side path-prefix (`root_path`) support; reconsidering web API token auto-generation; a CLI WebSocket/follow transport; named multi-instance profiles in one config file; changing #1117's reverse-proxy guidance.

## Design Doc References

- `## Problem` — the bind-vs-connect conflation and the credential-scoping defect that rides along
- `## Functional Requirements` — FR#1 through FR#17, the authoritative behavior list
- `## Acceptance Criteria` — AC#1 through AC#20, each verifiable by a local command
- `## Edge Cases` — IPv6 literals, blank values, unreadable token files, the `--token-file` vs `cli.token_file` split
- `## Key Constraints` — the prohibitions reproduced above, with their reasons
- `## Architecture → Where the target lives` — the `CliConfig` group and why the group label goes on `model_config`
- `## Architecture → Global flags` — the three new flags, the `-s` availability check, and the `--url` collision
- `## Architecture → Resolution` — `cli/target.py`, `ServerTarget`, and the plain-parameter signatures
- `## Architecture → Path prefixes are free` — the verified `httpx2` join table
- `## Architecture → Credential scoping` — the scope table, `CREDENTIAL_SOURCES`, and why gating only the file was a half-measure
- `## Architecture → Failing open, not fast` — the `trusted_proxies` argument and today's `--debug`-gated URL echo
- `## Architecture → Transport` — `verify=`, redirects, and the config-vs-flag warning split
- `## Replacement Targets` — what to remove rather than leave alongside new code
- `## Test Strategy` — required layers, tests to adapt, new coverage mapped to FRs
- `## Documentation Updates` — the four docs pages and what each needs
- `## Impact → Behavioral Invariants` — what must not change, and the three deliberate breaks

## Convention Examples

### Nested config group

**Source:** `src/hassette/config/models.py:538-549`

```python
class FileWatcherConfig(ExcludeExtrasMixin, BaseModel):
    """File watcher debounce, step, and enable/disable settings."""

    debounce_milliseconds: int = Field(default=3000)
    """Debounce time for file watcher events in milliseconds."""

    step_milliseconds: int = Field(default=500)
    """Time to wait for additional file changes before emitting event in milliseconds."""

    watch_files: bool = Field(default=True)
    """Whether to watch files for changes and reload apps automatically."""
```

Docstrings go *below* each field as bare string literals, not in a `description=` kwarg. Every field uses `Field(default=...)` even when a bare default would do.

### Lazy URL parsing with dedicated exceptions

**Source:** `src/hassette/utils/url_utils.py:27-42`

```python
if not config.base_url:
    raise BaseUrlRequiredError(f"base_url must be set in the configuration, got: {config.base_url}")

cleaned_url = config.base_url.strip().strip("'\"")
yurl = URL(cleaned_url)

if not yurl.scheme:
    raise SchemeRequiredInBaseUrlError(f"base_url must include a scheme (http:// or https://), got: {cleaned_url}")
```

One exception type per failure mode, each message echoing the offending value. Note the `.strip("'\"")` — quoted values arrive from `.env` files and are stripped defensively. Follow the style; do not call these functions (see Key Constraints).

### Global flag declaration on the meta launcher

**Source:** `src/hassette/cli/__init__.py:117-131`

```python
@app.meta.default
def launcher(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    config_file: Annotated[
        str | None, Parameter(name=["--config-file", "-c"], help="Path to the TOML configuration file.")
    ] = None,
    json: Annotated[bool, Parameter(name=["--json"], help="Output results as JSON.", negative=[])] = False,
) -> None:
```

Explicit `name=[...]` lists including the short form. `negative=[]` on booleans suppresses cyclopts' auto-generated `--no-*` variant — omit it on `--no-verify-ssl`, where the negative form *is* the flag.

### Credential test shape

**Source:** `tests/unit/cli/test_client.py` (`TestCredentialAttachment`)

```python
def test_falls_back_to_token_file_when_config_value_absent(self, tmp_path: Path) -> None:
    (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
    factory = CLIClientFactory(_make_config_for_auth(tmp_path))
    client, captured_headers = factory.build_capturing_headers()
    client.get(HEALTH_ENDPOINT, dict)
    assert captured_headers[0]["authorization"] == "Bearer file-token"
```

Credential assertions read the captured request header, never an internal attribute. Extend `CLIClientFactory` and `_make_config_for_auth` rather than writing new local builders — see `.claude/rules/test-conventions.md`.
