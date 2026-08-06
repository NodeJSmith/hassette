---
task_id: "T06"
title: "Update CLI, config, and web UI documentation"
status: "done"
depends_on: ["T04", "T05"]
implements: ["AC#14", "AC#15", "AC#19"]
---

## Summary

Rewrite the CLI configuration page around the new target-resolution and credential model, correct two pages that go stale with this change, and add the reverse-proxy section that tells an operator what to change on their gateway to let CLI traffic through. Docs land last because they describe the final flag names and error messages. This task also runs the repo-wide lint and type gates.

## Target Files

- modify: `docs/pages/cli/configuration.md`
- modify: `docs/pages/cli/commands.md`
- modify: `docs/pages/core-concepts/configuration/index.md`
- modify: `docs/pages/web-ui/index.md`
- read: `docs/pages/web-ui/snippets/reverse-proxy-caddy.txt`
- read: `docs/pages/web-ui/snippets/trusted-proxies.toml`
- read: `.claude/rules/doc-rules.md`
- read: `.claude/rules/voice-guide.md`
- read: `design/specs/092-cli-remote-url/design.md`
- read: `design/specs/092-cli-remote-url/tasks/context.md`

## Prompt

**`docs/pages/cli/configuration.md`** — the main rewrite.

- **"Discovery Order" (lines 5-16)** now describes target resolution: `--server-url` first, then `cli.server_url` (env → `.env` → TOML), then the bind-derived address as the last resort. The current text describes only the bind-derived path.
- **The "Remote instances" tip (lines 18-30)** is replaced entirely. Its `HASSETTE__WEB_API__HOST=192.168.1.100 hassette status` recipe is the antipattern this change fixes and must not survive as a suggestion.
- **"Web API Token"** gains `--token-file`, `cli.token_file`, and `HASSETTE__CLI__AUTH_TOKEN`, plus the CLI-scoped-vs-server-scoped table from the design's `## Architecture → Credential scoping`. The reason belongs with it: `web_api.*` describes what the *local* instance accepts, not what a remote one does. The current text presents `HASSETTE__WEB_API__AUTH_TOKEN` as *the* way to point the CLI at a token; that framing is now loopback-only.
- **"Common Errors" (lines 135-149)** gains two entries: the redirect case and the suppressed-credential 401.
- **New: an upgrade warning.** A `!!! warning "Upgrading from a previous version"` admonition naming the two silent behavior changes — the bind-host remote recipe no longer sending the token file, and `HASSETTE__WEB_API__AUTH_TOKEN` scoping to loopback — and what a script relying on either must change. These two break at runtime rather than at parse time, so a script keeps running and either starts 401ing or, against a target with `auth_enabled=False` or a matching `trusted_proxies` entry, silently succeeds unauthenticated. The changelog footer is not enough; this page is where a returning user looks.
- **New section: letting CLI traffic through a reverse proxy.** One worked example — a forward-auth gateway that rejects bearer tokens, and the shape of the change that lets `/api/*` through on Hassette's own token.

Two constraints on that new section:

1. **Write it in proxy-agnostic language.** No `middlewares`, no `handle`, no `location` — describe the change as "add a route for `/api/*` that skips your gateway's login middleware, and let Hassette's own bearer token authenticate those requests instead." The page it links to (`docs/pages/web-ui/index.md:30-49`) is written in Caddy, while the only concrete worked material available is Traefik-flavored; product-neutral phrasing avoids making a reader translate mid-task.
2. **Cover subdomain routing only.** That is the topology verified end-to-end against a live deployment. Path prefixes are supported in code and can be mentioned in the field reference, but no worked prefix example ships — the `PathPrefix` + `stripPrefix` round-trip has never been observed working end-to-end, and a reader following a step-by-step recipe is usually debugging under an outage.

Link to the existing guidance in `docs/pages/web-ui/index.md` rather than duplicating it; match that section's length and register.

**`docs/pages/cli/commands.md`** — the `hassette run` flag table at line 22 hand-documents `--base-url`/`-u`/`--url`, which T05 removed. Update to `--ha-url`/`-u`. A reader following the stale table gets a cyclopts "unknown option" error, and `mkdocs build --strict` will not catch it.

**`docs/pages/core-concepts/configuration/index.md`** — the "Configuration Sections" table (lines 55-65) lists the existing config groups and is the page a reader confused between `base_url`, `web_api.host`/`port`, and the new `cli.server_url` would consult. Add a `[hassette.cli]` row.

**`docs/pages/web-ui/index.md`** — add one cross-link from the existing reverse-proxy admonition to the new CLI section. No rewrite; #1117's content stands.

Follow `.claude/rules/voice-guide.md` throughout: system-as-subject on concept/reference pages (no "you"), 10–18 word explanatory sentences, present tense, main behavior before caveats, and every limitation paired with a path forward.

Do **not** edit `CHANGELOG.md` — release-please generates it from commit messages.

## Focus

Per `.claude/rules/doc-rules.md`, run `doc-persona-review` and `doc-accuracy-review` scoped to the three changed prose pages (`cli/configuration`, `cli/commands`, `core-concepts/configuration`) before this task is considered done. A `lost` or `stuck-at-step-N` persona verdict, or a confirmed `WRONG`/`OUTDATED_API` accuracy finding on lines you touched, is a blocker. Those reviews only read pages in the docs diff — a page omitted from this task is a page the accuracy review never sees, which is exactly why `commands.md` and `core-concepts/configuration/index.md` are here.

The docs site uses `--8<--` snippet includes for code examples, and CI type-checks Python snippets with Pyright. The additions here are shell, TOML, and prose rather than Python, so new snippet files are likely unnecessary — but if a TOML example is long enough to warrant one, put it in `docs/pages/cli/snippets/` alongside the page.

Existing snippets worth reading for register and length before writing the new section: `docs/pages/web-ui/snippets/reverse-proxy-caddy.txt` (three lines) and `trusted-proxies.toml`.

`mkdocs build --strict` catches broken internal links, so verify the cross-links resolve. It does not catch a stale table row or a removed flag still documented as present — those need the greps in Verify.

This task also runs the repo-wide gates (AC#14). `prek -a` alone does not run Pyright; it is a pre-push-staged hook and needs the separate invocation.

## Verify

- [ ] AC#14: `prek -a && prek pyright -a --stage pre-push` exits 0.
- [ ] AC#15: `uv run mkdocs build --strict` exits 0 with the rewritten CLI configuration page, the new reverse-proxy section, and the `[hassette.cli]` row in place.
- [ ] AC#19: `grep -n 'base-url\|--url' docs/pages/cli/commands.md` returns no match for the removed `hassette run` flag spellings.
