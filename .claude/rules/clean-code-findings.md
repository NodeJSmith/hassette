# Clean Code Findings

How to file issues for pre-existing code quality findings surfaced during `/mine-clean-code`, `/mine-review`, or `/mine-ship`.

## When to File

File an issue when a clean-code or nitpicker review surfaces a pre-existing finding (not introduced by the current branch) that:

1. Passed the validity protocol (not filtered as likely-invalid)
2. Is independently actionable — someone can fix it without understanding the current PR's context
3. Is not already tracked by an existing issue

Do not file findings introduced by the current branch — fix those in the current PR.

## Issue Shape

**Title:** `Clean up <what> in <where>` — imperative, specific to the affected files or component area. Not the checker name or finding ID.

**Labels (all required):**

- `type:enhancement`
- `topic:code-quality`
- `size:small` (most findings are; use `size:medium` only for multi-file structural changes)
- One or more `area:` labels matching the affected code

**Milestone:** `Code Quality`

**Body structure:**

```markdown
## Description

<One sentence: what review surfaced this, during which PR, and that it predates the current work.>

## Key Items

<Bulleted list of specific findings with file:line references. Group tightly related findings.>

## Acceptance Criteria

<Checklist of concrete done conditions — one per finding or per tightly-related cluster.>
```

## Grouping

One issue per component area or tightly-related cluster of findings. A nitpicker run that flags 3 issues in `execution-table.tsx` and 2 in `handler-health-card.tsx` from the same component family becomes one issue. Unrelated findings in different subsystems become separate issues.

Do not create one mega-issue for an entire review run. Do not create one issue per individual finding when they share a file.

## Filing Mechanics

Use `/mine-create-issue` to file. After filing, confirm the milestone and labels are set (the create-issue skill handles labels but may not set the milestone automatically).
