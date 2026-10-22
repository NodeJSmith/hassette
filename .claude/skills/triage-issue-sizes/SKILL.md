---
name: triage-issue-sizes
description: "Use when the user says: 'triage the medium issues', 'split the mediums', 'get more issues into autofix', 'can any mediums be split', 'audit the large issues', 'are the large issues still valid', 'triage the large issues', or wants size:medium or size:large issues checked, resized or split. Checks each issue of one size against current main, sorts it into relabel / resize / split / partial / stale / duplicate / decision / research / keep, independently verifies every recommendation, gets one approval per batch, then files the children, relabels and closes with sub-issue and blocked_by links, verified by API reads."
user-invocable: true
---

# Triage Issue Sizes

Autofix only takes `size:small` issues. Many `size:medium` issues are small once their stale parts are dropped, or are two or three small fixes bundled under one title. `size:large` issues drift the other way: half-landed, superseded by a later design, or really several independent mediums. This skill checks one size tier at a time, files the right-sized pieces, and leaves real design work alone.

Sibling of `triage-autofix-issues`, which handles issues autofix already tried and gave up on. This skill works the queue before autofix sees it.

**The principle:** an issue is only small if an unattended bot with no human to ask could finish it in one focused PR. A bad split costs more than no split, because each child burns an autofix run (or a human session) and leaves a half-done parent.

## Arguments

$ARGUMENTS: the size tier, `medium` (default) or `large`, then an optional `area:*` / `type:*` label to scope the run. With no scope, take every open issue of that size. If the first word is neither a tier nor a label, ask which tier was meant.

The two tiers differ in a few places, marked **Medium** / **Large** below and in REFERENCE.md. In short: a medium run aims at small children autofix can take; a large run audits validity and sizing, and its children may be small or medium.

## Phase 1: Gather and batch

1. Make a run directory: `mktemp -d <scratchpad>/triage-issue-sizes-XXXXXX`. Fetch `gh issue list -R NodeJSmith/hassette --state open --label size:<tier> --limit 500 --json number,title,labels,body,comments,milestone` into it, adding `--label <scope>` when the run is scoped (repeated `--label` flags must all match), so every later step sees only the requested subset. If the result hits the limit, raise it.
2. Find split parents whose children are all done. From the full list, take issues with a comment starting `Size triage: split into` (PARTIAL parents say `Size triage: partial` and stay open). A parent qualifies only if it has at least one sub-issue, none is open, and every one closed as `completed` (`gh api repos/NodeJSmith/hassette/issues/<n>/sub_issues --jq '[.[] | {state, state_reason}]'`). A child closed as not planned or duplicate means part of the parent may not have shipped: list that parent for the user instead. Qualifying parents skip Phases 2-3; present them as their own line in the first batch's report for approval, then append them to that batch's verified report as a `CLOSE COMPLETED PARENTS` section so the filing agent sees them. If that batch is skipped, they wait for the next run. Nothing else closes a parent.
3. Drop every issue an earlier run already handled, or that belongs elsewhere.
   - Any issue whose most recent `Size triage:` comment marks it as handled. Two kinds hand an issue on instead, and are NOT skipped: `Size triage: resized to <this tier>` (a larger-tier run, or a decision in `triage-autofix-issues`, moved it here for this tier to check), and `Size triage: re-triage after <milestone>` once that milestone is closed (`gh api repos/NodeJSmith/hassette/milestones?state=all --jq '.[] | select(.title=="<milestone>") | .state'`). Children filed by a run carry no `Size triage:` comment, so a later medium run picks up the medium children a large run filed. That is intended.
   - Any `autofix:*` label. Those belong to `triage-autofix-issues`.
   - **Medium:** any label in `PARKED_LABELS` (`dfl_common`, in `~/Dotfiles/packages/dfl-common/src/dfl_common/__init__.py`), since autofix never takes them. **Large:** keep parked issues; validity and sizing still matter for work a human will pick up.
4. Split the rest into batches of about 35 (medium) or 25 (large, whose issues take longer to check), so each report fits its length cap. Put bugs first, then group by `area:*`, then group issues with no area by type or topic. Grouping matters because issues in one area tend to touch the same files, and a classifier can only flag same-file conflicts within its own batch. Show the user the batch list, then start Phase 2.

