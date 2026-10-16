# Triage Medium Issues: Reference

## Categories

| Category | Meaning | Outcome |
|---|---|---|
| RELABEL | Small as written, or small once stale parts are dropped | `size:medium` → `size:small` |
| SPLIT | 2+ children, each small, together covering the whole issue | Children filed; parent closed by a later run once they are all closed |
| PARTIAL | Some pieces split out as small children; the rest stays medium | Children filed; parent keeps `size:medium` |
| STALE | Already fixed or obsolete on main | Closed with the evidence |
| DUPLICATE | Overlaps another open issue | Closed as duplicate of the survivor |
| DECISION | Blocked on a choice only the maintainer can make | `autofix:needs-decision`, so `triage-autofix-issues` picks it up |
| KEEP | Real medium or large design work | Left medium, marked so later runs skip it |

**The test for small:** could a bot with no human to ask finish it in one focused PR, roughly 1-3 files, without picking between two reasonable fixes? If it would have to pick, the issue is a DECISION, or the child body has to make the pick. A cleanup issue bundling several nits in one file is still small if the nits are mechanical.

**Duplicate survivor:** keep the issue whose body is more current against main and better scoped. On a tie, keep the older one, since it has the history. Unique findings from the closed issue move to the survivor.

## Classifier prompt

```
READ-ONLY triage. Do not change anything on GitHub and do not edit files in the repo.

Repo: NodeJSmith/hassette, checkout <repo-root>. Run `git -C <repo-root> fetch -q origin` and read code at origin/main (`git show origin/main:<path>`). HA core is at ~/source/core if a claim is HA-facing.

Goal: move size:medium issues within reach of an unattended autofix bot that only takes size:small. For each issue below, read the body and comments (`gh issue view <n> -R NodeJSmith/hassette --comments`), check every claim against origin/main, and classify it.

<paste the Categories table, "The test for small" and "Duplicate survivor">

Apply the test for small to every proposed child: a split whose children aren't each small wastes autofix runs. A SPLIT's children must cover all of the parent. Also check `gh api repos/NodeJSmith/hassette/issues/<n>/sub_issues`: if earlier children exist, don't propose ones that repeat them. Cite evidence for STALE (commit, file or PR). Name the survivor for DUPLICATE.

Flag same-file groups (issues or children that edit the same file), and say what order to chain them in, so they can be ordered with blocked_by links instead of conflicting.

Report under ~4000 chars: counts per category, then one line per issue as `#n CATEGORY: reason`, with children indented under SPLIT/PARTIAL (title, files, fix shape), then "Same-file groups".

Issues: <numbers and titles>
```

## Filing rules

Give these to the filing agent verbatim, plus the approved report.

```
Authorized on NodeJSmith/hassette, ONLY for the issues in your report: edit labels, create issues, set sub-issue and blocked_by links, comment on, close and retitle issues. Do not edit parent bodies. Pass every body and comment with --body-file (files in <tmpdir>), never inline.

Before changing an issue, re-fetch it (`gh issue view <n> --json state,labels,comments`). If it is closed, has gained an autofix:* label, has lost size:medium, or already has a `Size triage:` comment (another run got there first), skip it and list it under deviations.

Every issue you act on (except closes) gets a comment starting `Size triage:`. Later runs skip issues carrying one, so use the exact wording below.

1. RELABEL: `gh issue edit <n> --remove-label size:medium --add-label size:small`. The issue must then pass autofix's picker:
   - at least one of type:bug, type:enhancement, type:documentation, type:CICD, topic:code-quality;
   - an author autofix trusts: NodeJSmith, or app/jessica-claude (`is_allowed_author` in dfl_common);
   - no label in dfl_common's EXCLUDE_LABELS, which includes the parked labels;
   - a title not opening with Investigate/Evaluate/Audit/Consider/Explore/Decide (retitle it to a plain imperative if it does);
   - no open blocked_by issue that is size:medium or larger;
   - no fix left open for the bot to choose.
   If it can't pass, don't relabel it; report it as a deviation. Comment `Size triage: relabeled small.`, plus the corrected scope (files and fix shape) if the body is stale against main.

