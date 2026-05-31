# Changelog Quality (release-please)

This project uses [release-please](https://github.com/googleapis/release-please) to generate changelog entries from conventional commit messages. Every PR that lands on `main` becomes a changelog line item — unless its type is excluded. Write commit messages (and therefore PR titles) with this in mind.

## Which types appear in the changelog

Only these types generate changelog entries (configured in `release-please-config.json`):

| Type | Changelog section | Use for |
|---|---|---|
| `feat` | Features | New user-facing functionality |
| `fix` | Bug Fixes | Something was broken, now it works |
| `perf` | Performance Improvements | Measurable performance gains |
| `refactor` | Refactoring | Structural changes notable enough for users to know about |
| `docs` | Documentation | User-facing documentation (docs site, README, public docstrings) |

These types are **excluded from the changelog** — use them for internal work:

| Type | Use for |
|---|---|
| `chore` | Internal work: `design/`, `research/`, CLAUDE.md, deps, tooling, internal scripts |
| `ci` | CI/CD pipeline changes |
| `test` | Test infrastructure, coverage improvements |

**Key distinction:** `docs:` is for documentation that users read (docs site pages, README, public API docstrings). Work in `design/`, `.claude/`, research briefs, or internal tooling docs should use `chore:` so it stays out of the changelog.

## How release-please reads commits

| Source | What it becomes |
|---|---|
| Commit subject line | Changelog bullet point |
| `BREAKING CHANGE:` footer in commit body | Breaking change description |
| `feat!:` / `fix!:` bang in subject | Triggers "Breaking Changes" section header, but **only uses the subject line** if no `BREAKING CHANGE:` footer exists |

GitHub squash-merge uses the PR title as the commit subject and the PR body as the commit body (repo setting: `PR_BODY`).

## PR titles are changelog entries

The PR title becomes the one-line changelog entry that users read. Write it as a **user-facing description**, not a developer-facing one.

**Good** — tells a user what changed for them:
- `feat: add immediate-fire and duration-hold for state/attribute handlers`
- `fix: REST API returns 404 for non-existent app_key on start/stop/reload`
- `feat!: generate typed state models from HA core source for 34 entity domains`

**Bad** — internal jargon, implementation details, or vague bundling:
- `feat: entity codegen pipeline with 34 generated domains`
- `fix: bundle five small-scope issue fixes`
- `refactor: tech debt cleanup across 13 issues`
- `feat: lifecycle state machines, connection state, and startup registry validation`

### Rules

1. **Imperative mood, lowercase** — `add X`, `fix Y`, not `Added X` or `Adds Y`
2. **Describe the user-visible outcome** — what can the user now do, or what broke that's now fixed?
3. **No bundle PRs in the title** — if a PR bundles N fixes, the title should describe the theme, and individual items belong in the PR body / commit body where release-please won't pick them up
4. **No internal-only entries** — if the PR is purely internal (CI, test infra, prior art research, design docs), use `chore:`, `ci:`, or `test:` type — these are excluded from the changelog entirely. Do not use `docs:` for internal documents (`design/`, `.claude/`, research briefs); `docs:` appears in the changelog and is reserved for user-facing documentation

## Breaking changes MUST have a footer

When a PR contains a breaking change (`feat!:`, `fix!:`, `refactor!:`), the **PR body must end with a `BREAKING CHANGE:` footer** that explains:
1. What changed
2. What user code is affected
3. What the user needs to do

The footer goes at the very end of the PR body (after a blank line), and becomes the breaking change description in the changelog.

### Example PR body structure

```markdown
## Summary

<description of what the PR does>

## Breaking Changes

<detailed explanation for the PR reviewer>

BREAKING CHANGE: `state.value` for toggle entities (light, switch, fan,
etc.) now returns `bool` instead of `str`. Code using
`state.value == "on"` must change to `state.value is True`.
```

The `BREAKING CHANGE:` footer is a [conventional commit trailer](https://www.conventionalcommits.org/en/v1.0.0/#specification) — it must be:
- Preceded by a blank line
- On its own line starting with `BREAKING CHANGE: ` (with the colon and space)
- Can span multiple lines (continuation lines are indented or just flow naturally)

### Multiple breaking changes

Use multiple `BREAKING CHANGE:` footers, each separated by a blank line:

```
BREAKING CHANGE: `HassettePayload.event_id` changed from `int` to
`str` (UUID4). Update comparisons to use string UUIDs.

BREAKING CHANGE: `RecordingApi.get_entity` now requires an explicit
`BaseEntity` subclass model argument. Call `get_state(entity_id)` for
registry-converted state without a specific model.
```

## Pre-release changelog review

Before merging a release-please PR, review the generated changelog and manually edit the **CHANGELOG.md file** on the release-please branch to:

1. **Remove internal entries** — prior art research, CI changes, test infrastructure, refactors with no user-visible behavior change
2. **Expand vague entries** — if a commit subject is too terse, add context from the PR body
3. **Group by feature area** — reorganize flat lists into topic-grouped sections (matching the v0.24.0 style) when a release has 5+ entries
4. **Verify breaking change descriptions** — ensure they tell the user what to do, not just what changed internally

### Do NOT edit the PR body (CRITICAL)

Only edit the `CHANGELOG.md` file on the release-please branch. **Never rewrite the PR description body on GitHub.**

Release-please uses its own PR body format (the `:robot: I have created a release *beep* *boop*` block) to recognize merged release PRs. After a release PR is squash-merged, release-please runs again, finds the PR by title, and parses the body to confirm it's a release PR. If the body doesn't match the expected format, release-please treats the merge as a normal commit — no tag, no GitHub Release, no publish.

This happened with v0.34.0: the PR body was rewritten to match the curated changelog, release-please couldn't parse it, and the release silently failed. Recovery required manually creating the tag, GitHub Release, and triggering the publish workflows.

**What to edit:** `CHANGELOG.md` on the branch (commit and push to the release-please branch)
**What to leave alone:** The PR description on GitHub — release-please owns that

### Recovery: manual release

If a release-please PR is merged but no tag/release appears:

1. Check the post-merge workflow run — look for `✖ Pull request body did not match`
2. Create the tag: `git tag v<version> <merge-commit-sha> && git push origin v<version>`
3. Create the GitHub Release: `gh release create v<version> --target <sha> --notes-file <changelog-excerpt>`
4. Trigger publish workflows manually: `gh workflow run "Publish Python package" -f tag_name=v<version>` and `gh workflow run "Build & Publish Image" -f tag_name=v<version>`
5. Close any spurious release-please PR that was opened for the next version
