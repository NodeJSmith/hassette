# Triage Autofix Issues: Reference

## Project filters

These come from `CLAUDE.md` ("Designing the Framework") and the user's standing preferences. They shape the recommendation; the user still decides.

- **Convenience APIs must earn their place.** Ask what boilerplate it saves, whether callers could write it against the primitives, and what failure modes it adds. Example: duration strings for the scheduler saved little and turned a typo into a runtime error Pyright can't catch.
- **Keep the public surface small.** New helpers go on the most specific component. Don't make something public "in case a user wants it".
- **Follow HA conventions.** Read `~/source/core` before recommending HA-facing behavior. When HA does something one way with no warning (binding `0.0.0.0`, merging `target` into service data), match it unless there's a strong, stated reason not to.
- **No compatibility shims before 1.0.** Prefer a clean break with a changelog note over keeping an old name, field or format alive. A wire field nothing consumes can go.
- **Frontend layout waits for the UI redesign.** A layout or placement fix on a page the redesign covers gets closed (the redesign redoes it) or parked under `epic:ui-redesign` (the underlying need survives). What data the API exposes is still fair game now.
- **No speculative work.** A fix for load nobody has observed, or storage for a value nothing can produce, is a close candidate. Say what would justify reopening it.
- **Fix the root cause.** When a gate or tool blocks a whole class of issues, file a fix for the tool rather than working around it in each issue. If the user wants this one unblocked now anyway, record the order change on both issues.

## Presenting an issue

Illustrative only; the issue number and details are placeholders.

```markdown
**#1234: Make the call_service entity targeting contract learnable**

The issue assumes `entity_id` in service data is "legacy-tolerated but not equivalent to `target=`." HA core disagrees: `ServiceRegistry.async_call` merges `target` into the service data before schema validation, so the two forms are equivalent for every service. The confusion comes from our docs, which never say so.

Options:
1. **Rescope to docs and requeue** (recommended). Document `target=` as preferred and state that `entity_id=` does the same thing. No warning, no API change.
2. Warn when `entity_id` appears in `**data`. That nags people about calls that work.
3. Promote `entity_id=` into `target` internally. That's code to build the request HA already builds.
4. Defer: leave it labeled as is.
```

Lead with the finding that changes the decision, and give each option its consequence in one clause. If the recommendation makes the issue autofix-ready, say so ("With option 1, I'll fix the criteria and requeue it").

## Outcomes

`<bail>` below means every `autofix:*` triage label on the issue: `needs-decision`, `stale-spec`, `needs-human`, `blocked`, `maybe-obsolete`. Remove whichever of them the issue carries with `gh issue edit <n> --remove-label <label>,<label>`. An issue's numeric `id`, needed for dependency links, comes from `gh api repos/NodeJSmith/hassette/issues/<n> --jq .id`.

### Requeue
The decision leaves concrete criteria and the work is small.
1. Check what autofix's picker requires (`select_issue()` in the pipeline's `autofix_issues.py`): `size:small`, at least one type/topic label from its allowed set, an allowed author, a title that doesn't match `OPEN_ENDED_TITLE_RE` in `dfl_common` (titles opening with words like "Investigate" or "Decide"), no open blocker, the issue still open, and no other excluded label left (`EXCLUDE_LABELS` in `dfl_common`: `autofix:pr-open`, `autofix:in-progress`, the parked labels `epic:ui-redesign` and `area:ui`, and the bail labels). If size fails, Resize instead. If the title or labels fail, fix them in step 2.
2. Save the body (`gh issue view <n> --json body --jq .body > <file>`), rewrite the criteria, then `gh issue edit <n> --body-file <file>`. Fix a failing title or label from step 1 in the same pass: `gh issue edit <n> --title "<new title>"`, `--add-label <type or topic label>`, `--remove-label <excluded label>`.
3. Post a comment starting `Decision:` (or `Spec updated:` for a Phase 3 rewrite) saying what changed.
4. Remove `<bail>` last. Then confirm the issue shows as ready in `dfl hassette eligible-issues`. If that command isn't on this machine, re-fetch the issue (`gh issue view <n> --json title,labels,state`) and recheck every step 1 condition yourself. Report it as requeued only after one of these checks passes.

### Close
The premise is gone, the feature shipped, or it doesn't earn its place. Post the reason with `gh issue comment <n> --body-file <file>`, including what would justify reopening it. Then `gh issue close <n> --reason "not planned"` (or `completed` if it shipped), and remove `<bail>`.

### Replace
The real fix differs from what the issue proposed. Rewriting the issue into a different ask hides that, so: search for duplicates, file the new issue first (see "File new"), then comment on the old one linking it, close it as not planned, and remove `<bail>`.

### Block
The work must wait for another issue. Confirm the blocker is open (`gh issue view <blocker> --json state`). Then `gh api -X POST repos/NodeJSmith/hassette/issues/<n>/dependencies/blocked_by -F issue_id=<blocker's id>`; HTTP 422 "already been taken" means the link exists. Confirm it with a GET on the same endpoint and comment with the reason.
- If the work is fully specified once the blocker lands and the issue passes the other Requeue step 1 conditions, remove `<bail>`. Autofix picks the issue up by itself when the blocker closes.
- If a choice will still be open then, set `autofix:needs-decision` instead.

### Park
A UI layout question the redesign will settle. Add `epic:ui-redesign`, remove `<bail>`, comment. Autofix skips parked labels.

### Resize
It's really a medium or large feature. `gh issue edit <n> --remove-label size:small --add-label size:medium` (one `size:` label only), remove `<bail>`, and record the decisions made so far in a comment. Autofix only picks up `size:small`.

### Defer
Nothing argues for acting now. Leave the labels alone. If verification turned up something, comment it so the next triage starts from there.

### File new
A follow-up, a root-cause fix, or a batch design issue. Follow `.claude/reference/github-workflow.md` (title, required labels, body). Search open issues for duplicates first. Link any issue it blocks.

## Summary example

Illustrative only; the numbers are placeholders.

```markdown
**Requeued after a decision (5):** #101, #102, #103, #104, #105. Criteria rewritten, decision posted.
**Requeued after a silent spec rewrite (2):** #106 (file list replaced with a rule), #107 (demo app count corrected).
**Closed (4):** #108 (field is used now), #109, #110, #111.
**Blocked (3):** #112, #113, #114 → #120.
**Parked under epic:ui-redesign (1):** #115.
**Deferred (1):** #116.
**Filed:** #120 (live health issues registry, large).

**Trend:** three issues each wanted their own health field. #120 replaces that pattern; a pipeline prompt note could have autofix flag new ones as blocked by #120.
```
