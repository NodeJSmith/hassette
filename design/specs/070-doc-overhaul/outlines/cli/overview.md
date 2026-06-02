# CLI — Overview

**Status:** Exists (67 lines), structure is good
**Voice mode:** Getting-started — "you" allowed, quick orientation
**Page type:** Getting-started (section landing)
**Reader's job:** Learn what the CLI can do and see it working in 30 seconds — so they know whether to use it or the web UI.

## What was cut (and where it goes)

Nothing cut. The existing page is lean and well-scoped: three example commands, a
connection error example, and links to deeper pages. This already matches the
reader's job. Adding JTBD metadata only.

The one structural note: the Quick Start section shows `status`, `app`, and `log` but
not `dashboard` — which is arguably more useful as a "find the problem" starting point.
Consider swapping `log` for `dashboard` since the reader's first question after
"is it running?" is "are my apps healthy?" not "what do the logs say?"

## Outline

### H2: Quick Start
Three commands with output: `hassette status` (is it running?), `hassette app`
(what apps are loaded?), `hassette log --limit 5` (what happened recently?). Connection
error example when Hassette is not running. Link to Configuration for remote instances.

### H2: Next Steps
- Command Reference — every command with flags and output examples
- Workflows — how to drill down from status to root cause
- Configuration & Scripting — JSON mode, jq recipes, shell completion

## Snippet Inventory

No code snippets — CLI output examples are inline.

## Cross-Links

- **Links to:** Commands, Workflows, CLI Configuration
- **Linked from:** Getting Started (next steps), Web UI overview
