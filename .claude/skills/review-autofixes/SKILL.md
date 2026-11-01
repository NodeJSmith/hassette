---
name: review-autofixes
description: "Review open autofix PRs: gate on findings that converge across review rounds, triage bot review findings, fix valid issues, push, queue auto-merge."
user-invocable: true
---

# Review Autofix PRs

Daily review of auto-generated PRs on `autofix/*` branches. For each open PR: check whether review findings keep converging on one mechanism (and park the PR for a human if so), triage the bot review findings, fix what's valid, push, and queue auto-merge. It doesn't run a reviewer battery. CodeRabbit and Codex have already reviewed the PR head, so this skill's job is to answer their findings, the same way `/mine-address-pr-issues` does interactively.

The skill runs either **interactively** (a user invoked it and can answer questions) or **unattended** (a scheduled reviewer invoked it, and the invoking prompt says so). Steps that differ say how.

## When to Activate

- User says "review autofix PRs", "check the autofix PRs", "daily autofix review"
- User invokes `/review-autofixes`

## Phase 1: Discover

Find open autofix PRs by label (autofix PR creation attaches `source:autofix`):

```bash
gh pr list --label "source:autofix" --state open --json number,title,headRefName,labels --jq '.[] | "\(.number) | \(.title) | \(.headRefName) | \([.labels[].name] | join(","))"'
```

Unattended, drop PRs whose labels include `autofix:needs-human`: they're parked until a human looks at them, and reprocessing them would repeat the same park on every run. A human returns one to the loop by swapping `autofix:needs-human` for `autofix:human-cleared`. Removing `needs-human` alone isn't enough, because the convergence that needed a human is still in the PR's history and the next run would park it again. Interactively, keep parked PRs, since the user is likely the human pass they're waiting for.