2. CHILDREN (SPLIT and PARTIAL):
   - Title: plain imperative, specific, no prefix (.claude/reference/github-workflow.md), not opening with any of the words above.
   - Body: problem, exact files, ONE committed fix shape, the test or check that proves it, acceptance criteria. Write it against current origin/main with no open choices, because a bot works it with no human. Verify every named path exists first.
   - Last line: `Part of #<parent>.`
   - Labels: size:small, the parent's type:* label, and the parent's applicable area:/topic:/epic: labels. If the parent has no type:* label, add the one that fits the child (github-workflow.md lists them); every type label is one autofix accepts. No priority, no milestone.
   - Sub-issue: `gh api -X POST repos/NodeJSmith/hassette/issues/<parent>/sub_issues -F sub_issue_id=<child id>`. The id comes from `gh api repos/NodeJSmith/hassette/issues/<child> --jq .id`.
   - Parent comment: `Size triage: split into #a, #b.` for a SPLIT. For a PARTIAL: `Size triage: partial, split out #a, #b; <what stays> stays medium.`

3. ORDER: link sibling dependencies and every same-file group, so two issues editing one file never run back to back unless the first has merged.
   - Command: `gh api -X POST repos/NodeJSmith/hassette/issues/<n>/dependencies/blocked_by -F issue_id=<blocker id>`. HTTP 422 "already been taken" means the link exists.
   - Only link to blockers that are, or will be, size:small. A medium blocker has no date, so the issue would wait indefinitely.
   - No cycles.

4. STALE: comment the evidence, ending "Reopen if this still applies.", then `gh issue close <n> --reason "not planned"`, or `--reason completed` if it shipped.

5. DUPLICATE: copy any unique finding to the survivor as a comment, comment on the duplicate naming the survivor, then `gh issue close <n> --duplicate-of <survivor>`, which sets the duplicate reason and records the link.

6. DECISION: `gh issue edit <n> --add-label autofix:needs-decision` and comment `Size triage: needs a decision. <the choice in one line>. <option> would make it small.` Leave `size:medium` on it: once the maintainer picks that option, the Requeue outcome in `triage-autofix-issues` swaps it to `size:small`. If no option makes it small, say so instead of naming one.

7. KEEP: comment `Size triage: kept medium. <reason>.` Nothing else.

8. CLOSE COMPLETED PARENT: confirm all sub-issues are closed, comment `Size triage: all children closed.`, then `gh issue close <n> --reason completed`.

If origin/main contradicts the report (the fix already landed, a proposed change would be wrong, a path is elsewhere), follow main, explain it in a comment on the parent, and list it under deviations.

Verify with API reads (labels, parent_issue_url, sub_issues, dependencies/blocked_by, state, state_reason), not exit codes. Report: a table (child | title | parent | blocked_by | sub-issue ok), one line per relabel, close, decision and keep, then deviations and why. Under ~3500 chars.
```

## Batch report

Illustrative only. All numbers in this file are placeholders.

```markdown
**Batch 3: core/bus/scheduler (34).** Relabel 3, split 6 → 13 children, stale 2, decision 8, keep 15.

- **Relabel:** #101 (body cites a removed helper; the fix is now in `bus.py` only), #102, #103.
- **Split #110** (three problems in one title):
  - a: `Remove the duplicate retry loop from websocket_service.py`
  - b: `Log the reconnect reason at INFO`, blocked by a (same file)
- **Close as stale:** #120 (fixed by #2400, `scheduler.py:88`).
- **Decision:** #130, strict vs lenient parsing. Strict makes it small.
- **Keep:** #140 (new lifecycle state machine), …
- **Same-file chains:** `bus.py`: #101 → 110a.
```

## Summary example

```markdown
**Batch 3 applied:** 3 relabeled; 13 children (#2850–#2862) under 6 parents; #120 and #121 closed as stale; 8 labeled needs-decision; 15 kept medium.
**Deviations:** #110: child a was already fixed on main, so one child was filed and the parent comment says why.
**Trend:** six "Decompose X" issues were kept for the same reason (the file-size gate wants one PR per file). A scanner change that files one issue per file would make them small at filing time.
```
