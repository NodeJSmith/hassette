---
task_id: "T10"
title: "Add CLI documentation"
status: "done"
depends_on: ["T05", "T06", "T07", "T08"]
implements: ["FR#2", "FR#10"]
---

## Summary

Add CLI documentation to CLAUDE.md, README.md, and the docs site. CLAUDE.md gets command examples in the Common Commands section. README gets a CLI overview section. The docs site gets a full CLI page with command reference, usage examples, scripting patterns, and shell completion setup instructions.

## Prompt

### Update `CLAUDE.md`

In the `## Common Commands` section, add CLI query commands:

```
# Query a running instance
hassette status
hassette app
hassette listener --app <key> --since 1h
hassette log --app <key> --since 1h --limit 20
hassette job --json

# Instance-specific queries
hassette listener --app <key> --instance 0
hassette app health <key> --instance office
```

### Update `README.md`

Add a `## CLI` section (after the existing "Getting Started" or equivalent section) with:
- Brief description: query a running hassette instance from the terminal
- 4-5 usage examples showing common workflows (status check, app investigation, log tailing, JSON for scripting)
- Link to the full docs site CLI page for details

### Create docs site CLI page

Create `docs/cli.md` (or `docs/cli/index.md` if the docs use subdirectories — check the existing `docs/` structure):

**Sections:**

1. **Overview** — what the CLI does, how it connects to a running instance
2. **Quick Start** — `hassette status`, `hassette app`, `hassette log --since 1h`
3. **Command Reference** — table or subsections for each command:
   - Command syntax, description, API endpoint, supported flags
   - Cover: status, app (list/health/activity/config/source), listener (list/invocations), job (list/executions), log, execution, event, config, service, telemetry, dashboard
4. **Shared Flags** — `--app`, `--instance`, `--since`, `--limit`, `--source-tier`, `--json` with descriptions and examples
5. **Output Modes** — human-readable vs JSON, pipe behavior, NO_COLOR support
6. **Scripting Examples** — patterns with `--json` and `jq`:
   - `hassette status --json | jq '.status'`
   - `hassette listener --app my-app --json | jq '.[] | select(.error_count > 0)'`
   - Health check script pattern
7. **Configuration** — how the CLI discovers the server address (env vars, .env, TOML, defaults)
8. **Shell Completion** — setup instructions for bash, zsh, fish
9. **Error Handling** — exit codes (0/1/2), JSON error format, common errors

### Update docs navigation

Add the CLI page to `mkdocs.yml` nav section. Check the existing nav structure and place it logically (likely under a "Reference" or "User Guide" section).

### No tests needed

This task is documentation-only. Verify by building the docs site (`uv run mkdocs serve`) and confirming the page renders correctly.

## Focus

- `CLAUDE.md`: the `## Common Commands` section is near the top of the file — add CLI commands after the existing entries
- `README.md`: check the existing section structure before adding
- `docs/` directory structure: check `mkdocs.yml` for the nav configuration and existing page layout. Use the same markdown style and heading conventions as existing docs pages.
- The docs site uses mkdocs — `uv run mkdocs serve` to preview locally
- Keep the command reference concise — `--help` text serves as the detailed reference. The docs page should focus on workflows and discoverability, not exhaustive flag documentation.

## Verify

- [ ] FR#2: Each subcommand is documented with its syntax, description, and supported flags
- [ ] FR#10: Shell completion setup instructions are documented for bash, zsh, and fish
