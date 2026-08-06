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
