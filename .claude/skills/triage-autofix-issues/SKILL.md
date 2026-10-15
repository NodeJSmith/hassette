---
name: triage-autofix-issues
description: "Use when the user says: 'triage autofix issues', 'go through the needs-decision issues', 'fix the stale-spec issues', 'what is autofix stuck on', or wants help deciding the issues the autofix pipeline gave up on. Verifies each one against the current code, rewrites stale specs, walks the user through open decisions one issue at a time, and applies each outcome (requeue, close, replace, block, park, resize, defer) on GitHub."
user-invocable: true
---

# Triage Autofix Issues

The autofix pipeline picks up small, well-specified issues and gives up on the ones it can't finish safely, labeling each with the reason and usually posting a comment that explains it. This skill works through that pile: it checks each issue against the current code, settles what's left with the user, and writes the outcome back to GitHub. Each issue ends up requeued for autofix, closed, blocked with a link to what it waits on, parked, resized, or deliberately deferred.

**The principle:** an issue leaves this skill only with a decision checked against today's code. The autofixer's comment and the issue's own framing are claims to test, not facts.

## Arguments

$ARGUMENTS: optional issue numbers, or one short label name (`needs-decision`, `stale-spec`, `needs-human`, `blocked`), which maps to `autofix:<name>`. With no argument, triage every open issue in scope.

## The labels

| Label | Autofix's claim | Default handling |
|---|---|---|
| `autofix:stale-spec` | The issue text is wrong or outdated against the code | Rewrite pass (Phase 3) |
| `autofix:needs-decision` | The issue leaves a design, API, product or visual choice open | Walk-through (Phase 4) |
| `autofix:needs-human` | Anything else | Classify it first; many are really one of the above |
| `autofix:blocked` (+ `autofix:maybe-obsolete`) | It failed twice, or found nothing to change (with `maybe-obsolete`) | Check whether it already shipped; usually a close or a requeue |

A "blocked by" bail adds no label: autofix creates a GitHub dependency link and skips the issue until the blocker closes. `epic:ui-redesign` issues are parked and skipped too. Neither needs triage unless it also carries a label above.

## Phase 1: Gather

1. For issue numbers, `gh issue view <n> --json number,title,labels,body,comments,state` each. Otherwise, for each label in scope, `gh issue list --label <label> --state open --limit 200 --json number,title,labels,body,comments` into a file in the scratchpad. If a result has exactly 200 entries, it may be truncated: rerun with a higher `--limit`. Dedupe by issue number, since one issue can carry two labels.
2. For each issue, find autofix's latest bail comment. Its text starts with one of the `*_COMMENT_PREFIX` strings in the pipeline's `constants.py` (`~/Dotfiles/packages/hassette-pipeline/src/hassette_pipeline/`; if that path is absent, recognize the comment by its "Autofix …" opening). No bail comment on an `autofix:blocked` issue without `maybe-obsolete` means autofix failed it twice: look at its last autofix PR or branch, if any, for why. No bail comment on any other label means someone labeled it by hand: classify from the issue itself and say so. Check blockers with `gh api repos/NodeJSmith/hassette/issues/<n>/dependencies/blocked_by --jq '[.[] | select(.state == "open") | .number]'`; the endpoint lists closed blockers too.
3. Group the issues by what is really blocking them, not by label, and show the user the counts with example numbers. If a group of three or more shares one cause, propose the batch decision now (Phase 4, "Batch decisions"), before walking through them one at a time.

## Phase 2: Verify before deciding

Agents accept the first framing they read, which here is the autofixer's bail reason or the issue's proposed fix. A recommendation built on a wrong premise gets the user to approve the wrong fix. Autofixer framings are often wrong: one claimed HA treats `entity_id` in service data differently from `target=` (HA merges them before validation), one called a three-line fix an envelope redesign, one named the wrong source model to derive a schema from.

For every issue, before recommending anything, check:
- **Is the premise still true?** Grep the code the issue names. Has it shipped, been superseded, or moved since the issue was filed?
- **What does HA do?** For anything HA-facing, read `~/source/core`.
- **How do real users call it?** Check `~/source/hautomate`, the real-user app corpus. It's a few users, so a pattern there is evidence, but absence alone never justifies a close.
- **Does a project rule shape it?** See REFERENCE.md, "Project filters". Filters shape the recommendation; the user still makes the call.

If a source path is missing on this machine, say so. "Couldn't check" is never "checked, found nothing".

Test: could you defend this recommendation to someone who has read the code but not the issue?

## Phase 3: Stale-spec rewrite pass

Rewrite an issue without asking the user only when the fix is text drift with nothing to choose: renamed symbols, a stale file list (replace it with a rule like "every `Event[Any]` annotation in `src/` and `tests/`" so it can't go stale again), a count that changed. Before each one, ask: *would a maintainer who read the same code pick a different fix or scope, or would the PR reviewer expect something different from what the old text promised?* If either is plausible, it's a decision: move it to Phase 4. A silent rewrite is close to irreversible, because autofix implements the new text without another human look.

"Without asking" means without asking the user, not without a trace: post a comment saying what changed and why (REFERENCE.md, "Requeue"). A stale spec whose premise is gone (the "unused" field is used now, the feature shipped) is a close, and closes always go to the user.

## Phase 4: Walk through decisions

Present one issue at a time. In message text: what the issue wants, why autofix stopped, what verification found (file or line evidence), then 2–4 options with one recommended and why. Options come from REFERENCE.md, "Outcomes", plus anything the findings call for that isn't there. Include **Defer** (leave it as is, labeled) when nothing argues for acting now. Ask with `AskUserQuestion` (header `#<number>`), apply the answer (Phase 5), then show the next issue. Format: REFERENCE.md, "Presenting an issue".

The user's answer may be a question ("would it be rework, or would it move over cleanly?"). Answer it with evidence and change the recommendation if the evidence does. Don't defend the original pick.

**Batch decisions.** When three or more issues are stuck on one cause (layout decisions the UI redesign will redo, a bespoke health field per concern), propose one decision for the group: park them together, or file one design issue and block the rest on it. Separate decisions on related issues drift apart and contradict each other.

## Phase 5: Apply each outcome

Use the recipes in REFERENCE.md, "Outcomes". Before mutating, re-fetch the issue's state and labels: autofix may have changed it during a long walk-through. Every change to an existing issue gets a comment recording why. Pass bodies and comments with `--body-file`, never inline.

**Requeue only what autofix will pick up.** Check every selection condition in the Requeue recipe first. If the honest size is medium, resize instead of forcing a split.

## Phase 6: Summarize

Report:
- counts per outcome, with issue numbers
- stale specs rewritten without asking, each with a one-line note
- new issues filed
- any trend that suggests a pipeline change (a new bail category, a prompt fix)

REFERENCE.md has an example.
