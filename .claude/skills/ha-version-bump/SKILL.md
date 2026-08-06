---
name: ha-version-bump
description: Use when the user says "new HA version", "bump HA version", "update the HA pin", "pull the new Home Assistant release", "monthly HA bump", or when the ha-version-drift workflow has filed a drift issue. Pulls the latest Home Assistant core release, updates every pinned reference, regenerates typed models, checks the developer blog for anything that needs a manual follow-up, and prepares (but does not push) the commit.
---

# HA Version Bump

Monthly maintenance. Hassette's typed entity/state models are generated from a local
checkout of `home-assistant/core`, pinned to an exact release. This skill re-runs that
pipeline against the latest release and surfaces anything a human needs to judge. It
does not silently rubber-stamp the diff.

`.github/workflows/ha-version-drift.yml` already detects pin drift daily and files a
tracking issue covering the pin, the local checkout, codegen, and tests. It doesn't cover
the compose-file image tags or the blog-reading step — this skill is the fuller recipe,
and the sole place those two are bumped.

## Phase 1: Check for drift

```bash
PINNED=$(cat codegen/ha-version.txt)
LATEST=$(gh api repos/home-assistant/core/releases/latest --jq .tag_name)
```

If `$PINNED` already equals `$LATEST`, tell the user there's nothing to bump and stop.
Otherwise, note the two values — each Bash tool call is a fresh shell, so `$LATEST`
doesn't survive into later phases; treat the version string as a fact you carry forward,
not a shell variable, and write it out literally in every command below.

If `$LATEST`'s year component is ahead of `$PINNED`'s (a year rollover, e.g. `2026.x` to
`2027.0`), flag this to the user before proceeding: major HA releases are far more likely
to carry breaking entity/API changes than a routine minor bump, and this skill is now the
only gate on that risk (Renovate's old `dependencyDashboardApproval` rule for major jumps
was removed along with the rest of its `homeassistant/home-assistant` handling — see
Phase 2). Ask whether to continue or wait for a closer look.

## Phase 2: Update every pinned reference

```bash
echo "<LATEST from Phase 1, substituted literally>" > codegen/ha-version.txt
```

Find every other place an HA image tag is pinned, then check each hit against `$PINNED`
to see which are actually stale. Don't rely on a fixed list of files — HA image tags are
minor-version only (`2026.7`, not `2026.7.1`) and new ones get added over time:

```bash
grep -rn "homeassistant/home-assistant:" --include="*.yml" --include="*.yaml" . \
  | grep -v node_modules | grep -v /.git/
```

Update each hit to the new minor version. This skill is the sole owner of these tags —
`renovate.json` explicitly disables Renovate for `homeassistant/home-assistant`
(`packageRules` — `"enabled": false`) precisely so there's no second, weekly bump racing
this monthly one. If `renovate.json` no longer has that rule, something reverted it;
flag that to the user rather than proceeding as if Renovate will catch the drift.

Then update the local core checkout (path from `reference_ha-core-local-checkout`
memory, default `~/source/core`):

```bash
cd ~/source/core && git status --short
```

If that shows uncommitted changes, stop and ask the user how to proceed (stash, discard,
or investigate) rather than switching tags out from under in-progress work. If clean:

```bash
git fetch --tags && git checkout "$LATEST"
```

## Phase 3: Regenerate and review

```bash
cd codegen && uv run hassette-codegen generate --ha-core-path ~/source/core
```

Read the full diff of every changed generated file (`git diff`, not `--stat`). Classify
each change against these three buckets.

- **Additive.** New device class, new unit, new enum member, new optional field. Safe.
- **Removed or renamed field, changed field type, removed enum member.** A breaking
  change for anyone using the generated models. Flag it explicitly to the user before
  proceeding. Do not silently absorb it into the commit.
- **Enum members that collapse to aliases of a same-valued member** (Python `StrEnum`
  behavior when two members share a value). Before flagging this as a bug, check whether
  HA core's own source does the same thing: grep the corresponding `~/source/core` file
  for `EnumWithDeprecatedMembers` or a comment marking the older member deprecated. If
  HA's own enum already collapses the same way, hassette's codegen is faithfully
  reproducing upstream, not introducing a defect.

Example from the 2026.7.1 to 2026.8.0 bump: a new `radon` device class, new
`Bq/m³`/`pCi/L` units, and a new `ButtonEventType` enum were all additive. A `climate.py`
change that looked like a broken enum (`TARGET_TEMPERATURE`/`TEMPERATURE` sharing a
value) turned out to mirror HA's own deprecation pattern once checked against
`~/source/core`. Also safe to commit as-is.

