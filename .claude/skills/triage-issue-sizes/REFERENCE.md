# Triage Issue Sizes: Reference

## Sizes

- **small:** one focused PR, roughly 1-3 files, no open design choice. Autofix-eligible.
- **medium:** one PR that needs design judgement, or 4-10 files.
- **large:** several PRs, or a design or sketch needed first.

**The test for small:** could a bot with no human to ask finish it in one focused PR, roughly 1-3 files, without picking between two reasonable fixes? If it would have to pick, the issue is a DECISION, or the child body has to make the pick. A cleanup issue bundling several nits in one file is still small if the nits are mechanical.

**The test for medium:** one PR a person could review in one sitting. A "medium" that is really three PRs is large; a mechanical codemod over many files can still be medium if it is one reviewable change.

Apply these tests to every proposed size: each child's, and each RELABEL or RESIZE target's.

**Autofix eligibility** (for any outcome that leaves an issue size:small). Autofix's picker takes an issue only if it has:
- at least one of type:bug, type:enhancement, type:documentation, type:CICD, topic:code-quality;
- an author autofix trusts: NodeJSmith, or app/jessica-claude (`is_allowed_author` in dfl_common, `~/Dotfiles/packages/dfl-common/src/dfl_common/__init__.py`);
- no label in dfl_common's EXCLUDE_LABELS, except the PARKED_LABELS among them. A parked issue, or a child inheriting a parked label, stays parked until a human unparks it, so its honest size is still small; check every other condition here, but don't count the parked label against it;
- a title not opening with Investigate/Evaluate/Audit/Consider/Explore/Decide;
- no open blocked_by issue that is size:medium or larger;
- no fix left open for the bot to choose.

**Small behind a medium:** don't propose blocking a size:small issue on a medium or larger one: it would wait with no date. Put the order in the child's body ("start after #n merges") instead. Propose the link only when the two edit the same lines and running them out of order would conflict, and say so.

## Categories

