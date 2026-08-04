---
task_id: "T02"
title: "Add auth exceptions and token resolution/persistence logic"
status: "planned"
depends_on: ["T01"]
implements: ["FR#9", "FR#10", "FR#21", "AC#12", "AC#19"]
---

## Summary

Creates `src/hassette/web/auth.py` (new file) with the token-resolution mechanism: on first start
with no configured token and no existing token file, generate one, persist it atomically, and log
which of the three resolution branches fired. A corrupt or unreadable existing token file is treated
as "no file" rather than crashing the service. Also adds the new auth-related exception classes to
`src/hassette/exceptions.py` that this and later tasks (T03-T08) raise.

## Target Files

- create: `src/hassette/web/auth.py` — token resolution, atomic write, corrupt-file recovery, branch logging
- modify: `src/hassette/exceptions.py` — new `HassetteError` subclasses for auth failures
- create: `tests/unit/web/test_auth.py` — unit tests for token resolution
- read: `src/hassette/exceptions.py:36-37,40-44,89-94,140-141,152-169` — exception hierarchy conventions (do NOT reuse `InvalidAuthError`, lines 140-141)
- read: `src/hassette/config/config.py:142-151,248-256` — `SecretStr` field pattern already mirrored by T01's `auth_token` field

## Prompt

Read design.md's `## Architecture → Credential model` (second paragraph, on token resolution) and
FR#9, FR#10, FR#21, plus the Edge Cases entry "Token file write failure" and "Corrupt or unreadable
existing token file."

In `src/hassette/exceptions.py`, add new plain `HassetteError` subclasses (not `FatalError` — an auth
failure must not crash or block-restart `WebApiService`) for the failure modes this task and later
tasks need, following the mostly-docstring-only convention at lines 152-169 (e.g.
`InvalidInheritanceError`). At minimum: an exception for "token file could not be written" (used when
the Edge Case "Token file write failure" applies — startup must fail loudly, naming the exact path
and OS error, not silently fall back to an ephemeral token). Insert these as a new block after
`InvalidAuthError` (~line 142) or at file end. **Do not reuse or subclass `InvalidAuthError`** — it
means "HA rejected hassette's own outbound token" and is wired into `websocket_service.py`'s
`NON_RETRYABLE` tuple; reusing it here would misroute an unrelated failure mode into that handling
path.

In the new `src/hassette/web/auth.py`, implement token resolution as a function (e.g.
`resolve_auth_token(config: WebApiConfig, data_dir: Path) -> str`) that tries, in order:

1. `config.auth_token.get_secret_value()` if explicitly configured (non-`None`).
2. Read `<data_dir>/.web_api_token`. If it exists and is readable, use its contents. If it exists but
   is corrupt/unreadable (empty, wrong permissions causing a read error, garbage content), treat this
   identically to "no file exists" — log an ERROR making the regeneration visible (FR#10), then fall
   through to step 3. Do not crash.
3. Generate a fresh token via `secrets.token_urlsafe(32)`, persist it atomically to
   `<data_dir>/.web_api_token` (write to a temp file in the same directory, then `os.replace()`, mode
   `0600`). If the write fails (permissions, read-only filesystem, full disk), fail loudly — raise
   the new exception from `exceptions.py` naming the exact path and OS error; do not silently return
   an in-memory-only token (per the Edge Case: every `WebApiService` restart, being
   `RestartType.TRANSIENT`, would otherwise mint a new token and invalidate whatever the operator
   just configured).

Whichever branch fires (1, 2, or 3), log at INFO with a distinct, identifiable message per branch
(FR#21) — e.g. "using configured auth_token", "loaded existing token from <path>", "generated new
auth_token, written to <path>" — via the existing `"hassette"` logger (`getLogger(__name__)`
convention). This logging must fire on every startup, not only the generate branch.

**Branch 3's log line must also include a ready-to-use URL (FR#9, User Scenarios "First start after
install or upgrade")** — e.g. `f"generated new auth_token, written to {path}. Open http://{config.host}:{config.port} to log in."`
(exact wording flexible; the URL is the concrete requirement). `resolve_auth_token(config:
WebApiConfig, data_dir: Path)` already receives `config`, which carries `host`/`port` — build the URL
from those fields directly in this function; there is no need to construct it anywhere else. Branches
1 and 2 (explicit config, existing file) do not need a URL — the User Scenarios text frames the URL
specifically as part of the *first-start-with-no-token* flow.

This task only builds and unit-tests the resolution function itself — wiring it into
`WebApiService.on_initialize()` (so it actually runs at startup) is T08's job, which imports and
calls this function; T08 does not need to add anything for the URL itself, since it's already part
of the log line this function produces.

## Focus

- `data_dir` is already a concept elsewhere in the codebase (Home Assistant token/config persistence)
  — check how other framework code resolves the data directory path (likely via `HassetteConfig` or
  a shared config accessor) and reuse that, don't hardcode a path or invent a new resolution
  mechanism.
- Atomic write: temp file in the *same directory* as the target (not `/tmp`, which may be a different
  filesystem and break `os.replace()`'s atomicity guarantee), mode `0600` set before or during the
  write, then `os.replace()`.
- The corrupt-file-recovery path (Edge Case: "Concurrent requests during token regeneration") — no
  locking is needed; this only happens once at startup before the service accepts traffic, per the
  design's own analysis. Don't add speculative locking.
- FR#21 requires a **distinct, identifiable** log line per branch, verified by asserting on log
  output in the unit test — don't use one generic "token resolved" message for all three branches.
- FR#9's ready-to-use URL is easy to drop silently (it's a small addition to one branch's log
  message, not a separate mechanism) — make sure the unit test for the "generated" branch explicitly
  asserts the URL is present in that log line, not just that a log line exists.

## Verify

- [ ] FR#9: Unit test confirms that with no configured token and no existing file, a token is generated via `secrets.token_urlsafe(32)`, persisted atomically (temp file + `os.replace()`) with mode `0600` to `<data_dir>/.web_api_token`, and an INFO log line fires containing a ready-to-use URL built from `config.host`/`config.port`.
- [ ] FR#10: Unit test confirms a corrupt/truncated existing token file results in a fresh token being generated (not a crash), with an ERROR-level log line making the regeneration visible.
- [ ] FR#21: Unit test exercises each of the three resolution branches (explicit config, existing file, freshly generated) and asserts each produces a distinct INFO log message, not a shared generic one.
- [ ] AC#12: Unit test confirms a corrupted/truncated token file at resolution time results in a fresh token, an ERROR log line, and the function returning successfully (not raising).
- [ ] AC#19: Unit test asserts on the exact log output distinguishing all three branches (explicit config vs. existing file vs. freshly generated).
