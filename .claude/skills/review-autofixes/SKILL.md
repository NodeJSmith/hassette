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
gh pr list --label "source:autofix" --state open --json number,title,headRefName --jq '.[] | "\(.number) | \(.title) | \(.headRefName)"'
```

Unattended, drop PRs labelled `autofix:needs-human`: they're parked until a human looks at them, and reprocessing them would repeat the same park on every run. A human returns one to the loop by swapping `autofix:needs-human` for `autofix:human-cleared`. Removing `needs-human` alone isn't enough, because the convergence is still in the PR's history and the next run would park it again. Interactively, keep parked PRs, since the user is likely the human pass they're waiting for.

Present the list (to the user, or in the run's output when unattended). If no open PRs, report that and stop.

## Phase 2: Process Each PR

For each PR, run these steps in sequence. Complete one PR before starting the next.

### 2a. Convergence Gate

An autofix PR that won't converge usually has several findings pointing at one flawed mechanism, where each fix spawns the next finding. Fixing findings one at a time never shows that. This gate compares every finding from every review round before anything is patched again.

Check out the PR branch first (`gh pr checkout {PR}`). The ledger is built from the code at the PR head, and the fixes in 2c land on this checkout too. Then fetch all review feedback, resolved threads included, into `<tmpdir>` from `get-skill-tmpdir review-autofixes`. Both this gate and 2b read it:

```bash
gh-pr-threads {PR} --json --all > <tmpdir>/feedback.json
```

**When to skip.** Skip straight to 2b if any of these hold:
- The PR carries `autofix:human-cleared`. A human already reviewed it and wants the loop to keep going.
- It's a first-round PR. A convergence needs findings from more than one round, so run the gate only when `feedback.json` shows resolved threads (`.threadCounts.resolved > 0`) or some reviewer has submitted more than one review (this prints a number greater than 1):

  ```bash
  gh pr view {PR} --json reviews --jq '[.reviews[].author.login] | group_by(.) | map(length) | max // 0'
  ```

**Build the ledger.** Follow `${CLAUDE_CONFIG_DIR:-~/.claude}/skills/mine-address-pr-issues/SKILL.md` for these parts, rather than a copy here, which would drift:
1. "Review threads & non-thread comments" describes the `feedback.json` you just fetched.
2. "Review comments: build the ledger": `pr-ledger-check init` (get `--pr-author` from `gh pr view {PR} --json author --jq .author.login`), a `deep-worker` that fills the ledger per `ledger-procedure.md` from this checkout, then `pr-ledger-check check` until it exits 0. Give the `deep-worker` the same instruction the source skill does: read code as needed, but don't modify files or run state-changing git commands, since 2c works in this checkout.

If the ledger can't be completed (the check still fails after two fix rounds, or a tool errors) and the run is unattended, don't fall through to patching. Skip the rest of Phase 2 for this PR and record "ledger failed: {reason}" in the summary. Interactively, show the problems and ask.

**No convergences:** continue to 2b. The ledger is only a gate; 2b triages as usual.

**Convergences:** stop before fixing anything on this PR.

- **Interactive:** ask as mine-address-pr-issues's "Convergence gate" does. "Stop and discuss" ends work on this PR only. Move on to the next PR and record it as "stopped to discuss" in the summary. If the user picks "Patch individually", continue to 2b and note in the summary that the convergence was patched individually by choice.
- **Unattended:** never patch individually. Park the PR for a human, reading its state first with `gh pr view {PR} --json labels,isDraft,autoMergeRequest` so nothing is repeated:
  1. Add `autofix:needs-human` if it's missing. That label takes the PR out of later unattended runs (Phase 1).
  2. Turn off any auto-merge an earlier run queued: `gh pr merge --disable-auto {PR}`.
  3. If the PR isn't a draft, convert it: `gh pr ready {PR} --undo`.
  4. Remove any `codex-rounds:N` label, so the Codex round counter doesn't keep driving automated re-review while the PR waits.
  5. Post one comment, written to a temp file and posted with `gh pr comment {PR} --body-file`. For each convergence, include:
     - its `mechanism`
     - its members, one line each: the finding, its round, and its outcome or open status
     - its `summary`
     - its `open_questions`, unanswered. Don't propose a redesign; these are for the human to decide.

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
3. Run the two merge-blocking gates the way CI's new-code steps do (`.github/workflows/lint.yml`). Local hooks don't cover them, and a fix can trip them on its own. Both compare commits, so run them after committing. `check_duplicate_code.py` needs Java, because it runs PMD CPD.

   ```bash
   uv run python tools/check_file_size_regressions.py origin/main HEAD
   uv run python tools/check_duplicate_code.py --gate-new-code origin/main HEAD
   ```

   If either fails, fix it and amend before pushing.
4. Push: `git push origin {branch}`

### 2f. Ensure the PR Closes Its Issue

A PR that started as a draft carries "Partial progress on #{N} — needs human review" in its body, not a GitHub closing keyword. Merging it as-is leaves the issue open with a stale `autofix:pr-open` label — nothing else in the pipeline clears either.

If the branch name matches `autofix/issue-{N}` (optionally followed by `-slug` — see `_AUTOFIX_BRANCH_RE` in `dfl`'s `hassette.py` for the exact pattern):

1. Check the current body (`gh pr view {PR} --json body --jq .body`) for a closing keyword referencing that issue (`close(s/d)`, `fix(es/ed)`, or `resolve(s/d)` followed by `#{N}`, case-insensitive). If one is already there, skip to 2g.
2. If the body reads "Partial progress on #{N}...", don't assume the review fixes closed the gap — they address code quality, not whether the issue's original ask is met. Read the issue (`gh issue view {N} --repo {REPO}`) and confirm what the draft named as unfinished is actually done now. If scope is genuinely still missing, leave the body untouched and go to 2g without a closing keyword — the issue should stay open and `pr-open`-labeled.
3. If it's actually complete, keep the rest of the description: read the full current body, replace the "Partial progress on #{N}..." line with `Closes #{N}`, run `get-tmp-filename` and write the modified body to that path, then push it back with `gh pr edit {PR} --body-file {tmpfile}` — never `--body "<full body>"` (arbitrary body content interpolated into a shell argument can break or execute unexpectedly) and never `--body "Closes #{N}"` alone, which would wipe the description.

