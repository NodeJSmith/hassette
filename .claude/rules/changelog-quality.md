# Changelog Quality (release-please)

This project uses [release-please](https://github.com/googleapis/release-please) to generate changelog entries from conventional commit messages. Every PR that lands on `main` becomes a changelog line item. Write commit messages (and therefore PR titles) with this in mind.

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
4. **No internal-only entries** — if the PR is purely internal (CI, test infra, prior art research, refactoring with no behavior change), use `chore:`, `ci:`, `test:`, or `docs:` type. These still appear in the changelog by default, but will be removed during the pre-release changelog review pass

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

Before merging a release-please PR, review the generated changelog and manually edit the CHANGELOG.md on the release-please branch to:

1. **Remove internal entries** — prior art research, CI changes, test infrastructure, refactors with no user-visible behavior change
2. **Expand vague entries** — if a commit subject is too terse, add context from the PR body
3. **Group by feature area** — reorganize flat lists into topic-grouped sections (matching the v0.24.0 style) when a release has 5+ entries
4. **Verify breaking change descriptions** — ensure they tell the user what to do, not just what changed internally
