---
task_id: "T01"
title: "Fix broken include_paths filter in AppChangeDetector"
status: "planned"
depends_on: []
implements: ["FR#5", "AC#5"]
---

## Summary
Fix the `include_paths` bug in `AppChangeDetector.detect_changes()`. The current `ROOT_PATH = "root"` constant matches every DeepDiff path via substring matching (every path starts with `"root"`), and `USER_CONFIG_PATH = "user_config"` doesn't match the actual field name `app_config`. This means any manifest attribute change (display_name, autostart, etc.) triggers a reload, not just `app_config` changes. After this fix, only `app_config` field changes trigger `reload_apps`.

## Target Files
- modify: `src/hassette/core/app_change_detector.py`
- modify: `tests/unit/core/test_app_change_detector.py`

## Prompt
Fix the `include_paths` bug in `src/hassette/core/app_change_detector.py`. The constants `ROOT_PATH = "root"` and `USER_CONFIG_PATH = "user_config"` (lines 13-14) are passed to `DeepDiff(..., include_paths=[ROOT_PATH, USER_CONFIG_PATH])` (line 72), but DeepDiff's `_skip_this` uses substring matching — `"root"` matches every path since all paths start with `"root"`.

Test against actual DeepDiff behavior to determine the fix approach:
1. Try fixing the constants to match the actual attribute access paths DeepDiff generates (e.g., paths containing `.app_config`).
2. If substring matching makes precise `include_paths` filtering impractical, remove `include_paths` entirely and filter the diff result in the detector's own logic — only keep diff entries that affect `app_config`.

Add tests in `tests/unit/core/test_app_change_detector.py` verifying:
- A change to `display_name` only does NOT trigger a reload (not in `reload_apps`)
- A change to `autostart` only does NOT trigger a reload
- A change to `app_config` still DOES trigger a reload
- Existing tests continue to pass (the fix narrows detection, so overly-broad tests may need adjustment)

See design doc `## Architecture → Component changes → AppChangeDetector` for details.

## Focus
- The `include_paths` parameter uses DeepDiff's internal `_skip_this` method which does substring matching — verify this empirically before committing to the fix approach.
- The design doc's open question was deferred to implementation: if substring matching makes precise filtering impractical, remove `include_paths` entirely and filter in the detector's own code.
- `affected_root_keys` (line 96) extracts the top-level dict key from the diff — this must still work correctly after the fix.
- Existing tests in `test_app_change_detector.py` currently pass because the bug makes detection overly broad; the fix narrows it, so some tests may need updating if they relied on non-config changes triggering reloads.
- **Deferred open question:** The exact `include_paths` fix approach depends on testing against actual DeepDiff behavior. If substring matching makes precise field-level filtering impractical, remove `include_paths` entirely and filter the diff result in the detector's own code. Decide during implementation based on empirical testing.

## Verify
- [ ] FR#5: A unit test changes only `display_name` on a manifest and verifies `detect_changes` does not include the app key in `reload_apps`
- [ ] AC#5: Same test as FR#5 — changes only `display_name`, verifies no reload triggered
