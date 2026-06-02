# CLI — Workflows

**Status:** Exists (139 lines), needs JTBD reorder + jq content absorbed
**Voice mode:** Getting-started/procedural — "you" allowed, step-by-step
**Page type:** Getting-started (procedural)
**Reader's job:** Diagnose a problem using the CLI — starting from "something is wrong" and ending at "here is what happened."

## What was cut (and where it goes)

Nothing cut. Content added: the jq scripting recipes move here from
cli/configuration.md, since they are workflow content ("how do I investigate?"), not
configuration content ("how do I set up the CLI?").

The existing page order is redesigned. The current page leads with the drill-down
workflow, then monitoring, then quick health checks, then time windows. The reader
who lands here is in one of two modes: "something is wrong right now" or "I want to
set up ongoing monitoring." Quick health checks serve the first mode better than a
5-step drill-down, so they move up front.

## Outline

### H2: Quick Health Checks
One-liner commands for common checks. The reader wants a fast answer:
- Is Hassette running? (`hassette status --json | jq ...`)
- Are all apps healthy? (`hassette dashboard --json | jq ...`)
- Any listeners with errors? (`hassette listener --json | jq ...`)
- What happened recently? (`hassette log --since 1h --limit 50`)

### H2: Drill-Down: From Status to Root Cause
The full investigation workflow, numbered steps:
1. `hassette status` — is the system ok?
2. `hassette dashboard` — which app has errors?
3. `hassette listener --app <key>` — which handler is failing?
4. `hassette listener <id> --since 1h` — what do the invocations look like?
5. `hassette execution <uuid>` — full trace for one invocation.

### H2: Monitoring a Specific App
Focused monitoring with `--app` filters across all commands. Multi-instance apps
with `--instance`.

### H2: Comparing Time Windows
`--since` with different durations to compare current vs baseline vs trend.

### H2: Scripting with `jq`
(Moved from cli/configuration.md)
Recipes for piping `--json` output to jq:
- Extract fields, filter by status, count failures
- Health check script (exit 1 if not ok)
- Alerting on error rate (dashboard + jq)

## Snippet Inventory

No code snippets — CLI command sequences are inline.

## Cross-Links

- **Links to:** Commands (individual command details), Configuration & Scripting (output modes, error handling), Web UI overview (browser alternative)
- **Linked from:** CLI overview, Operating, Troubleshooting
