---
task_id: "T05"
title: "Scope Pyright suppressions per-file in docs config"
status: "planned"
depends_on: ["T04"]
implements: ["AC#4"]
---

## Summary

Pre-Phase 3 cleanup. Audits the global Pyright suppressions in `docs/pyrightconfig.json` and moves them to per-file exclusions where possible. New snippet files written during Phase 3 should get strict type checking by default — broad global suppressions mask real type errors in new code.

## Prompt

Work on the `docs/overhaul` branch.

### 1. Audit current suppressions

Read `docs/pyrightconfig.json`. The current config has:
- Per-directory exclusions for `pages/advanced/snippets/custom-states`, `pages/advanced/snippets/state-registry`, `pages/advanced/snippets/type-registry/base_state_convert_call.py`, and `pages/migration/snippets`
- Global error checks: `reportAttributeAccessIssue`, `reportUndefinedVariable`, `reportReturnType`, `reportUnnecessaryComparison` all set to `"error"`

The design doc flags `reportOperatorIssue` and `reportAssignmentType` as candidates for scoping — check whether these are currently suppressed globally (they may be off by default in the Pyright version used).

### 2. Identify which snippets trigger suppressions

Run `uv run pyright --project docs` with stricter settings to see what breaks. For each suppressed rule:
- Count how many snippet files trigger it
- Determine if those files are concentrated in specific directories or scattered

### 3. Move to per-file where possible

If a suppression is triggered by files in only 1–2 directories, move it from a global suppression to per-directory or per-file exclusions. If it's triggered across many directories, document why the global suppression must stay.

Update `docs/pyrightconfig.json` with the new configuration. The advanced/ snippet paths will need updating since those snippets moved to core-concepts/states/ in T01.

### 4. Verify

Run `uv run pyright --project docs` and confirm it passes with the updated config.

## Focus

**Current exclusion paths are stale after T01:** The advanced/ snippets moved to core-concepts/states/snippets/ (custom-states, state-registry, type-registry). Update the exclusion paths to match the new locations.

**Migration snippets** import `appdaemon` which isn't installed — these legitimately need suppression and should stay excluded.

**New snippets in Phase 3** should not inherit broad suppressions. The goal is: existing files that need suppression get it explicitly, new files get strict checking.

## Verify

- [ ] AC#4: `uv run pyright --project docs` passes with zero errors after config changes