Present the list (to the user, or in the run's output when unattended). If no open PRs, report that and stop.

## Phase 2: Process Each PR

For each PR, run these steps in sequence. Complete one PR before starting the next.

### 2a. Convergence Gate

An autofix PR that won't converge usually has several findings pointing at one flawed mechanism, where each fix spawns the next finding. Fixing findings one at a time never shows that. This gate compares every finding from every review round before anything is patched again.

Check out the PR branch first (`gh pr checkout {PR}`). The ledger is built from the code at the PR head, and the fixes in 2c land on this checkout too. Then fetch all review feedback, resolved threads included, into `<tmpdir>` from `mktemp -d <scratchpad>/review-autofixes-XXXXXX`. Both this gate and 2b read it:

```bash
gh-pr-threads {PR} --json --all > <tmpdir>/feedback.json
```

**When to run it.**
- **Never** when the PR carries `autofix:human-cleared`. A human already reviewed it and wants the loop to keep going, so go straight to 2b.
- **Always** when the PR has had more than one review round: `feedback.json` shows resolved threads (`.threadCounts.resolved > 0`), or some reviewer has submitted more than one review (this prints a number greater than 1):

  ```bash
  gh pr view {PR} --json reviews --jq '[.reviews[].author.login] | group_by(.) | map(length) | max // 0'
  ```

- **Your call** on a first-round PR. Findings from a single round can still converge, for example several findings that each probe a different edge of one mechanism. Run the gate when the findings plausibly share a mechanism. Skip to 2b when they plainly don't: two fully separate items, or a batch that's all documentation or style nits.

**Build the ledger.** Follow `${CLAUDE_CONFIG_DIR:-~/.claude}/skills/mine-address-pr-issues/SKILL.md` for these parts, rather than a copy here, which would drift:
1. "Review threads & non-thread comments" describes the `feedback.json` you just fetched.
2. "Review comments: build the ledger": `pr-ledger-check init` (get `--pr-author` from `gh pr view {PR} --json author --jq .author.login`), a `deep-worker` that fills the ledger per `ledger-procedure.md` from this checkout, then `pr-ledger-check check` until it exits 0. Give the `deep-worker` the same instruction the source skill does: read code as needed, but don't modify files or run state-changing git commands, since 2c works in this checkout.

If the ledger can't be completed (the check still fails after two fix rounds, or a tool errors) and the run is unattended, don't fall through to patching. Skip the rest of Phase 2 for this PR and record "ledger failed: {reason}" in the summary. Interactively, show the problems and ask.

**No convergences:** continue to 2b. The ledger is only a gate; 2b triages as usual.

**Convergences:** stop before fixing anything on this PR. The one exception is an unattended run where no convergence needs a human (see Unattended below).

- **Interactive:** ask as mine-address-pr-issues's "Convergence gate" does. "Stop and discuss" ends work on this PR only. Move on to the next PR and record it as "stopped to discuss" in the summary. If the user picks "Patch individually", continue to 2b and note in the summary that the convergence was patched individually by choice.
- **Unattended:** first decide which convergences need a human. A convergence does if either is true:
  - at least one member is `open`, or
  - a fix didn't hold: some member was first raised after another member was fixed. The fix time is the committer date of the commit the fix reply names (`git show -s --format=%cI {sha}`), not the reply's own timestamp. A reply often lands after the fixed head is already under review. Use the reply time only when it names no commit. For a history row, use its `round` date. Where either side of a comparison is only a date, count a same-day tie as raised after, unless both members come from one source record (one review, one challenge-log record, or one known-issue entry). A record's findings are raised together, so none of them is raised after another's fix. If a fixed member's fix time can't be found, as with a review-body finding that got a shared PR comment instead of a reply, treat the convergence as needing a human. The later member counts whatever its own outcome. A finding declined after a fix still parks, because an unattended run can't tell a wrong finding from a fix that didn't hold.

  Findings raised in one review always come before any fix, so a batch fixed together never meets the second test. Check that test rather than reading "every member resolved" as settled: a mechanism patched once per round also ends up all resolved.

  A convergence that meets neither is settled, for example several first-round findings that one commit fixed together. The interactive path still surfaces these. Unattended, a settled convergence doesn't park, since a human has nothing left to decide on findings that are already fixed. If no convergence needs a human, continue to 2b, and add "convergence noted, already resolved: {mechanism}" to the PR's summary row.

  If any convergence needs a human, never patch individually. Park the PR. Read its state first with `gh pr view {PR} --json labels,isDraft,autoMergeRequest` so nothing is repeated, then do the steps in this order. The label goes on last because it takes the PR out of later unattended runs (Phase 1): if a run dies partway, the next run must still see the PR so it can finish making it safe.
  1. Turn off any auto-merge an earlier run queued: `gh pr merge --disable-auto {PR}`.
  2. If the PR isn't a draft, convert it: `gh pr ready {PR} --undo`.
  3. Remove any `codex-rounds:N` label, so the Codex round counter doesn't keep driving automated re-review while the PR waits.
  4. Post one comment, written to a temp file and posted with `gh pr comment {PR} --body-file`. For each convergence that needs a human, include:
     - its `mechanism`
     - its members, one line each: the finding, its round, and its outcome or open status
     - its `summary`
     - its `open_questions`, unanswered. Don't propose a redesign; these are for the human to decide.

     After those, name any settled convergence in one line: its `mechanism` and "already resolved".
  5. Add `autofix:needs-human` if it's missing.

  Then skip the rest of Phase 2 for this PR and record it in the summary as parked.

### 2b. Triage Review Findings

Work from the `<tmpdir>/feedback.json` fetched in 2a. Triage every unresolved thread, from CodeRabbit and Codex alike, plus any findings CodeRabbit put in `.reviewComments` instead of a thread ("Outside diff range", "Duplicate comments"). For each:

1. **Read the finding** — understand what the reviewer is claiming.
2. **Verify against the code** — read the cited file and lines in the checkout. Does the issue actually exist?
3. **Evaluate** — is it valid? Is it YAGNI? Is the suggested fix correct?
4. **Classify** as: **Fix** (valid, will address), **Skip** (YAGNI, defensible design, or wrong), or **Outdated** (code already changed).

Severity doesn't decide it: a valid LOW finding is a **Fix** too.

**Failing CI is a finding too.** Review threads aren't the only thing that blocks a merge. List the PR's failed checks (`gh pr checks {PR}`) and read each failure's log (`gh run view {run-id} --log-failed`). The `file-sizes` and `duplicate-code` gates are the ones autofix PRs trip most: a red one always means this PR grew an oversized file or added a duplicate block, so it's a **Fix**, never a skip (`.claude/reference/github-workflow.md` explains both gates). Shrink or move code to fix a file-size failure; don't contort it just to hit the count. An aggregate job like `lint-complete` fails whenever one of its inputs does, so fix the input.

**Named failure mode:** agents accept bot findings as correct without verifying — "great catch" before checking. Always read the actual code first. CodeRabbit alone has a ~30% false positive rate on this codebase.

Present a summary table of all findings with verdicts before fixing anything (in the run's output when unattended).

### 2c. Fix Valid Findings

On the PR branch checked out in 2a, for each finding classified as **Fix**:

1. Apply the fix.
2. Run the affected tests.
3. If the fix touches web models or schemas, regenerate: `uv run python scripts/export_schemas.py --types`

### 2d. Resolve Threads

For each triaged thread, reply and resolve. Findings from `.reviewComments` have no thread; answer those in one PR comment.

- **Fixed:** `gh-pr-reply {PR} {comment_id} "Fixed in {sha}." --resolve {thread_id}`
- **Skipped:** `gh-pr-reply {PR} {comment_id} "Skipping — {reason}." --resolve {thread_id}`

### 2e. Commit & Push

If fixes were applied in 2c (CI fixes included):

1. Run affected tests to verify, plus `prek -a` and `prek run pyright -a --stage pre-push`.
2. Stage, commit: `refactor: address review findings in {short description}`
3. Run the two merge-blocking gates the way CI's new-code steps do (`.github/workflows/lint.yml`). The `check-file-size-regressions` and `check-duplicate-code` pre-push hooks run the same commands, but run them here anyway so the result doesn't depend on hooks being installed; a fix can trip them on its own. Both compare commits, so run them after committing. `check_duplicate_code.py` needs Java, because it runs PMD CPD.

   ```bash
   uv run python tools/check_file_size_regressions.py origin/main HEAD
   uv run python tools/check_duplicate_code.py --gate-new-code origin/main HEAD
   ```

   If either fails, fix it, amend, and repeat steps 1 and 3 on the amended commit before pushing. Moving code to fix a file-size failure can break imports or types or add duplication, and a duplication fix can grow a file, so earlier results don't cover the amended `HEAD`.
4. Push: `git push origin {branch}`

### 2f. Ensure the PR Closes Its Issue

A PR that started as a draft carries "Partial progress on #{N} — needs human review" in its body, not a GitHub closing keyword. Merging it as-is leaves the issue open, and with no open PR left to hold it out of selection, the issue becomes eligible for autofix again.

If the branch name matches `autofix/issue-{N}` (optionally followed by `-slug` — see `AUTOFIX_BRANCH_RE` in `dfl_common` for the exact pattern):

1. Check the current body (`gh pr view {PR} --json body --jq .body`) for a closing keyword referencing that issue (`close(s/d)`, `fix(es/ed)`, or `resolve(s/d)` followed by `#{N}`, case-insensitive). If one is already there, skip to 2g.
2. If the body reads "Partial progress on #{N}...", don't assume the review fixes closed the gap — they address code quality, not whether the issue's original ask is met. Read the issue (`gh issue view {N} --repo {REPO}`) and confirm what the draft named as unfinished is actually done now. If scope is genuinely still missing, leave the body untouched and park the issue so it stays open but out of selection: `gh issue edit {N} --repo {REPO} --add-label autofix:needs-human`, then comment on the issue what is still missing, starting the comment with `Autofix judged this needs a human decision` (`NEEDS_HUMAN_COMMENT_PREFIX` in the pipeline's `constants.py`) so triage recognizes it as a bail comment. Go to 2g without a closing keyword.
3. If it's actually complete, keep the rest of the description: read the full current body, replace the "Partial progress on #{N}..." line with `Closes #{N}`, run `mktemp <scratchpad>/pr-body-XXXXXX` and write the modified body to that path, then push it back with `gh pr edit {PR} --body-file {tmpfile}` — never `--body "<full body>"` (arbitrary body content interpolated into a shell argument can break or execute unexpectedly) and never `--body "Closes #{N}"` alone, which would wipe the description.

If the branch name doesn't match the pattern, skip this step and go to 2g.

### 2g. Enable Auto-Merge

After the findings are handled and any fixes are pushed:

If the PR is a parked draft (`autofix:needs-human`, reachable only in an interactive run), ask the user before leaving the park: marking it ready, swapping `autofix:needs-human` for `autofix:human-cleared` (so later unattended runs don't re-park it) and queueing auto-merge. That's their decision.

```bash
gh pr merge --auto --squash {PR}
```

This queues the PR to merge automatically once CI passes. It's safe to queue right after pushing fixes. Codex reviews each new head well before the test suite finishes, and an unresolved review thread blocks the merge, so an unreviewed fix can't slip through. If the command fails with a merge conflict (base branch was modified), the PR needs a rebase — note it in the summary and move on.

## Phase 3: Summary

After all PRs are processed, present a summary table:

| PR | Review threads | Fixes | Outcome |
|---|---|---|---|
| #{n} | {X threads: Y fixed, Z skipped} | {description} | {auto-merge queued / needs rebase / parked: converging on {mechanism} / stopped to discuss / ledger failed} |

When a PR continued past a settled convergence, append `(convergence noted, already resolved: {mechanism})` to its outcome, e.g. `auto-merge queued (convergence noted, already resolved: status-to-color map)`.

## Diagnostic Questions

Before classifying a finding as **Fix**:
- Does the issue actually exist in the current code, or is the reviewer reading stale context?
- If it suggests an abstraction, do callers exist outside the changed files? (YAGNI check)
- Would the fix introduce more complexity than the finding it addresses?

Before skipping a finding:
- Am I skipping because I verified it's wrong, or because fixing it is inconvenient?
- Would a reviewer reading this code independently flag the same issue?
