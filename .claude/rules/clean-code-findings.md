# Clean Code Findings

How to file issues for pre-existing code quality findings surfaced during `/mine-clean-code`, `/mine-review`, or `/mine-ship`.

## When to File

File an issue when a clean-code or nitpicker review surfaces a pre-existing finding (not introduced by the current branch) that:

1. Passed the validity protocol (not filtered as likely-invalid)
2. Is independently actionable — someone can fix it without understanding the current PR's context
3. Is not already tracked by an existing issue

Do not file findings introduced by the current branch — fix those in the current PR.

## Code Quality vs. Architecture — mutually exclusive

This file governs `topic:code-quality` + the **Code Quality** milestone only. There is a sibling track, `topic:architecture` + the **Architecture** milestone, for structural/SOLID work — module decomposition, coupling reduction, redesigning an internal boundary. An issue gets exactly one of the two label+milestone pairs, never both. If a finding could plausibly wear either tag, use the diagnostic below rather than applying both "to be safe." Architecture-track issues have no separate shape doc — file them with `/mine-create-issue` using its standard type/area/size labeling, just with `topic:architecture` + the Architecture milestone instead of the Code Quality pairing below.

**`topic:code-quality`** — mechanical, local, low-risk. Fixable as a same-shape find-and-replace without changing how a reader traces control flow through the surrounding code: naming a magic constant, extracting a literally-repeated block, deleting dead code, fixing an import-order nit, deduplicating a copy-pasted test fixture. The kind of thing `/mine-clean-code`'s three checkers (llm-checker, lazy-checker, nitpicker) surface.

**`topic:architecture`** — structural. Splitting an oversized function/module along a genuinely different responsibility boundary, reducing coupling between modules, or any change that needs `refactoring-discipline.md`'s pin-behavior-first treatment (a characterization test before restructuring) because the risk of silently changing behavior is real. If the fix requires re-tracing control flow or re-deriving an invariant to verify correctness, it's architecture, not code-quality — regardless of how small the resulting diff looks.

**Diagnostic:** "Decompose `run_pipeline` into named steps" is architecture (six blended responsibilities, needed a pin test, real risk of reordering side effects). "Name the `d93f0b` literal as `DEFAULT_LABEL_COLOR`" is code-quality (one file, no behavior change, nothing to re-verify). When genuinely unsure, err toward architecture — it carries more scrutiny (pin-behavior-first), and mislabeling a risky change as a quick mechanical one is the more expensive mistake.

## Issue Shape

**Title:** `Clean up <what> in <where>` — imperative, specific to the affected files or component area. Not the checker name or finding ID.

**Labels (all required):**

- `type:enhancement`
- `topic:code-quality` — never combine with `topic:architecture`; see above
- `size:small` (most findings are; use `size:medium` only for coordinated multi-file mechanical changes, e.g. a consistent rename across a package — not for anything that decomposes or restructures)
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
