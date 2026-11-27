# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A stopped sibling key's config view loses its schema after a shared file re-imports

Status: open
Recorded: 2026-11-27 (1697)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/utils/app_utils.py
- src/hassette/web/config_view.py

Issue:
App keys A and B share one file. A forced reload of A re-imports the file and replaces its record with a fresh one holding only A's class. While B is stopped, disabled or not autostarted, `cached_class` returns None for B, so B's config view masks every string until B loads again.

Why deferred:
It fails safe (over-masking), clears when B starts, and needs a multi-key file, a stopped sibling and a UI visit at once.

Recommended follow-up:
If it shows up, let `cached_class` read the class from a current record's module without importing (getattr plus the app-class check) and cache it on the record.

Acceptance criteria:
- After a sibling key's forced reload, a stopped key's config view shows its schema.

## KI-002: A plain import can record the new file's hash over stale bytecode

Status: open
Recorded: 2026-11-27 (1697)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/utils/app_utils.py

Issue:
Only a forced re-import deletes the cached `.pyc`. A same-size edit saved in the same second as the last compile, then plain-imported by a fresh process, runs the stale bytecode while the record stores the new file's hash, so a later Reload logs "file unchanged" and reuses it.

Why deferred:
The staleness predates this change (`importlib.reload` read the same `.pyc`), needs a one-second coincidence plus a restart, and clears on the next save. Leaving plain-load records hashless would change D2 on every startup to guard it.

Recommended follow-up:
If it's ever seen, record the hash only for imports that deleted the `.pyc` first.

Acceptance criteria:
- A Reload after this sequence re-imports and runs the current source.

## KI-003: Module records are keyed by manifest path, not module name

Status: open
Recorded: 2026-11-27 (1697)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/utils/app_utils.py

Issue:
`APP_MODULES` is keyed by the manifest's path while a module's identity is its name in `sys.modules`. Two spellings of one module's path get two records, and dependent modules (no manifest path) can't have one.

Why deferred:
Today it needs an unusual layout. #4498 adds records for dependents and has to rework the key then.

Recommended follow-up:
Rekey by canonical module name as part of #4498.

Acceptance criteria:
- One module has one record however its path is spelled.

## KI-004: A cached failure re-raised on plain loads grows its traceback

Status: open
Recorded: 2026-11-27 (1697)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/utils/app_utils.py

Issue:
`read_app_class` re-raises the stored exception object, so every plain load that reaches the loader for a failed record appends frames to its traceback.

Why deferred:
The factory's `cached_load_error` check stops most such loads, any forced load replaces the record, and the old cache re-raised the same way.

Recommended follow-up:
If it shows up in logs, re-raise a copy or reset the traceback before raising.

Acceptance criteria:
- Repeated plain loads of a failed module report a traceback of constant length.
