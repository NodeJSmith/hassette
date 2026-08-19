---
task_id: "T03"
title: "Split tests/unit/test_autodetect_apps.py along its four existing class boundaries"
status: "done"
depends_on: []
implements: ["FR#3", "AC#3"]
---

## Target Files

- modify: `tests/unit/test_autodetect_apps.py`
- create: `tests/unit/test_validate_apps.py`
- create: `tests/unit/test_autodetect_apps_integration.py`

## Prompt

`tests/unit/test_autodetect_apps.py` is 924 lines, exceeding the repo's 800-line file threshold
(closes issue #1580). It has four clean, non-overlapping test classes:
`TestAutoDetectAppsCurrDir`, `TestAutoDetectApps`, `TestValidateApps`, `TestAutoDetectIntegration`.

Read the full current file first, then:

1. Keep `TestAutoDetectAppsCurrDir` and `TestAutoDetectApps` in `tests/unit/test_autodetect_apps.py`.
2. Move `TestValidateApps` into a new `tests/unit/test_validate_apps.py`.
3. Move `TestAutoDetectIntegration` into a new `tests/unit/test_autodetect_apps_integration.py`.

Each file only needs the imports its own moved tests actually use — do not copy the full import
list into every file. As a starting reference (verify against the actual usages in each class
before finalizing):
- `test_autodetect_apps.py` (keeps `TestAutoDetectAppsCurrDir`, `TestAutoDetectApps`): needs
  `autodetect_apps` from `hassette.utils.app_utils`, plus whichever of `hassette.context`,
  `HassetteConfig`, `AUTODETECT_EXCLUDE_DIRS_DEFAULT`, `TEST_TOKEN`/`make_test_config` those two
  classes use.
- `test_validate_apps.py` (`TestValidateApps`): needs `HassetteConfig`, `make_test_config`, and
  `hassette.context` — does not need `AUTODETECT_EXCLUDE_DIRS_DEFAULT`, `TEST_TOKEN`, or
  `autodetect_apps` directly.
- `test_autodetect_apps_integration.py` (`TestAutoDetectIntegration`): needs `hassette.context`,
  `HassetteConfig`, `TEST_TOKEN` — does not need `AUTODETECT_EXCLUDE_DIRS_DEFAULT`,
  `make_test_config`, or `autodetect_apps` directly.
Run `prek -a` (ruff's unused-import check) after the split to catch anything copied unnecessarily.
Preserve the autouse config fixture (present per-class in the original) in each new file — do not
centralize it into a shared conftest unless it's already there.

This is a pure move — no logic, assertion, or fixture behavior changes. Give each new file a
short module docstring (3-5 lines) noting it split out of `test_autodetect_apps.py`.

## Verify

- [ ] FR#3: `TestValidateApps` lives in `test_validate_apps.py`; `TestAutoDetectIntegration` lives in `test_autodetect_apps_integration.py`; `TestAutoDetectAppsCurrDir` and `TestAutoDetectApps` remain in `test_autodetect_apps.py`. No test dropped or duplicated.
- [ ] AC#3: `uv run pytest tests/unit/test_autodetect_apps.py tests/unit/test_validate_apps.py tests/unit/test_autodetect_apps_integration.py -v` passes. Test count matches what the original single file reported before the split. Every resulting file is under 800 lines.