## Phase 4: Test and lint

```bash
cd codegen && HA_CORE_PATH=~/source/core uv run pytest tests/ -q --rootdir=.
cd - && ptest uv run nox -s dev
prek -a
prek pyright -a --stage pre-push
```

(`ptest` per `feedback_use-ptest-for-local-tests` memory: bare `pytest`/`nox` invocations
over roughly 10 CPU-minutes get killed by the orphan-test reaper on this machine.)

**Stop here if any command fails.** Do not proceed to Phase 5 or 6 on a red suite — fix
the failure or report it to the user and end the run. A generated-model change that
breaks tests is exactly the case this skill exists to catch before it ships.

## Phase 5: Read the developer blog

Find the date of the last version bump commit (`git log --follow -1 --format=%aI --
codegen/ha-version.txt` on the previous commit, or ask the user if unclear). Fetch
`https://developers.home-assistant.io/blog` and read every post published since that
date, not just titles. For each post, judge relevance against what hassette actually
touches: entity/state models, the WebSocket/REST API, the codegen extraction logic. Most
HA blog posts are integration-specific or frontend-specific and don't apply. Two patterns
are worth checking directly against `src/hassette/` before dismissing a post:

- A property/attribute rename or deprecation on a domain hassette generates models for.
  Check whether codegen already picked up the new shape (Phase 3's diff) or whether the
  old name is hardcoded somewhere in `src/hassette/` outside codegen output.
- A deprecated API hassette's hand-written code calls directly (`grep -rn <name>
  src/hassette/`). Codegen regenerating models doesn't fix a hand-written call site.

Report what you read and why each post does or doesn't need action. "Read N posts, none
applicable" is a valid, expected outcome most months.

## Phase 6: Review gate and commit

Run the `mine-review` skill on the working-tree diff before committing. This is a real
commit to a shared branch, not a throwaway change, so it gets the same code-reviewer,
integration-reviewer, and wtf-reviewer pass as any other commit (`git-workflow.md` —
Mandatory Code Review Before Commit). Verify any flagged enum/alias finding against the
upstream HA source per Phase 3 before accepting it.

Present a summary: version old to new, which files changed, test/lint results, blog
findings, review findings. Then:

```
AskUserQuestion:
  question: "Bump reviewed and clean — commit it?"
  header: "Commit"
  multiSelect: false
  options:
    - label: "Commit"
      description: "Stage the pin + regenerated files and commit with the summary above"
    - label: "Hold off"
      description: "Leave the changes uncommitted for further review"
```

Commit type is `chore` (codegen output isn't user-facing until it ships in a release)
unless a breaking change was found, in which case use `fix!`/`feat!` per
`changelog-quality.md` and get explicit user sign-off on the `BREAKING CHANGE:` footer
wording.

## Design decisions

**Why check the blog manually instead of trusting codegen's diff to catch everything?**
Codegen only sees what's in `~/source/core`'s Python source. Deprecations, migration
timelines, and "this will break in HA 2027.X" warnings live in prose, not in a diff a
generator can produce.

**Why does this skill own the compose-file image tags instead of Renovate?** The first
run (2026-08-06) hand-edited both compose files in the same commit as the codegen pin.
A review pass flagged that as duplicating a Renovate rule that already bumped the same
tags weekly — so the skill was changed to defer to Renovate instead. In practice,
Renovate's weekly PR for this one package went unreviewed; entity-model changes almost
never land in HA patch releases, so there was no forcing function to look at it between
monthly bumps. Renovate is now explicitly disabled for `homeassistant/home-assistant`
(`renovate.json`) and this skill is the sole place the tags move, in lockstep with the
codegen pin they're meant to track.

**Why verify enum-alias findings against upstream before accepting them?** This is a
recurring false-positive pattern for this specific codegen pipeline: a code reviewer
sees two `StrEnum` members with the same value and calls it a bug, when it's actually
hassette faithfully mirroring a deprecation pattern HA core already uses. Confirmed
2026-08-06 against `homeassistant/helpers/deprecation.py`'s `EnumWithDeprecatedMembers`
metaclass and `climate/const.py`'s `TARGET_TEMPERATURE`/`TEMPERATURE` pair. Worth
checking every time this shape recurs instead of re-deriving it from scratch.
