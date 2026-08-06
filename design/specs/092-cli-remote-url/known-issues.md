# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: FR#16/FR#17 success-path JSON-mode target/TLS echo not implemented

Status: filed (#1527)
Run: 57
Source: T04
Reason not fixed now: out-of-scope
Observed in: T04
Affected files:
- src/hassette/cli/client.py
- src/hassette/cli/output.py

Issue:
FR#16 requires the resolved non-loopback target to be surfaced once per invocation on both the
success and failure paths (a `Target: <base_url>` line on stderr in human mode, a `"target"` key
in the JSON envelope in JSON mode). FR#17 requires a similar `"tls_verified": false` key in JSON
mode when `verify_ssl` is false and sourced from config. Both are fully implemented for the error
path (human and JSON mode — `_handle_http_error` and `_handle_network_error` in `client.py`) and
for the success path in human mode (`_echo_success_target_and_warnings()`). The success-path
JSON-mode echo (adding `"target"`/`"tls_verified"` keys to a successful command's JSON output) is
not implemented — JSON mode is a no-op there today.

Why deferred:
Every command's `client.get(...)` result flows straight into one of `cli/output.py`'s three render
functions (`render_table`, `render_detail`, `render_detail_dict`), each independently writing its
own JSON document with no shared success envelope. Adding these keys on the success path requires
either touching all 6 command modules' JSON output plumbing or restructuring `cli/output.py`'s
render functions to accept and merge an extra envelope dict — both out of T04's scope as approved
(wiring the resolver into the client, not redesigning command output rendering).

Recommended follow-up:
Design a shared JSON success envelope (or an extra-keys parameter threaded through the three
render functions) that lets `client.get(...)` callers attach `target`/`tls_verified` metadata
without each of the 6 command modules doing it by hand. File as a follow-up issue scoped to
`cli/output.py` and the 6 command modules in `src/hassette/cli/commands/`.

Acceptance criteria:
- A unit test asserts a successful non-loopback command's JSON output includes a `"target"` key
  matching the resolved base URL.
- A unit test asserts a successful command run with a config-sourced `verify_ssl=false` includes
  `"tls_verified": false` in its JSON output.
- Loopback / verified-TLS success output is unchanged (no new keys).

## KI-002: docs/pages/cli/commands.md sample outputs were stale relative to current CLI output

Status: resolved — fixed during this orchestration run
Run: 57
Source: T06
Reason not fixed now: N/A — fixed directly instead of deferred
Observed in: T06 (doc-accuracy-review, pre-existing content not touched by T06's own diff, but fixed
in the same run rather than left for a follow-up)
Affected files:
- docs/pages/cli/commands.md

Issue:
`doc-accuracy-review` scoped to `cli/commands` found 7 findings, all in ASCII-art sample outputs
and one prose claim, none on lines T06's diff touched (confirmed via `git diff HEAD~1 -- docs/pages/cli/commands.md`,
which shows T06 only edited the `hassette run` flags table and the global-flags table):
- `hassette status` sample panel omits the `bootstrap_released` field (between `websocket_connected`
  and `uptime_seconds` in `SystemStatusResponse`).
- `hassette app` sample table omits the "Autostart" column (7th of 8 columns in `APP_LIST_COLUMNS`).
- `hassette app health` sample panel title shows the raw class name "AppHealthResponse" instead of
  the humanized "App Health" that `_humanize_model_name` actually produces.
- `hassette job` sample table omits the "Mode" column (in `JOB_LIST_COLUMNS`, between Status and Total).
- `hassette job` sample row shows Status as lowercase "scheduled" instead of the capitalized
  "Scheduled" the column formatter actually produces.
- `hassette telemetry` sample panel title shows "TelemetryStatusResponse" instead of the humanized
  "Telemetry Status".
- Prose claim "next scheduled run time (blank unless the status is scheduled)" is stale — every
  recognized `schedule_status` now shows status-aware placeholder text (e.g. "Timing unavailable.",
  "Waiting for entity time.") instead of a blank cell, per `_next_run_display`'s current implementation.

Why not deferred:
None of these lines were in T06's stated scope (docs for the new remote-URL/credential-resolution
feature) — they were pre-existing staleness in sample outputs for commands this feature didn't
touch (`status`, `app`, `app health`, `job`, `telemetry`), introduced by whichever earlier change
modified `SystemStatusResponse`, `APP_LIST_COLUMNS`, `JOB_LIST_COLUMNS`, or `_next_run_display`
without updating the docs. Scope boundaries between tasks in a single orchestration run don't
change who owns a real, fixable issue discovered along the way — fixed directly instead of filed
for later.

