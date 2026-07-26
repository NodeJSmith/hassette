---
name: review-autofixes
description: "Review open autofix PRs: triage CodeRabbit findings, run code/integration/WTF + clean-code reviewers, fix valid issues, push."
user-invocable: true
---

# Review Autofix PRs

Daily review of auto-generated PRs on `autofix/*` branches. For each open PR: triage CodeRabbit findings, run the full review battery, fix what's valid, push.

## When to Activate

- User says "review autofix PRs", "check the autofix PRs", "daily autofix review"
- User invokes `/review-autofixes`

## Phase 1: Discover

Find open autofix PRs:

```bash
gh pr list --search "autofix" --state open --json number,title,headRefName --jq '.[] | "\(.number) | \(.title) | \(.headRefName)"'
```

Present the list to the user. If no open PRs, report that and stop.

## Phase 2: Process Each PR

For each PR, run these steps in sequence. Complete one PR before starting the next.

### 2a. CodeRabbit Triage

Fetch threads:

```bash
gh-pr-threads --json {PR}
```

For each unresolved thread:

1. **Read the finding** — understand what CodeRabbit is claiming.
2. **Verify against the code** — read the cited file and lines on the PR branch (`git show {branch}:{path}`). Does the issue actually exist?
3. **Evaluate** — is it valid? Is it YAGNI? Is the suggested fix correct?
4. **Classify** as: **Fix** (valid, will address), **Skip** (YAGNI, defensible design, or wrong), or **Outdated** (code already changed).

**Named failure mode:** agents accept CodeRabbit findings as correct without verifying — "great catch" before checking. Always read the actual code first. CodeRabbit has ~30% false positive rate on this codebase.

Present a summary table of all findings with verdicts before fixing anything.

### 2b. Fix Valid Findings

Check out the PR branch. For each finding classified as **Fix**:

1. Apply the fix.
2. Run the affected tests.
3. If the fix touches web models or schemas, regenerate: `uv run python scripts/export_schemas.py --types`

### 2c. Resolve Threads

For each CodeRabbit thread, reply and resolve:

- **Fixed:** `gh-pr-reply {PR} {comment_id} "Fixed in {sha}." --resolve {thread_id}`
- **Skipped:** `gh-pr-reply {PR} {comment_id} "Skipping — {reason}." --resolve {thread_id}`

### 2d. Run Review Battery

Launch all 6 reviewers in parallel on the PR branch:

**Review group** (code-reviewer, integration-reviewer, wtf-reviewer):
- Each as `Agent(subagent_type="{type}")` with prompt: "Review the changes on branch `{branch}` against `main`. {PR title}. Run `git diff main...HEAD`."

**Clean code group** (llm-checker, lazy-checker, nitpicker):
- Same pattern.

Wait for all 6 to complete.

### 2e. Address Review Findings

For each reviewer's findings:

- **CRITICAL/HIGH**: Fix immediately, re-run the reviewer.
- **MEDIUM**: Fix if it's a quick, unambiguous change. Skip if it's a judgment call.
- **LOW**: Note but don't fix unless trivial.

### 2f. Commit & Push

If fixes were applied (from 2b or 2e):

1. Run affected tests to verify.
2. Stage, commit: `refactor: address review findings in {short description}`
3. Push: `git push origin {branch}`

## Phase 3: Summary

After all PRs are processed, present a summary table:

| PR | CodeRabbit | Fixes | Review Verdict |
|---|---|---|---|
| #{n} | {X threads: Y fixed, Z skipped} | {description} | {clean / N findings} |

## Diagnostic Questions

Before classifying a CodeRabbit finding as **Fix**:
- Does the issue actually exist in the current code, or is CodeRabbit reading stale context?
- If it suggests an abstraction, do callers exist outside the changed files? (YAGNI check)
- Would the fix introduce more complexity than the finding it addresses?

Before skipping a finding:
- Am I skipping because I verified it's wrong, or because fixing it is inconvenient?
- Would a reviewer reading this code independently flag the same issue?
