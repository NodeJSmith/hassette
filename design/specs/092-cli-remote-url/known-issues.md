# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: FR#16/FR#17 success-path JSON-mode target/TLS echo not implemented

Status: open
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