Fix applied:
- Added the `bootstrap_released` row to the `hassette status` sample panel.
- Added the "Autostart" column to the `hassette app` sample table.
- Corrected the `hassette app health` panel title to "App Health".
- Added the "Mode" column to the `hassette job` sample table (value: `single`, the
  `DEFAULT_OVERLAP_MODE`).
- Capitalized the `hassette job` sample row's Status cell to "Scheduled".
- Corrected the `hassette telemetry` panel title to "Telemetry Status".
- Rewrote the Next Run column description to name the four status-aware placeholder strings
  (`Timing unavailable.`, `Waiting for entity time.`, `Schedule completed.`, `Manual only.`)
  instead of claiming a blank cell.

Verified via `uv run mkdocs build --strict` (exit 0) and `prek -a` (clean) after the fix.

Acceptance criteria:
- `hassette status`/`hassette app`/`hassette app health`/`hassette job`/`hassette telemetry` sample
  outputs in the page match live output field-for-field, including panel titles.
- The Next Run column description matches `_next_run_display`'s current placeholder-text behavior.

## KI-003: Two non-unified `HassetteConfig` test-builder helpers for cli/web_api overrides

Status: resolved — fixed during known issues walkthrough
Run: 57
Source: clean-code
Observed in: T03/T04 (clean-code review at the end of the run)
Affected files:
- tests/unit/cli/test_target.py
- tests/unit/cli/test_client.py

Issue:
`tests/unit/cli/test_target.py`'s `_make_config()` (new in this branch) and
`tests/unit/cli/test_client.py`'s `_make_config_for_auth()` (pre-existing, extended in this branch
per the design doc's Convention Examples) both build a `HassetteConfig` with `cli`/`web_api`
overrides for resolver/credential tests, but via two different construction strategies:
`_make_config()` routes through the shared `make_test_config()` factory (per
`.claude/rules/test-conventions.md`), while `_make_config_for_auth()` constructs
`HassetteConfig(web_api=WebApiConfig(...), cli=CliConfig(...))` directly, bypassing
`make_test_config()`'s other safety defaults (`apps.autodetect=False`,
`disable_state_proxy_polling=True`). Neither helper reuses the other, despite covering
overlapping ground (host/port, cli.server_url, cli.auth_token, cli.verify_ssl, web_api.auth_token).

Originally deferred:
At clean-code time, unifying the two into one shared helper looked like it meant either routing
12+ existing `TestCredentialAttachment`/`TestVerifySslPassthrough`/etc. tests in `test_client.py`
through `make_test_config()`'s extra safety defaults (a behavior-adjacent change to an
actively-used, unrelated test suite) or making `test_target.py`'s newer helper match
`test_client.py`'s bypass-`make_test_config()` style. On closer inspection during the known-issues
walkthrough, this turned out to be a mechanical migration rather than a design decision — see Fix
applied below.

Fix applied:
Added `make_cli_config()` to `tests/unit/cli/conftest.py` — a thin wrapper over the shared
`make_test_config()` factory (per `.claude/rules/test-conventions.md`) covering the cli/web_api
override shape both files need. Removed `test_target.py`'s local `_make_config()` and
`test_client.py`'s `_make_config_for_auth()`; migrated all call sites in both files onto the
shared helper. `test_client.py`'s separate, unrelated local `_make_config(host, port)` helper
(used by target-derivation tests with no cli/web_api overrides) was renamed to
`_make_host_port_config` to disambiguate it from the new shared `make_cli_config()`. Verified via
`uv run pytest tests/unit/cli/ -n 4` (430 passed, no behavior changes) and a code-reviewer pass
(PASS, 0 findings).

Acceptance criteria:
- One test-builder helper (shared or in `test_utils`) covers the cli/web_api override shape
  needed by both `test_target.py` and `test_client.py`. — met (`make_cli_config` in `conftest.py`)
- All tests in both files pass unchanged in behavior after the migration. — met (430/430 passed)
