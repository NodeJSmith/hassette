# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: Framework-owned names on App and Resource can collide with a user subclass

Status: open
Recorded: 2026-11-06 (3679)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/app/app.py
- src/hassette/resources/base.py

Issue:
The change adds public, non-`@final` names: `App.debug_capture`, `App.set_debug_capture`, `App.apply_lifecycle_log_level`, `App.reapply_log_levels`, and `Resource.logger_author`, `Resource.apply_own_log_level`, `Resource.reapply_log_levels`. A user app that already defines `debug_capture` or one of these method names overrides framework state silently. Writing `debug_capture` after construction diverges the mirror until the next toggle repairs it.

Why deferred:
The trigger needs a name collision on upgrade, the names are hidden from `dir()` by `_APP_PUBLIC_API`, and the existing framework-internal names on `App` (`config_log_level`, `owner_framework_log_level`, `owner_log_identity`) follow the same public, non-final convention. Enforcing only the new names would split the convention.

Recommended follow-up:
If a collision is ever reported, decide the convention for all framework-owned `App`/`Resource` names at once: `@final` methods and a read-only property over a private slot for the mirror.

Acceptance criteria:
- A user subclass overriding a framework-owned method fails at class creation, and writing the capture mirror raises.
