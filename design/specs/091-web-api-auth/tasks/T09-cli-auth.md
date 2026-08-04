---
task_id: "T09"
title: "Attach bearer token to CLI requests from file or env"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#18", "AC#14"]
---

## Summary

The `hassette` CLI currently sends no credential to the web API at all. This task makes it read the
auth token from `HASSETTE__WEB_API__AUTH_TOKEN` (env) or the token file
(`<data_dir>/.web_api_token`, the same file T02's resolution logic writes) and attach
`Authorization: Bearer <token>` to every request — matching the project's existing posture toward the
HA token (never accepted as a literal CLI argument, to avoid shell-history/`ps` exposure).

## Target Files

- modify: `src/hassette/cli/client.py` — read credential, attach header
- modify: `tests/unit/cli/test_client.py` — new tests for credential attachment
- read: `src/hassette/cli/client.py:50-64,244-252` — `HassetteCLIClient.__init__`, `make_client()`, current `HassetteConfig(token=None)` construction
- read: `tests/unit/cli/CLAUDE.md` — directory-specific test conventions (two-layer parse_args/function-call pattern)

## Prompt

Read design.md's `## Architecture → CLI` section and FR#18, plus the Convention Examples' `SecretStr`
pattern (already mirrored by T01's `auth_token` field and T02's resolution logic).

In `src/hassette/cli/client.py`, at `make_client()` (currently lines 244-252, where
`HassetteConfig(token=None)` is built for the HA token), add credential resolution for the *web API*
token, in this order:

1. `config.web_api.auth_token` — **do not read `os.environ` directly.** `make_client()` already
   constructs a full `HassetteConfig`, so once T01 adds the `auth_token` field to `WebApiConfig`,
   `HASSETTE__WEB_API__AUTH_TOKEN` populates it through the normal pydantic-settings machinery for
   free. Hand-rolling an `os.environ` lookup builds a second, divergent resolution path that silently
   ignores the config file and any `AliasChoices` the field carries — two ways to answer the same
   question, disagreeing in exactly the cases a user would file a bug about.
2. `<data_dir>/.web_api_token` — the file T02 writes. Read it directly; `data_dir` is available from
   the same `config` object.

No CLI flag should accept a literal token value as a bare argument — check `src/hassette/cli/` for
any existing `--token`-shaped argument definitions and confirm none is added for this credential.

In `HassetteCLIClient.__init__` (currently lines 50-64, where `self._client = httpx.Client(...)` is
built with no headers), attach `Authorization: Bearer <token>` to the client's default headers so
every request carries it automatically.

Read `tests/unit/cli/CLAUDE.md` before writing tests — this directory has its own documented
two-layer convention (parse_args layer + function-call layer) that test additions must follow.

## Focus

- Do not read the token via T02's full resolution function (which *generates* a token if none
  exists) — the CLI is a *consumer* of an already-resolved token, not the service that owns
  generation. If no token is configured and no file exists yet (service never started), the CLI
  should fail with a clear "no token found, has hassette been started?" error rather than silently
  generating its own token that would never match the running service's.
- `tests/unit/cli/test_client.py:79-82` already tests `HassetteCLIClient`'s `base_url` rewrite
  behavior (`0.0.0.0` → `127.0.0.1`) and is explicitly unaffected by this change — don't modify that
  test, add new ones alongside it.
- Mirror the existing HA-token posture exactly: no literal `--token <value>` CLI argument anywhere in
  `src/hassette/cli/` for this credential either.

## Verify

- [ ] FR#18: Unit test confirms `HassetteCLIClient` resolves the token from `config.web_api.auth_token` (set via `HASSETTE__WEB_API__AUTH_TOKEN` in the test environment, proving the value arrives through pydantic-settings rather than a hand-rolled `os.environ` read), falls back to the token file when the config value is `None`, and attaches `Authorization: Bearer <token>` to outgoing requests; confirms no CLI subcommand defines a bare `--token <value>` argument.
- [ ] AC#14: `hassette status` (or an equivalent CLI command) successfully authenticates using the token file or `HASSETTE__WEB_API__AUTH_TOKEN`, verified via a unit test exercising the credential-resolution + header-attachment path; `--help` output / source inspection confirms no subcommand accepts a literal token argument.
