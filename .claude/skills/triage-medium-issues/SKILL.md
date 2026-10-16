---
name: triage-medium-issues
description: "Use when the user says: 'triage the medium issues', 'split the mediums', 'get more issues into autofix', 'can any mediums be split', or wants size:medium issues made autofix-ready. Checks each medium issue against current main, sorts it into relabel / split / partial / stale / duplicate / decision / keep, gets one approval per batch, then files the children, relabels and closes with sub-issue and blocked_by links, verified by API reads."
user-invocable: true
---

# Triage Medium Issues

Autofix only takes `size:small` issues. Many `size:medium` issues are small once their stale parts are dropped, or are two or three small fixes bundled under one title. This skill finds those, files the small pieces so autofix can work them unattended, and leaves real design work alone.

Sibling of `triage-autofix-issues`, which handles issues autofix already tried and gave up on. This skill works the queue before autofix sees it.

**The principle:** an issue is only small if an unattended bot with no human to ask could finish it in one focused PR. A bad split costs more than no split, because each child burns an autofix run and leaves a half-done parent.

## Arguments

$ARGUMENTS: optional issue numbers, or an `area:*` / `type:*` label to scope the run. With no argument, take every open `size:medium` issue.

## Phase 1: Gather and batch

1. `gh issue list -R NodeJSmith/hassette --state open --label size:medium --limit 500 --json number,title,labels,body,comments` into the scratchpad (`get-skill-tmpdir triage-medium-issues`). If the result hits the limit, raise it.
2. Find split parents whose children are all done. From the full list, take issues with a comment starting `Size triage: split into` (PARTIAL parents say `Size triage: partial` and stay open). If `gh api repos/NodeJSmith/hassette/issues/<n>/sub_issues --jq '[.[] | select(.state == "open")] | length'` is 0, the parent goes into the first batch report as "close as completed". Nothing else closes it.
3. Drop every issue autofix would never take, or that an earlier run already handled. Issue numbers named in $ARGUMENTS skip this filter.
   - Any label in `PARKED_LABELS` (`dfl_common`, in `~/Dotfiles/packages/dfl-common/src/dfl_common/__init__.py`).
   - Any `autofix:*` label. Those belong to `triage-autofix-issues`.
   - Any issue with a comment starting `Size triage:`, which every outcome below leaves behind.
4. Split the rest into batches of about 35, so each classifier's report fits its length cap. Put bugs first, then group by `area:*`, then group issues with no area by type or topic. Grouping matters because issues in one area tend to touch the same files, and a classifier can only flag same-file conflicts within its own batch. Show the user the batch list, then start Phase 2.

## Phase 2: Classify (read-only)

Dispatch one Sonnet subagent per batch, up to three in parallel, with the classifier prompt in REFERENCE.md. They change nothing on GitHub.

Classifiers tend to trust the issue body. Bodies go stale fast here: other PRs fix findings, files move, and a parent's proposed fix can be wrong on main. The prompt makes them check every claim against `origin/main`. When you relay a result, keep its evidence (commit, file, line) so the user can check it.

## Phase 3: Approve each batch

When a classifier finishes, present its batch as message text in the "Batch report" format (REFERENCE.md).

Ask with `AskUserQuestion` (header `Batch <n>`). Build the options from the findings:
- **Apply all** when nothing in the batch looks doubtful.
- **Apply except** when you doubt specific items: a close resting on thin evidence, or a split whose children don't look small. Name the items in the option.
- **Apply with changes**, where the user names the changes.
- **Skip batch**.

The user often answers with a correction instead, such as "taking screenshots is easy now, relabel #1453". Fold it in and confirm what changed before filing.

## Phase 4: File

Dispatch one Sonnet filing subagent per approved batch, in parallel, with the filing rules in REFERENCE.md and the approved report including the user's changes.

The batch may have waited a while for approval, and autofix or a person may have changed an issue since it was classified. The filing rules make the agent re-fetch each issue's state and labels before changing it, and re-read the parent's named files on `origin/main` before writing a child. Where main contradicts the report, the agent follows main and explains why.

Filing agents report what they intended, not what happened. Before relaying, check with API reads: every close (`state_reason`), every deviation, and at least two each of children (labels, `parent_issue_url`, `dependencies/blocked_by`), relabels, and `Size triage:` comments per batch. If any check fails, verify the whole batch.

## Phase 5: Summarize

Report per batch: relabels, children filed (number range and parents), closes, decisions labeled, issues kept, and every deviation. If one cause sent three or more issues to KEEP or DECISION, name it as a trend. It may be a scanner or pipeline fix that would make those issues small when they're filed. See "Summary example" in REFERENCE.md.