| Category | Tier | Meaning | Outcome |
|---|---|---|---|
| RELABEL | medium | Small as written, or small once stale parts are dropped | `size:medium` → `size:small` |
| RESIZE | both | Valid but sized wrong: a large that mostly landed, or a medium that is really several PRs | Size label swapped to the stated size |
| SPLIT | both | 2+ children together covering the whole issue. Medium: each child small. Large: each child small or medium | Children filed. The parent is closed by a later run once every child closes as completed; until then it stays open, as a tracker if any child is medium |
| PARTIAL | medium | Some pieces split out as small children; the rest stays medium | Children filed; parent keeps `size:medium` |
| STALE | both | Already fixed or obsolete on main | Closed with the evidence |
| DUPLICATE | both | Overlaps another open issue | Closed as duplicate of the survivor |
| DECISION | both | Blocked on a choice only the maintainer can make | `autofix:needs-decision`, so `triage-autofix-issues` picks it up. Large runs only: when a pending milestone will reshape it, the classifier may propose comment-only "re-triage after <milestone>", which a later run picks back up once that milestone closes (see Phase 4) |
| RESEARCH | large | An open question or exploration, not buildable as written | Retitled to start with "Research" and resized to medium (one brief is one session's work). Writing the brief itself is out of scope here |
| KEEP | both | Valid, and correctly sized as real design work | Left as is, marked so later runs skip it |

**Duplicate survivor:** keep the issue whose body is more current against main and better scoped. On a tie, keep the older one, since it has the history. Unique findings from the closed issue move to the survivor.

## Classifier prompt

```
READ-ONLY triage. Do not change anything on GitHub and do not edit files in the repo.

Repo: NodeJSmith/hassette, checkout <repo-root>. Run `git -C <repo-root> fetch -q origin` and read code at origin/main (`git show origin/main:<path>`, `git grep <pat> origin/main`). HA core is at ~/source/core if a claim is HA-facing. If `gh issue view` times out on GraphQL, use REST: `gh api repos/NodeJSmith/hassette/issues/<n>` and `.../comments`.

<keep the one goal line for this run's tier and delete the other>
Goal (medium): move size:medium issues within reach of an unattended autofix bot that only takes size:small.
Goal (large): audit size:large issues: is each still valid on main, and is `size:large` accurate?

For each issue below, read the body and comments, check every claim against origin/main, and classify it. For milestone issues, read the milestone's ledger under design/specs/ (`gh api repos/NodeJSmith/hassette/milestones --jq '.[]|[.title,.description]'`): ratified ledger scope is not yours to change, but a stale reference in the body is still worth flagging.

<paste "Sizes" (with Autofix eligibility and Small behind a medium), the Categories rows for this tier, and "Duplicate survivor">

Be skeptical of issue bodies, which go stale; be equally skeptical of "it's huge" and check what fraction is actually left. Apply the size tests to every proposed child: a child that isn't its stated size wastes a run. A SPLIT's children must cover all of the parent. Check `gh api repos/NodeJSmith/hassette/issues/<n>/sub_issues` and `.../dependencies/blocked_by`: don't propose children that repeat existing ones. Cite evidence for STALE (commit, file:line or PR). Name the survivor for DUPLICATE, and search open issues for overlap beyond this batch (`gh issue list -R NodeJSmith/hassette --state open --search "<terms>"`).

Flag same-file groups (issues or children that edit the same file), and say what order to chain them in, so they can be ordered with blocked_by links instead of conflicting.

Write the report to <run dir>/report-<batch>.md and return it, under ~4500 chars: counts per category, then one line per issue as `#n CATEGORY: reason (evidence)`, with children indented under SPLIT/PARTIAL (title, size, files, fix shape), then "Same-file groups" and "Cross-issue notes" (overlaps, ordering, clusters).

Issues: <numbers and titles>
```

## Verifier prompt

```
READ-ONLY verification. Do not change anything on GitHub and do not edit repo files.

Repo NodeJSmith/hassette, checkout <repo-root>. `git -C <repo-root> fetch -q origin`, read code at origin/main. HA core at ~/source/core. If `gh issue view` times out, use REST (`gh api repos/NodeJSmith/hassette/issues/<n>`, `/comments`, `/sub_issues`, `/dependencies/blocked_by`).

This is a <tier> run. The triage report at <run dir>/report-<batch>.md was produced by another agent. Reports like it are routinely wrong in ways that otherwise surface only while filing: an item called stale is still present, a "small" child needs a design choice, a proposed change contradicts main, a referenced issue is closed or different, a dependency to delete is still in use. Re-check EVERY item independently before anything is filed.

For each issue, verify:
1. Every factual claim (paths, line numbers, counts, symbol existence, referenced issues' state and content) against origin/main and GitHub. Re-read the issue body and comments yourself.
2. The verdict: is STALE really done (find the shipping evidence)? Is DUPLICATE really the same scope? Is the size right on the Sizes pasted below?
3. For SPLIT/PARTIAL: do the children cover the whole parent? Is each child's size honest? Do any duplicate existing open issues or sub-issues? Are blocked_by targets open and correct?
4. Proposed blocked_by links: both issues open, no cycles, ordering justified. Apply "Small behind a medium": move an unjustified link into the child's body as an ordering note.
5. Every outcome that leaves an issue size:small passes "Autofix eligibility" (a parked label doesn't count against it, per that section).

<paste "Sizes" (with Autofix eligibility and Small behind a medium), the Categories rows for this tier, and "Duplicate survivor">

Do not soften: if a verdict is wrong, change it. If correcting forces a design call (choosing one side of an either/or), make the most conservative one and mark it `VERIFIER CALL` so the maintainer sees it.

Write the CORRECTED report (same structure, ready to file from) to <run dir>/verified-<batch>.md. Reply under ~2500 chars: the OK items collapsed into one list, each verdict flip as `FLIP #n: <old> -> <new>` with evidence, each detail correction as `#n: <what was wrong> -> <corrected>`, then anything you could not verify.
```

## Filing rules

Give these to the filing agent verbatim, plus the verified report's path and the user's changes as overrides.

```
Authorized on NodeJSmith/hassette, ONLY for the issues in your report: edit labels, create issues, set sub-issue and blocked_by links, comment on, close and retitle issues. Do not edit parent bodies unless the report or an override says to. Pass every body and comment with --body-file (files in <run dir>/file-<batch>/), never inline. Pass `-R NodeJSmith/hassette` to every `gh issue` command: without repo context, comments can fail silently. If `gh issue view` times out on GraphQL, use REST (`gh api`).

Before changing an issue, re-fetch it (state, labels, comments). If it is closed, has gained an autofix:* label, no longer has this run's size label, or has gained a `Size triage:` comment newer than the run started (another run got there first), skip it and list it under deviations. An older `Size triage: resized to ...` or `re-triage after ...` comment is why the issue is in this run; it is not a reason to skip.

Every issue you act on (except closes) gets a comment starting `Size triage:`. Later runs skip issues carrying one (except the two hand-on kinds in SKILL.md Phase 1), so use the exact wording below.

1. RELABEL / RESIZE: swap the size label (`gh issue edit <n> -R NodeJSmith/hassette --remove-label size:<old> --add-label size:<new>`). An issue relabeled to size:small must then pass autofix's picker (Autofix eligibility, pasted below; a parked label doesn't count against it); retitle it to a plain imperative if only the title fails.
   If it can't pass, don't relabel it; report it as a deviation. Comment `Size triage: relabeled small.` (or `Size triage: resized to <size>.`), plus the corrected scope (files and fix shape) if the body is stale against main.

2. CHILDREN (SPLIT and PARTIAL):
   - Title: plain imperative, specific, no prefix (.claude/reference/github-workflow.md), not opening with any of the words above.
   - Body: problem, exact files, the fix shape, the test or check that proves it, acceptance criteria. Write it against current origin/main and verify every named path exists first. A size:small child commits to ONE fix shape with no open choices, because a bot works it with no human.
   - Last line: `Part of #<parent>.`
   - Labels: the child's size, the parent's type:* label, and the parent's applicable area:/topic:/epic:/priority: labels, including a parked label (a child of parked work stays parked). If the parent has no type:* label, add the one that fits the child (github-workflow.md lists them). A DECISION child gets `autofix:needs-decision` and size:medium. Children don't get a `Size triage:` comment: a later run of their size should still check them.
   - Milestone: copy the parent's, if any. A child is part of the parent's milestone scope, since together the children are the parent. If the report moves part of the parent outside the milestone's ledger scope, leave that child without one and say so.
   - Sub-issue: `gh api -X POST repos/NodeJSmith/hassette/issues/<parent>/sub_issues -F sub_issue_id=<child id>`. The id comes from `gh api repos/NodeJSmith/hassette/issues/<child> --jq .id`.
   - Parent comment: `Size triage: split into #a, #b.` for a SPLIT. For a PARTIAL: `Size triage: partial, split out #a, #b; <what stays> stays medium.` A large parent with any medium child keeps size:large as a tracker.

3. ORDER: link sibling dependencies and every same-file group, so two issues editing one file never run back to back unless the first has merged.
   - Command: `gh api -X POST repos/NodeJSmith/hassette/issues/<n>/dependencies/blocked_by -F issue_id=<blocker id>`. HTTP 422 "already been taken" means the link exists.
   - Don't block a size:small issue on a medium or larger one unless the report says to (see "Small behind a medium"); otherwise state the order in the child's body. Name every such link you do add in the report's notes, so the summary can flag it.
   - No cycles.

4. STALE: comment the evidence, ending "Reopen if this still applies.", then `gh issue close <n> -R NodeJSmith/hassette --reason "not planned"`, or `--reason completed` if it shipped.

5. DUPLICATE: copy any unique finding to the survivor as a comment, comment on the duplicate naming the survivor, then `gh issue close <n> -R NodeJSmith/hassette --duplicate-of <survivor>`, which sets the duplicate reason and records the link.

6. DECISION: `gh issue edit <n> -R NodeJSmith/hassette --add-label autofix:needs-decision` and comment `Size triage: needs a decision. <the choice in one line>. <option> would make it <smaller size>.` Leave the size label: once the maintainer picks that option, `triage-autofix-issues` swaps it (Requeue when the result is small and not parked, otherwise Resize). If no option makes it smaller, say so instead of naming one. For a DECISION the report marks comment-only, skip the label and comment `Size triage: re-triage after <milestone>. <why>.`

7. RESEARCH: swap to size:medium, retitle to start with "Research" (unless it already does), and comment `Size triage: research, not buildable as written. <next step>.`

8. KEEP: comment `Size triage: kept <size>. <reason>.`, plus any stale-reference corrections the report lists. Nothing else.

9. CLOSE COMPLETED PARENT (the report's CLOSE COMPLETED PARENTS section): confirm it has at least one sub-issue and every one is closed as completed, comment `Size triage: all children closed.`, then `gh issue close <n> -R NodeJSmith/hassette --reason completed`.

If origin/main contradicts the report (the fix already landed, a proposed change would be wrong, a path is elsewhere), follow main, explain it in a comment on the parent, and list it under deviations.

Verify with API reads (labels, milestone, parent_issue_url, sub_issues, dependencies/blocked_by, state, state_reason), not exit codes. Report: a table (child | title | parent | size | blocked_by | sub-issue ok), one line per relabel/resize, close, decision, research and keep, then notes (small issues blocked by mediums), then deviations and why. Under ~3500 chars.

<paste "Sizes" (with Autofix eligibility and Small behind a medium)>
```

## Batch report

Illustrative only. All numbers in this file are placeholders.

```markdown
**Batch 3: core/bus/scheduler (34).** Relabel 3, split 6 → 13 children, stale 2, decision 8, keep 15.
**Verifier:** 1 flip (#120 is not stale: the helper moved, the bug didn't), 4 detail fixes, 1 verifier call (#110b picks the strict parser).

- **Relabel:** #101 (body cites a removed helper; the fix is now in `bus.py` only), #102, #103.
- **Split #110** (three problems in one title):
  - a: `Remove the duplicate retry loop from websocket_service.py`
  - b: `Log the reconnect reason at INFO`, blocked by a (same file)
- **Close as stale:** #121 (fixed by #2400, `scheduler.py:88`).
- **Decision:** #130, strict vs lenient parsing. Strict makes it small.
- **Keep:** #140 (new lifecycle state machine), …
- **Same-file chains:** `bus.py`: #101 → 110a.
```

A large batch adds resize, research and tracker lines:

```markdown
- **Resize:** #1721 → medium (half of it was dropped; after #3104). #1250 → small (only the drawer link remains).
- **Research:** #1237, retitle "Research a composition-based lifecycle controller", → medium.
- **Split #513** (tracker, stays large): four mediums by module group, the app-lifecycle one blocked by #3104.
```

## Summary example

```markdown
**Batch 3 applied:** 3 relabeled; 13 children (#2850–#2862) under 6 parents; #121 closed as stale; #98 closed as completed (all children done); 8 labeled needs-decision; 15 kept medium.
**Deviations:** #110: child a was already fixed on main, so one child was filed and the parent comment says why. #2861 is small but blocked by medium #2700 (same config keys).
**Trend:** six "Decompose X" issues were kept for the same reason (the file-size gate wants one PR per file). A scanner change that files one issue per file would make them small at filing time.
```
