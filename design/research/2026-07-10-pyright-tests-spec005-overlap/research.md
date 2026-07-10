---
proposal: "Determine whether pyright-for-tests (#1271, 1422 errors) overlaps enough with spec 005 (test factory dedup) to fold into the same PR"
date: 2026-07-10
status: Draft
flexibility: Leaning
motivation: "Avoid redundant file edits if both changes touch the same lines; avoid unnecessary coupling if they don't"
constraints: "spec 005 is already designed and scoped; pyright-for-tests has a known error count but no design yet"
non-goals: "Not designing the full pyright-for-tests solution — just measuring overlap"
depth: deep
---

# Research Brief: Pyright-for-Tests / Spec 005 Overlap Analysis

**Initiated by**: How much does enabling pyright on `tests/` (issue #1271, 1,422 errors) overlap with the test infrastructure dedup work in spec 005?

## Context

### What prompted this

Two planned workstreams touch test files: spec 005 (factory dedup, ~53 files) and issue #1271 (pyright for tests, ~173 files with errors). The question is whether combining them into one PR would reduce rework, or whether they are independent enough to ship separately.

### Current state

`pyrightconfig.json` has `**/tests` in its `ignore` list. Removing that and running pyright produces 1,422 errors across 173 test files. Spec 005 touches ~53 files (33 test files being migrated + new files being created + test_utils being modified).

31 files have both pyright errors AND are in spec 005's migration scope, accounting for 299 of the 1,422 pyright errors (21%).

### Key constraints

- Spec 005 is already fully designed with 20 FRs and 11 ACs
- Pyright-for-tests has no design doc yet
- Both would be large PRs individually

## Feasibility Analysis

### Error distribution

| Location | Errors | % of total |
|----------|--------|------------|
| In spec 005 scope (31 files) | 299 | 21% |
| Outside spec 005 scope (142 files) | 1,123 | 79% |

Within the 299 in-scope errors, classification by rule:

| Rule | In-scope | Outside | Total |
|------|----------|---------|-------|
| reportArgumentType | 58 | 588 | 646 |
| reportAttributeAccessIssue | 133 | 190 | 323 |
| reportOptionalMemberAccess | 93 | 193 | 286 |
| reportOptionalSubscript | 4 | 31 | 35 |
| reportCallIssue | 2 | 30 | 32 |
| reportUnusedFunction | 2 | 20 | 22 |
| All other | 7 | 71 | 78 |

### Category A: Naturally fixed by spec 005 — 5 errors (1.7% of in-scope)

Only 5 of the 299 in-scope errors would be eliminated by the factory migration itself:

1. **4 reportOptionalMemberAccess in `test_execution_modes.py`** (lines 523-526) — the test reads `original_parent.app_key`, `.index`, `.unique_name`, `.class_name` from `bus.parent` (typed `Resource | None`) to copy into an inline Mock. Spec 005 replaces this block with `make_mock_parent(source_tier="framework")` using keyword defaults, eliminating the reads from the optional reference.

2. **1 reportArgumentType in `test_scheduler_job_names.py`** (line 71) — the local `make_job()` accepts `trigger: object = None` and passes it to `ScheduledJob(trigger: TriggerProtocol | None)`. Spec 005 deletes this function; the shared `make_scheduled_job(trigger: TriggerProtocol | None)` is correctly typed.

### Category B: Same file, separate fix needed — 294 errors (98.3% of in-scope)

The remaining 294 errors in spec 005 files are on lines and patterns completely unrelated to the factory migration. The dominant families:

- **133 reportAttributeAccessIssue** — mostly mock assertion attributes (`.assert_called_once()`, `.return_value`, `.call_count`) accessed on objects pyright sees as `MethodType` (bound methods of real typed classes whose internals were secretly replaced with mocks). The factory migration does not change these patterns because the mocked attributes sit inside real typed objects like `SchedulerService`, not on the factory return values themselves.

- **93 reportOptionalMemberAccess** — accessing attributes on optional-typed internal service references (`_scheduler_service: SchedulerService | None`, `_db_write_queue: Queue | None`, etc.). These are framework internals whose types don't change with the factory migration.

- **58 reportArgumentType** — type mismatches at call sites unrelated to the factories being consolidated (e.g., `SimpleNamespace` passed where `AppManifest` expected, `str` literal where `ExecutionStatus` enum expected).

### What already supports this (combining them)

Almost nothing. The 5-error natural overlap is negligible. The two workstreams address orthogonal concerns: spec 005 consolidates duplicated factory code; pyright-for-tests adds type checking to test files.

### What works against this (combining them)

- **PR size**: spec 005 alone touches ~53 files with mechanical but widespread changes. Adding 1,422 pyright fixes across 173 files would create an unreviewable PR.
- **Different fix strategies**: spec 005 is delete-local-def-add-import (mechanical, safe). Pyright fixes span inline suppressions, `assert` narrowing, `cast()` calls, enum/model constructor changes, and config-level suppressions — each requiring judgment calls.
- **Independent verification**: spec 005's acceptance criteria are testable in isolation. Pyright compliance is independently testable (`uv run pyright` with tests included). Coupling them means a failure in either domain blocks the other.

## Mock typing finding

**Does `-> MagicMock` on factory return types resolve `reportAttributeAccessIssue`?**

**Yes, fully.** The typeshed stubs declare `class NonCallableMock(Base, Any)` with `__getattr__(self, name: str) -> Any`. So:

- Mock assertion methods (`.assert_called_once()`, `.return_value`, `.call_args`): resolved via explicit declarations on `NonCallableMock`
- Domain-specific attributes (`.bus`, `.execute`, `.app_key`): resolved via `__getattr__ -> Any`
- Chained mock access (`executor.register_listener.assert_called_once()`): resolved because `Any.__getattr__` returns `Any`

**But this doesn't help with the 188+ MethodType errors in this codebase.** Those errors come from accessing mock assertions on real typed objects whose internal attributes were replaced with mocks at runtime (e.g., `svc._job_queue = MagicMock()` on a `SchedulerService`, then `svc._job_queue.add.reset_mock()`). Pyright traces `_job_queue` through `SchedulerService`'s type annotation, sees `.add` as a bound method (`MethodType`), and flags `.reset_mock()`. Changing the factory return type to `MagicMock` would break these tests because callers need both real `SchedulerService` methods and mock assertions on injected internals.

## Options Evaluated

### Option A: Ship separately (recommended)

Keep spec 005 and pyright-for-tests as independent workstreams. Spec 005 ships first (it's already designed). Pyright-for-tests gets its own issue/design/PR(s), potentially phased by error category.

**How it works**: Spec 005 proceeds as designed. Pyright-for-tests gets a separate design that phases the 1,422 errors by fix strategy. The 5 naturally-overlapping errors resolve themselves whichever ships first — if spec 005 ships first, those 5 disappear from the pyright backlog.

**Pros**:
- Each PR is reviewable in isolation
- Independent verification (spec 005: test suite passes + grep checks; pyright: zero errors with tests included)
- Spec 005 can ship immediately; pyright work can be phased
- No risk of one workstream blocking the other

**Cons**:
- 31 files touched by both (minor — the edits are on different lines)
- Theoretical merge conflict risk (low — spec 005 changes import lines and function definitions; pyright changes call sites and adds inline suppressions)

**Effort estimate**: No additional effort from separating. Slight reduction from avoiding the coordination overhead.

### Option B: Fold pyright fixes into spec 005 PR

Fix pyright errors in spec 005 files as part of the same PR, while leaving the remaining 1,123 outside-scope errors for a follow-up.

**How it works**: For each spec 005 file, fix both the factory migration AND any pyright errors. Add `tests` to pyrightconfig.json's `include` with a per-directory config that only enforces on the migrated files (or accept that the 1,123 outside errors remain as known debt).

**Pros**:
- "While we're here" — avoids re-reading 31 files later

**Cons**:
- Mixes two concerns in one PR (factory dedup + type fixes), making review harder
- Can't enable pyright for tests/ in CI until ALL 1,422 errors are fixed (or use a complex allowlist)
- The 294 non-overlapping errors in spec 005 files require different fix strategies than the factory migration
- Increases spec 005 PR size by ~294 error fixes with no shared benefit
- Forces spec 005 to wait for pyright analysis decisions

**Effort estimate**: Medium — the 294 in-scope errors need analysis and judgment calls on top of the mechanical factory migration.

## Outside-scope error analysis (Category C)

The 1,123 errors outside spec 005 scope break down into these fix-strategy groups:

### Codemod-able (mechanical transforms) — ~339 errors

| Pattern | Count | Fix |
|---------|-------|-----|
| `dict` literal where typed model expected | 158 | Replace `{"key": val}` with `ModelClass(key=val)` |
| `object()` sentinel where typed param expected | 125 | Replace `object()` with typed SENTINEL or proper default |
| String literal where enum expected | 34 | Replace `"success"` with `ExecutionStatus.SUCCESS` |
| String where `SecretStr` expected | 19 | Wrap with `SecretStr("value")` |
| String where `whenever` type expected | 3 | Replace with `ZonedDateTime.parse(...)` |

### Inline suppression (judgment required per-site) — ~345 errors

| Pattern | Count | Fix |
|---------|-------|-----|
| `reportOptionalMemberAccess` on framework internals | 193 | `assert obj is not None` before access, or `# pyright: ignore` |
| Mock assertion on `MethodType` | 102 | `# pyright: ignore[reportAttributeAccessIssue]` or `cast(MagicMock, ...)` |
| `reportOptionalSubscript` | 31 | `assert` narrowing or `# pyright: ignore` |
| `reportIndexIssue` | 19 | `# pyright: ignore` |

### Config-level (one-time) — 20 errors

| Pattern | Count | Fix |
|---------|-------|-----|
| Fixture false positives (`reportUnusedFunction`) | 10 | `executionEnvironments` in pyrightconfig.json |
| Non-fixture false positives (decorator-captured, protocol checks) | 12 | `# pyright: ignore` per-line |

### Real bugs or design issues — ~7 errors

| Pattern | Count | Fix |
|---------|-------|-----|
| Missing `await` on coroutine | 7 | Add `await` (these are genuine bugs in test code) |

### Mixed/Other — ~412 errors

Various `reportArgumentType`, `reportCallIssue`, `reportGeneralTypeIssues`, `reportReturnType`, `reportOperatorIssue`, and `reportAttributeAccessIssue` for custom app attributes, property assignment, etc. Each needs individual analysis but most follow one of the patterns above.

## reportUnusedFunction (22 errors)

Of the 22 errors: 10 are pytest fixtures (decorated with `@pytest.fixture`, using underscore-prefixed autouse convention), 12 are other functions (converter functions defined inside test methods, protocol compliance check functions, nested async helpers).

**Pyright supports per-directory config via `executionEnvironments`**. The fixture false positives can be suppressed by adding:

```json
"executionEnvironments": [
    {
        "root": "tests",
        "reportUnusedFunction": "none"
    }
]
```

This disables `reportUnusedFunction` for the entire `tests/` directory. The 12 non-fixture functions would also be suppressed, but since they are all intentionally "unused" from pyright's perspective (captured by decorators, used as protocol witnesses, or called indirectly by pytest), this is acceptable.

Alternatively, per-line `# pyright: ignore[reportUnusedFunction]` on each fixture/function keeps the rule active for genuinely unused code in tests, but adds noise to 22 lines.

## Concerns

### Technical risks
- The 102 `mock-assert-on-MethodType` errors have no clean fix. Inline suppression with `# pyright: ignore` is the pragmatic path, but `cast(MagicMock, obj.method)` is the type-correct alternative that adds verbosity to test assertions. This is a design decision that should be made explicitly for pyright-for-tests, not folded into spec 005.

### Complexity risks
- The `reportOptionalMemberAccess` errors (286 total) represent a real tension: test code accesses framework internals that are correctly typed as optional (they are `None` before initialization). Adding `assert` narrowing to 286 sites is noisy. Adding inline suppressions is mechanical but loses the type safety benefit. A per-directory `reportOptionalMemberAccess: "none"` loses real bugs.

### Maintenance risks
- Inline `# pyright: ignore` suppressions accumulate and mask future type errors. Keeping them targeted (specific rule codes, not blanket ignores) mitigates this, but the sheer volume (potentially 300+ suppressions) is a maintenance burden.

## Open Questions

- [ ] Should `reportOptionalMemberAccess` be suppressed at the directory level for tests (loses some signal but eliminates 286 errors), or handled per-site (more precise but very noisy)?
- [ ] Should mock assertion access on `MethodType` use `cast(MagicMock, ...)` (type-correct but verbose) or `# pyright: ignore` (pragmatic but suppressive)?
- [ ] Should pyright-for-tests be phased — e.g., start with codemod-able errors (339) and config fixes (22), then tackle inline suppressions (345) — or done in one pass?
- [ ] Are the 7 missing `await` errors genuine bugs that should be fixed independently as a bugfix?

## Recommendation

**Ship them separately.** The overlap is 5 errors out of 1,422 (0.35%). The two workstreams address different problems with different fix strategies. Combining them would bloat spec 005's already-large PR with 294 unrelated type fixes and force design decisions about pyright suppression strategy that don't belong in a factory dedup spec.

The codemod-able errors (339, or 24% of total) could be a good first phase for pyright-for-tests, since they represent genuine type correctness improvements (replacing `dict` literals with model constructors, string literals with enums). The inline suppressions can follow as a second phase with explicit decisions on the `reportOptionalMemberAccess` and MethodType questions.

### Suggested next steps

1. Ship spec 005 as designed — no pyright concerns to add
2. File a design doc for pyright-for-tests (separate from #1271) that addresses the suppression strategy questions above
3. Phase pyright-for-tests: (a) codemod-able fixes, (b) config-level fixes, (c) inline suppressions — each phase independently landable
4. Fix the 7 missing `await` errors immediately as a standalone bugfix PR — they are genuine bugs

## Sources

- [Pyright configuration: executionEnvironments](https://github.com/microsoft/pyright/blob/main/docs/configuration.md)
- [Pyright discussion #1738: Handling pytest fixtures](https://github.com/microsoft/pyright/discussions/1738)