## Phase 2: Classify (read-only)

Dispatch one Sonnet subagent per batch, up to three in parallel, with the classifier prompt in REFERENCE.md, filled in for this run's tier (its goal line, its Categories rows, the run dir, the batch's issues). They change nothing on GitHub. Each writes its report to `<run dir>/report-<batch>.md` as well as returning it.

Classifiers tend to trust the issue body. Bodies go stale fast here: other PRs fix findings, files move, and a parent's proposed fix can be wrong on main. The prompt makes them check every claim against `origin/main`.

## Phase 3: Verify (read-only)

As each classifier finishes, dispatch a Sonnet verifier for that batch (up to three in parallel) with the verifier prompt in REFERENCE.md, filled in the same way. Do not skip this, including for small batches: classifier reports routinely carry a wrong count, a stale path, a blocker that is already closed, a "small" child hiding a design choice, or a verdict that main contradicts, and those otherwise surface only while a filing agent is writing issues, after the user approved them.

The verifier re-reads every issue itself, re-checks every claim and verdict, and writes a corrected report to `<run dir>/verified-<batch>.md`, listing each correction with evidence. Present and file from the corrected report, never the classifier's.

A verifier can make its own design calls while correcting (picking one side of an either/or, restricting a workflow). Treat those as recommendations, not facts: surface them in Phase 4 like any other choice.

## Phase 4: Approve each batch

Present each verified batch as message text in the "Batch report" format (REFERENCE.md). Lead with what the verifier changed, and call out every **verdict flip** (a close that is no longer a close, a resize reversed, a split dropped) separately from detail fixes like counts and line numbers. Batches are grouped by area, so neither classifiers nor verifiers see overlaps across batches; if two batches propose children or closes that touch the same issue or file, say so here.

Ask with `AskUserQuestion` (header `Batch <n>`). Build the options from the findings:
- **Apply all** when nothing in the batch looks doubtful.
- **Apply except** when you doubt specific items: a close resting on thin evidence, a split whose children don't look their stated size, or a verifier design call. Name the items in the option.
- **Apply with changes**, where the user names the changes.
- **Skip batch**.

**Large:** most DECISION items are design questions, not autofix work. Don't label all of them by reflex. Offer to answer the quick ones in the conversation (then file the answer's outcome: close, or the resize/split it makes possible, with its `Size triage:` comment), leave a comment-only "re-triage after <milestone>" on the ones a pending milestone will reshape, and label only the rest `autofix:needs-decision`.

The user often answers with a correction instead, such as "taking screenshots is easy now, relabel #1453". Fold it in and confirm what changed before filing.

## Phase 5: File

Dispatch one Sonnet filing subagent per approved batch, in parallel, with the filing rules in REFERENCE.md, the path to the verified report, and the user's changes listed as overrides.

The batch may have waited a while for approval, and autofix or a person may have changed an issue since it was classified. The filing rules make the agent re-fetch each issue's state and labels before changing it, and re-read the parent's named files on `origin/main` before writing a child. Where main contradicts the report, the agent follows main and explains why.

Filing agents report what they intended, not what happened. Before relaying, check with API reads: every close (`state_reason`, and the duplicate link for duplicates), every deviation, and at least two each of children (labels, milestone, `parent_issue_url`, `dependencies/blocked_by`), relabels and resizes, research retitles, and `Size triage:` comments per batch. Also check that every `blocked_by` target the agent added is open and is the issue it meant: a typo'd number links a stranger. If any check fails, verify the whole batch.

## Phase 6: Summarize

Report per batch: relabels and resizes, children filed (number range and parents), closes (stale, duplicate, completed parents), decisions labeled or deferred, research retitles, issues kept, and every deviation. Name any small issue left blocked by a medium or larger one, since autofix won't reach it until that blocker lands. If one cause sent three or more issues to KEEP or DECISION, name it as a trend: it may be a scanner or pipeline fix, or a milestone whose landing should trigger a re-triage. See "Summary example" in REFERENCE.md.
