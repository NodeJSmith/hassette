# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A JSON app entry in `HASSETTE__APPS__<KEY>` is accepted but ignored

Status: open
Recorded: 2026-10-20 (3145)
Source: pre-commit-review
Reason not fixed now: out-of-scope
Affected files:
- src/hassette/config/config.py
- src/hassette/config/checks.py

Issue:
`HASSETTE__APPS__STALLING='{"filename": "s.py", "class_name": "S"}'` passes the unknown-key check (the `app-definition-json` case in `tests/unit/config/test_unknown_keys.py`), but `HassetteConfig` builds no app entry from it: `apps.apps` stays empty. The nested form (`HASSETTE__APPS__STALLING__FILENAME` and `__CLASS_NAME`) works. Reproduced on this branch; the behavior predates spec 135, which only stopped a system test from relying on the JSON form.

Why deferred:
It is a settings-source bug independent of autodetect removal, and fixing it means deciding whether the JSON form should load or be rejected by the unknown-key check, which no ratified decision covers. With this change the user at least sees the unconfigured-app warning for the class instead of nothing.

Recommended follow-up:
File an issue: make a JSON value on `HASSETTE__APPS__<KEY>` produce an app entry, or have the unknown-key check reject it with a hint naming the nested form.

Acceptance criteria:
- A JSON `HASSETTE__APPS__<KEY>` value either loads as an app entry or fails startup with a message naming the nested form; a test pins whichever is chosen.
