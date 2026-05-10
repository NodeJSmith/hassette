# Changelog Review

Review and rewrite the release-please changelog PR before merging.

## Context

- release-please config: !`cat release-please-config.json 2>/dev/null`
- Changelog quality rule: !`cat .claude/rules/changelog-quality.md 2>/dev/null`
- Current v0.24.0 section (gold standard for style): !`sed -n '/^## \[0\.24\.0\]/,/^## \[0\.23\.0\]/p' CHANGELOG.md | head -80`

## Step 1: Find the release PR

Run `gh pr list --search "chore(main): release" --state open --json number,title,headRefName --limit 5`.

If no PR found, stop and tell the user. If multiple, ask which one.

## Step 2: Checkout and read

1. Fetch and checkout the release-please branch.
2. Read the new release section in `CHANGELOG.md` (the topmost `## [x.y.z]` heading).
3. List the commits in this release: `git log --oneline <prev-tag>..<base-commit>`.

## Step 3: Gather PR context

For each commit that produced a changelog entry, fetch its PR body via `gh pr view <number> --json title,body` using the `(#NNN)` reference in the commit subject. Focus on:

- What user-facing behavior changed
- Breaking change migration details
- Whether the change is internal-only

## Step 4: Rewrite

Rewrite the release section to match the v0.24.0 style:

**Remove entirely:**
- `docs:` entries for prior art research, internal design docs
- `ci:` entries (CI pipeline changes)
- `test:` entries (test infrastructure, not test utilities shipped to users)
- `chore:` entries (gitignore, changelog meta, dependency bumps)
- `refactor:` entries with no user-visible behavior change
- Internal framework plumbing that users never interact with

**Keep and rewrite:**
- `feat:` entries → describe what users can now do
- `fix:` entries → describe what was broken and is now fixed
- `perf:` entries → describe what got faster
- `docs:` entries for user-facing docs (tutorials, API reference, getting started)
- `refactor:` entries that change user-facing APIs

**Breaking changes:**
Each must explain (1) what changed, (2) what user code is affected, (3) what to do. Use field-by-field details when types changed. Put these in a `### Breaking Changes` section at the top.

**Grouping:**
When 5+ entries remain, group by feature area with `### Section` headers:
- `### Breaking Changes` (always first if present)
- Topic sections like `### Scheduler`, `### Bus`, `### Web UI`, `### State Models`, `### Test Utilities`, `### API`, `### Error Handling`
- `### Bug Fixes` (always last)
- `### Documentation` (only if user-facing docs changed)

**Format:**
- `- ` bullets with bold lead-in for breaking changes
- Issue references as `(#NNN)`, no commit SHAs
- Preserve the `## [x.y.z](compare-link) (date)` heading exactly

## Step 5: Check older releases

Scan the 2–3 releases below the new one. If any have the raw release-please format (flat `### Features` / `### Bug Fixes` with `([commit-sha])` links), ask:

```
AskUserQuestion:
  question: "Older releases (listed below) still have raw release-please formatting. Clean those up too?"
  header: "Older entries"
  multiSelect: false
  options:
    - label: "Yes, clean them all"
      description: "Apply the same rewrite to older unreviewed releases"
    - label: "No, just this release"
      description: "Only edit the new release section"
```

## Step 6: Push

1. Show a summary: entries removed, entries rewritten, breaking changes added.
2. Ask for approval:

```
AskUserQuestion:
  question: "Ready to push the rewritten changelog to the release-please branch?"
  header: "Push"
  multiSelect: false
  options:
    - label: "Push it"
      description: "Commit and push to the release-please branch"
    - label: "Show the diff"
      description: "Show the full diff first, then ask again"
```

3. Commit with `docs: rewrite changelog with user-facing descriptions` and push.
