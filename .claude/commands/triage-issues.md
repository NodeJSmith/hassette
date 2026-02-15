---
description: Audit and clean up GitHub issues — enforce labels, milestones, titles, and bodies per project conventions.
---

# Triage Issues Command

Audit open GitHub issues **created by @NodeJSmith** against the conventions in CLAUDE.md, fix anything that's off, and report what was changed.

## When to Use

Use `/triage-issues` when:
- Issues have accumulated without proper labeling
- You've batch-created issues and need to fill in details
- Periodic hygiene check on the backlog (e.g., before a release or sprint)

## Arguments

$ARGUMENTS — parsed as:
- `all` (default) — audit every open issue
- `recent` — only issues created or updated in the last 14 days
- `#123 #456` — audit specific issue numbers only

## How It Works

### Phase 1: Gather Current State

Run in parallel:
```bash
gh issue list --state open --author @me --json number,title,body,labels,milestone,createdAt,updatedAt --limit 200
gh label list --json name,description,color --limit 100
```

### Phase 2: Check Each Issue Against Conventions

Read the **GitHub Issues** section of `CLAUDE.md` for the current project conventions. For each open issue, check:

1. **Title** — must be a plain imperative description (no `[Bug]`, `[Feature]`, `Bug:`, `Feature -` prefixes). Type is conveyed by labels, not title.
2. **Body** — must not be empty. At minimum needs a Description section and Acceptance Criteria (checklist).
3. **Type label** — exactly one of: `bug`, `enhancement`, `documentation`, `CICD`, `tests`
4. **Area label** — at least one `area:*` label unless the issue is cross-cutting (CI/CD, repo-wide docs, external integrations). Valid areas: `area:ui`, `area:websocket`, `area:scheduler`, `area:bus`, `area:api`, `area:config`, `area:apps`.
5. **Size label** — one of `size:small` or `size:large`. Apply based on estimated scope.
6. **Milestone** — must be assigned to one of the active milestones.
7. **Priority label** — `priority:high` or `priority:low` only when clearly warranted (security issues, blockers = high; nice-to-haves = low). Most issues don't need a priority label.

### Phase 3: Fix Issues

For each issue that fails any check:

**Missing/bad title**: Use `gh issue edit <N> --title "<new title>"`
**Empty/thin body**: Draft a body with these sections and apply with `gh issue edit <N> --body`:
  - `## Description` — what and why
  - `## Acceptance Criteria` — checklist of done conditions
  - (Optional) `## Proposed Solution` — if there's an obvious approach
  - Keep it concise. Don't pad with boilerplate.

**Missing labels**: Use `gh issue edit <N> --add-label "label1,label2"`
**Wrong labels**: Use `gh issue edit <N> --remove-label "old" --add-label "new"`
**Missing milestone**: Use `gh issue edit <N> --milestone "Name"`

### Phase 4: Report

After all fixes, output a summary table:

```
## Triage Summary

| # | Title | Changes Made |
|---|-------|-------------|
| 42 | Fix flashing on UI | Added body, +area:ui, +size:small, milestone → HA Addon and UI |
| 55 | Scheduler timeout | Title cleaned (removed [Feature] prefix), +area:scheduler |

### Stats
- Issues audited: 27
- Issues changed: 14
- Issues already clean: 13
```

### Phase 5: Flag Issues Needing Human Input

Some issues can't be fixed automatically:
- **Stale issues** with no activity for 3+ months — flag for review, don't close
- **Duplicate candidates** — flag pairs that look related, suggest merging
- **Unclear scope** — issues where you can't write a meaningful body from the title alone

Present these in a separate section:

```
## Needs Your Input

| # | Title | Question |
|---|-------|----------|
| 162 | Add guards against blocking I/O | Stale (4 months, no activity) — still relevant? |
| 63/64 | Timeout for scheduler / Timeout for bus | Merge into single issue? |
```

Use `AskUserQuestion` if fewer than 4 decisions are needed. Otherwise just list them for the user to address manually.

## Important Notes

- **Read CLAUDE.md first** every time — conventions may have changed since last run
- **Never close issues** without explicit user approval
- **Preserve existing body content** — when adding structure to an issue that has some text, wrap the existing text into the appropriate section rather than replacing it
- **Batch gh calls** where possible to avoid rate limiting
- Requires `gh` CLI installed and authenticated
