# CLI — Configuration & Scripting

**Status:** Exists (231 lines), needs JTBD reorder
**Voice mode:** Reference/procedural hybrid
**Page type:** Reference
**Reader's job:** Set up the CLI for their environment (remote instance, shell completion, scripting) and know how to handle errors in scripts.

## What was cut (and where it goes)

The "Scripting with jq" section (6 recipes + 2 scripts) moves to Workflows. That
content answers "how do I investigate a problem?" not "how do I configure the CLI?"
Keeping it here forces the reader to find workflow content on a configuration page.

What stays: Configuration (discovery order, token), Output Modes (human/JSON/NO_COLOR),
Shell Completion, Error Handling. These are all setup-and-reference content.

## Outline

### H2: Configuration
#### H3: Discovery Order
How the CLI finds the server address: env vars, .env file, hassette.toml, default.
Tip for remote instances (env var or .env file).

#### H3: Token
Not required for CLI query commands — only for `hassette run`. Brief.

### H2: Output Modes
#### H3: Human-Readable (Default)
Tables for collections, panels for single objects. Piped output strips ANSI and
disables truncation.

#### H3: JSON (`--json`)
Structured output. Full response model (superset of table). One JSON document on
stdout. Exit code semantics with `--json`.

#### H3: `NO_COLOR`
Disable ANSI color output.

### H2: Shell Completion
#### H3: Generate to stdout
`--generate-completion` for zsh/bash/fish.

#### H3: Install to default location
`--install-completion --shell zsh`. Auto-detect behavior.

### H2: Error Handling
#### H3: Exit Codes
Table: 0 (success), 1 (server/usage error), 2 (network error).

#### H3: Common Errors
Connection refused, request timed out, unknown instance name — each with the error
message and what to do.

#### H3: JSON Error Format
Error objects in JSON mode. Two examples (network error, server error).

#### H3: Debug Mode (`--debug`)
Full HTTP response on errors. Human mode and JSON mode examples.

## Snippet Inventory

No code snippets — shell command examples are inline.

## Cross-Links

- **Links to:** CLI overview, Commands, Workflows (jq recipes moved there)
- **Linked from:** CLI overview, Commands (output modes reference)
