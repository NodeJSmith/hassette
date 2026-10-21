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

## KI-002: App classes defined inside module-level `if`/`try`/`with` blocks don't warn

Status: open
Recorded: 2026-10-21 (3145)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/utils/app_utils.py

Issue:
`app_class_names` only reads direct `ClassDef` statements in a module's body. A class defined under a module-level `try:`/`except ImportError`, `if sys.version_info >= ...:`, or `with` block is a module attribute the loader can resolve, but the scan never sees it, so an unconfigured one gets no warning.

Why deferred:
The warning is a newcomer hint, not a completeness check, and app files rarely guard class definitions. The user accepted this as a known limitation in the ship-time challenge.

Recommended follow-up:
If users report a missing warning for a guarded class, descend into module-level `If`/`Try`/`With` bodies (excluding `if TYPE_CHECKING:`) in `app_class_names`.

Acceptance criteria:
- An unconfigured app class defined under a module-level `try:` or `if` block produces the startup warning, and one under `if TYPE_CHECKING:` still doesn't.

## KI-003: No test pins that startup logs the unconfigured-app warnings

Status: open
Recorded: 2026-10-21 (3145)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/core.py

Issue:
`Hassette.startup_tasks` logs each string from `app_startup_warnings` at WARNING. The warnings' content is fully tested, but nothing fails if that loop is removed or its level changes.

Why deferred:
Pinning it would need a log-capture test, which the project's test rules forbid. The loop is short and visible. The user accepted this as a known limitation in the ship-time challenge.

Recommended follow-up:
If startup logging is refactored, keep the warnings flowing through a function whose return value is tested, or expose them on an observable surface (for example, a status field) that a test can assert on without capturing logs.

Acceptance criteria:
- A change that drops the startup warnings fails a test that doesn't capture log output.
