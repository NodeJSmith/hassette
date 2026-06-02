# CLI — Command Reference

**Status:** Exists (408 lines), comprehensive reference
**Voice mode:** Reference — terse, tabular, scannable
**Page type:** Reference
**Reader's job:** Look up the exact flags, output format, and API endpoint for a specific CLI command.

## What was cut (and where it goes)

Nothing cut. This is a lookup reference — completeness is the point. The existing
page is well-organized by command with consistent structure (description, output
example, flags table, API endpoint).

Anti-mirror check: the command order (run, status, app, listener, job, log, execution,
event, dashboard, config, telemetry) follows a rough frequency-of-use ordering, not
source-code order. `run` and `status` first because they are the first commands any
user runs. `app` and `listener` next because they are the primary inspection commands.
This is correct from the reader's perspective.

The Shared Flags section at the bottom consolidates cross-cutting flags (`--since`,
`--instance`, `--json`, `--limit`, `--source-tier`) — the reader can look up format
details once rather than per-command. This is the right structure for a reference page.

## Outline

### H2: `hassette run`
Start the server. Flags table (--token, --base-url, --verify-ssl, --dev-mode).

### H2: `hassette status`
System health summary. Output example, API endpoint.

### H2: `hassette app`
App listing + subcommands (health, activity, config, source). Subcommand table, then
each subcommand with output example and flags.

### H2: `hassette listener`
Listener listing + invocation history by ID. Output example, flags table, API
endpoints.

### H2: `hassette job`
Job listing + execution history by ID. Output example, flags table, API endpoints.

### H2: `hassette log`
Recent log entries. Output example, flags table, API endpoint.

### H2: `hassette execution`
Logs for a specific execution UUID. Flags, API endpoint.

### H2: `hassette event`
Recent HA events from the in-memory buffer. Output example, flags, API endpoint.

### H2: `hassette dashboard`
App grid health summary. Output example, API endpoint.

### H2: `hassette config`
Resolved Hassette configuration. API endpoint.

### H2: `hassette telemetry`
Telemetry database statistics. Output example, API endpoint.

### H2: Shared Flags
Cross-cutting flags table: `--app`, `--instance`, `--since`, `--limit`,
`--source-tier`, `--json`. `--since` format details (relative durations, absolute
timestamps). `--instance` resolution (index vs name, requires `--app`).

## Snippet Inventory

No code snippets — CLI output examples are inline.

## Cross-Links

- **Links to:** CLI overview, Workflows (how commands compose), Configuration & Scripting (output modes)
- **Linked from:** CLI overview, Operating (runbook commands reference these)