If the branch name doesn't match the pattern, skip this step and go to 2g.

### 2g. Enable Auto-Merge

After the findings are handled and any fixes are pushed:

If the PR is a parked draft (`autofix:needs-human`, reachable only in an interactive run), ask the user before leaving the park: marking it ready, swapping `autofix:needs-human` for `autofix:human-cleared` (so later unattended runs don't re-park it) and queueing auto-merge. That's their decision.

```bash
gh pr merge --auto --squash {PR}
```

This queues the PR to merge automatically once CI passes. If the command fails with a merge conflict (base branch was modified), the PR needs a rebase — note it in the summary and move on.

## Phase 3: Summary

After all PRs are processed, present a summary table:

| PR | Review threads | Fixes | Outcome |
|---|---|---|---|
| #{n} | {X threads: Y fixed, Z skipped} | {description} | {auto-merge queued / needs rebase / parked: converging on {mechanism} / stopped to discuss / ledger failed} |

## Diagnostic Questions

Before classifying a finding as **Fix**:
- Does the issue actually exist in the current code, or is the reviewer reading stale context?
- If it suggests an abstraction, do callers exist outside the changed files? (YAGNI check)
- Would the fix introduce more complexity than the finding it addresses?

Before skipping a finding:
- Am I skipping because I verified it's wrong, or because fixing it is inconvenient?
- Would a reviewer reading this code independently flag the same issue?
