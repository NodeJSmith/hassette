---
proposal: "Evaluate existing linters and best practices for detecting accidentally swallowed asyncio.CancelledError, and determine whether to adopt a tool or build a custom checker."
date: 2026-05-02
status: Draft
flexibility: Exploring
motivation: "Bare except BaseException blocks that suppress CancelledError silently break graceful shutdown. Issue #676 calls for an audit and ongoing prevention."
constraints: "Python 3.11+, asyncio-only (no trio/anyio in user apps), ruff is the primary linter"
non-goals: "Not building a general-purpose async linter; not auditing trio/anyio patterns"
depth: normal
---

# Research Brief: Linting for Swallowed CancelledError

**Initiated by**: Issue #676 -- Audit codebase for accidentally swallowed CancelledError

## Context

### What prompted this

Issue #676 (spawned from the async task management research brief) identified that `except BaseException` or bare `except:` blocks that suppress `asyncio.CancelledError` silently break graceful shutdown. Tasks that should be cancelled instead run to completion or loop indefinitely, undermining TaskBucket's shutdown timeout infrastructure.

Since Python 3.9, `CancelledError` inherits from `BaseException` (not `Exception`), which means `except Exception` is safe -- but `except BaseException` and bare `except:` without re-raise still catch it.

### Current state

Hassette uses **ruff** as its primary linter (configured in `ruff.toml`) with bugbear (`B`) rules enabled. Pre-commit runs `ruff-check` with `--fix`. Pyright handles type checking. There is no async-specific linting beyond what ruff provides.

Current codebase state:
- **0** bare `except:` clauses in `src/`
- **2** `except BaseException` blocks in `src/`:
  - `src/hassette/core/database_service.py:301` -- **safe**: re-raises unconditionally
  - `src/hassette/web/routes/ws.py:100` -- **BUG**: does not re-raise; swallows CancelledError when it falls through the disconnect-checking conditionals
- **108** `except Exception` blocks in `src/` -- all safe for CancelledError in Python 3.11+ (CancelledError is a BaseException subclass, not caught by `except Exception`)

### Key constraints

- Python 3.11+ only (CancelledError is BaseException since 3.9; no 3.8 compatibility concern)
- Ruff is the primary linter; adding flake8 as a parallel tool adds complexity
- The project already uses anyio in the websocket layer (`anyio.create_task_group`), but user apps are asyncio-only

## Findings

### 1. Do existing linters catch this?

| Linter | Rule | Catches swallowed CancelledError? | Available in ruff? |
|--------|------|----------------------------------|-------------------|
| **flake8-async** | ASYNC103 (no-reraise-cancelled) | Yes -- flags `except BaseException` / bare `except:` / `except CancelledError` without re-raise. Handles conditional branches (both if/else must raise). Checks both async and sync functions. | **No** -- ruff has not implemented ASYNC103 |
| **flake8-async** | ASYNC104 (cancelled-not-raised) | Yes -- specifically flags `return` or raising a different exception in cancellation handlers | **No** -- ruff has not implemented ASYNC104 |
| **flake8-bugbear** | B036 (except-BaseException-no-reraise) | Partially -- flags `except BaseException` without `raise` at top-level of handler. Not async-specific; misses `except CancelledError` specifically. | **No** -- ruff stops at B035 |
| **ruff** | E722 (bare-except) | Only bare `except:` -- not `except BaseException` | Yes (already enabled) |
| **pylint** | W0718 (broad-exception-caught) | Warns about `except Exception` being too broad; does not specifically check for CancelledError re-raise or async context | N/A (not used) |
| **pyright/mypy** | None | Type checkers have no rules for exception handling flow analysis | N/A |

**Summary**: The only tool that specifically and correctly catches swallowed CancelledError is **flake8-async** (ASYNC103 + ASYNC104). Neither ruff nor any other tool currently in hassette's toolchain covers this gap.

### 2. What scope should a checker have?

Based on flake8-async's implementation and the Python documentation:

**Function scope: `async def` only, or also sync?**
flake8-async checks both async and sync functions indiscriminately. This is correct -- a sync function can contain `try`/`except BaseException` around code that calls coroutines via `await` if it's actually an async function that lost its `async` keyword (unlikely), or more commonly, sync functions that are callbacks from async frameworks. However, the pragmatic answer for hassette is: **focus on `async def` first** -- that's where 99% of CancelledError propagation happens. Sync-function catches of BaseException are a code smell but not an async-cancellation risk in this codebase.

**Exception types: which catches to flag?**
- `except BaseException` without re-raise: **Always flag.** This is the primary vector.
- Bare `except:` without re-raise: **Always flag.** Equivalent to `except BaseException`.
- `except asyncio.CancelledError` without re-raise: **Always flag.** Explicit suppression.
- `except Exception`: **Do NOT flag.** Safe in Python 3.9+. CancelledError is not a subclass of Exception.

**Conditional re-raises: flag or allow?**
flake8-async's approach is sound: a conditional re-raise (e.g., `if some_condition: raise`) is flagged by ASYNC103 unless **all** branches re-raise. This matches the ws.py bug -- the handler only logs, never re-raises, meaning CancelledError is swallowed on every code path.

### 3. How do major async frameworks handle this?

**Python asyncio documentation** (official):
> "In case `asyncio.CancelledError` is explicitly caught, it should generally be propagated when clean-up is complete."
> "In almost all situations the exception must be re-raised."
> "The asyncio components that enable structured concurrency, like `asyncio.TaskGroup` and `asyncio.timeout()`, are implemented using cancellation internally and might misbehave if a coroutine swallows `asyncio.CancelledError`."

**trio**: Uses `trio.Cancelled` (BaseException subclass). The documentation and linting ecosystem (flake8-async was originally flake8-trio) are the most mature. Level-triggered cancellation means suppressing Cancelled breaks the cancel scope entirely.

**anyio**: Uses `get_cancelled_exc_class()` to abstract over trio/asyncio. Same rule: always re-raise. anyio's `create_task_group` (used in hassette's ws.py) wraps exceptions in `BaseExceptionGroup`, which adds a wrinkle -- `except BaseException` catches the group, but `CancelledError` may be nested inside it.

**BaseExceptionGroup interaction** (Python 3.11+): When a `TaskGroup` or `anyio.create_task_group` wraps multiple failures, cancellation errors can end up inside a `BaseExceptionGroup`. The ws.py handler already handles this case with `exc.split(_is_disconnect)`, but it still does not re-raise after processing. This is an edge case that simple AST-based checkers struggle with -- flake8-async added `except*` support for this in recent versions.

**PEP 789** (in-progress): Proposes `sys.prevent_yields()` to prevent task-cancellation bugs in async generators. Focused on a different (but related) class of cancellation bugs. Not yet accepted.

### 4. Existing tools that could be adopted

| Tool | Approach | Pros | Cons |
|------|----------|------|------|
| **flake8-async** (standalone) | AST visitor; runs without flake8 | Covers ASYNC103/104 exactly; handles conditional branches, `except*`, match-case; pre-commit hook available; maintained by python-trio | Does not respect `# noqa`; no config file support in standalone mode; adds a parallel linter alongside ruff; asyncio-specific rules still have open gaps (issue #257) |
| **flake8-async** (via flake8) | Same checker, flake8 plugin | Full `# noqa` support; config via setup.cfg/tox.ini | Adds flake8 as a dependency alongside ruff; heavier |
| **Custom pygrep hook** | Regex-based pre-commit | Zero dependencies; trivial to add | Cannot check conditional re-raises; high false-positive rate; misses `except CancelledError` |
| **Custom AST script** | Python script using `ast` module | Full control; can be tailored to hassette patterns | Maintenance burden; reinventing flake8-async poorly |
| **Wait for ruff** | ruff issue #8451 tracks flake8-async rules | Zero new tooling; native integration | ASYNC103/104 not on any roadmap; could be months or years |

## Options Evaluated

### Option A: Adopt flake8-async as a pre-commit hook (standalone mode)

**How it works**: Add `flake8-async` to `.pre-commit-config.yaml` as a standalone checker alongside ruff. Configure it to run only the rules relevant to hassette: `--enable ASYNC103,ASYNC104`. It runs as its own pre-commit hook, independent of flake8.

The standalone mode invokes `flake8-async` directly (not through flake8), which means it has no config file support and does not respect `# noqa` comments. For hassette, this is acceptable because:
- There are only 2 `except BaseException` blocks in the entire codebase
- One is already correct (re-raises); the other is a genuine bug
- False positives would be rare and easy to suppress by restructuring code

**Pros**:
- Battle-tested implementation with correct handling of conditional branches, `except*`, and match-case
- Maintained by the python-trio team (active development through 2025/2026)
- Pre-commit hook is a single YAML block -- minimal setup
- Catches the exact bug class that issue #676 targets
- Also catches `except CancelledError` without re-raise, not just `except BaseException`

**Cons**:
- Adds a second Python linter alongside ruff (minor toolchain complexity)
- Standalone mode does not respect `# noqa` comments (must restructure code instead of suppressing)
- Some rules (ASYNC102) have known gaps for asyncio's edge-based cancellation semantics
- The tool requires `import asyncio` to be present in a file to activate asyncio-specific checks

**Effort estimate**: Small -- one pre-commit config block, one `uv add --dev` (or just the pre-commit hook), fix the one existing bug in ws.py.

**Dependencies**: `flake8-async` (PyPI package, no transitive dependencies beyond Python stdlib)

### Option B: Add a targeted pygrep pre-commit hook

**How it works**: Add a `pygrep`-based pre-commit hook that flags `except BaseException` and bare `except:` in Python files. Similar to the existing `no-mypy-ignore` hook in the project.

```yaml
- id: no-swallowed-base-exception
  name: 'Flag except BaseException without re-raise'
  language: pygrep
  types: [python]
  entry: 'except\s+(BaseException)\s*[:\[]'
```

This would flag any `except BaseException` for manual review but cannot verify whether the handler re-raises.

**Pros**:
- Zero dependencies -- uses pre-commit's built-in pygrep
- Familiar pattern (project already uses pygrep for `no-mypy-ignore`)
- Instant to add

**Cons**:
- Cannot check if the handler re-raises -- flags `database_service.py` (correct code) as a false positive
- Cannot check conditional re-raises
- Does not catch `except asyncio.CancelledError` specifically
- Not a real lint rule -- just pattern matching

**Effort estimate**: Small -- but limited value beyond a reminder.

### Option C: Do the audit manually, add a CLAUDE.md convention, skip automated checking

**How it works**: Complete the audit from issue #676 (grep + manual review of each handler), fix the ws.py bug, add a convention note in CLAUDE.md about CancelledError handling, and rely on code review to catch future violations.

**Pros**:
- No new tooling
- Zero ongoing maintenance
- The codebase has only 2 instances today -- the problem is currently small

**Cons**:
- No automated prevention -- relies entirely on reviewer knowledge
- As the codebase grows, new `except BaseException` blocks may appear without review
- Code review is fallible for subtle async cancellation bugs
- Does not catch the bug class proactively

**Effort estimate**: Small -- audit + one fix + one CLAUDE.md addition.

## Concerns

### Technical risks
- **flake8-async's asyncio gaps**: Issue #257 explicitly notes that some rules (ASYNC102) do not apply to asyncio due to different cancellation semantics (edge-based vs level-based). ASYNC103/104 are less affected because "always re-raise CancelledError" is universal across frameworks, but edge cases around `BaseExceptionGroup` handling may produce false positives or false negatives.
- **ws.py's BaseExceptionGroup handling**: The existing `except BaseException` in ws.py deliberately catches `BaseExceptionGroup` from anyio's task group. A fix must handle both the group case and the plain CancelledError case while still cleaning up disconnects. This is not a simple "add `raise`" fix.

### Complexity risks
- Adding flake8-async alongside ruff means two Python linters with different config mechanisms. Developers need to know which tool catches which class of bug. This is manageable but non-zero cognitive overhead.

### Maintenance risks
- flake8-async is actively maintained but is a niche tool. If the python-trio team stops maintaining it and ruff never implements ASYNC103/104, the hook becomes a dead dependency.
- Ruff issue #8451 tracks implementing flake8-async rules, but ASYNC103/104 are among the harder rules to implement (they require flow analysis). No timeline is published.

## Open Questions

- [ ] Should the ws.py fix re-raise CancelledError specifically, or should it restructure to use `except*` (Python 3.11+ feature) for cleaner BaseExceptionGroup handling?
- [ ] Is there appetite for adding flake8-async as a dev dependency, or is the "audit + convention" approach preferred given only 2 current instances?
- [ ] Should the checker also run in CI (GitHub Actions), or is pre-commit sufficient?

## Recommendation

**For the immediate audit (issue #676)**: Option C is sufficient. Grep the codebase, fix the ws.py bug, add a CLAUDE.md note. The problem surface is tiny today (2 instances, 1 bug).

**For ongoing prevention**: Option A (flake8-async pre-commit hook) is the right long-term answer, but it can be deferred until after the audit is complete. The tool exists, it works, and it catches exactly this bug class. Adding it as a pre-commit hook is a 5-minute change. The pragmatic path:

1. Complete the audit and fix ws.py (issue #676)
2. Add a CLAUDE.md convention note about CancelledError handling
3. Add flake8-async as a pre-commit hook (ASYNC103 + ASYNC104 only) in the same PR or a follow-up
4. Monitor ruff issue #8451 -- if ruff implements ASYNC103/104, drop flake8-async

Do **not** write a custom AST checker. flake8-async already handles conditional branches, `except*`, and match-case correctly. Reimplementing that logic would be wasted effort.

### Suggested next steps
1. Fix the ws.py bug (the `except BaseException` handler at line 100 that swallows CancelledError)
2. Add a CancelledError handling convention to CLAUDE.md
3. Optionally add flake8-async pre-commit hook: `--enable ASYNC103,ASYNC104`
4. Close issue #676 with the audit results

## Sources

- [flake8-async rules documentation](https://flake8-async.readthedocs.io/en/latest/rules.html)
- [flake8-async installation/usage](https://flake8-async.readthedocs.io/en/stable/usage.html)
- [flake8-async issue #257: asyncio-specific ASYNC3xx rules](https://github.com/python-trio/flake8-async/issues/257)
- [Ruff issue #8451: Implement flake8-async rules](https://github.com/astral-sh/ruff/issues/8451)
- [Ruff rules list (flake8-async category)](https://docs.astral.sh/ruff/rules/#flake8-async)
- [Ruff E722 bare-except](https://docs.astral.sh/ruff/rules/bare-except/)
- [Ruff issue #21518: BaseException should also be considered as bare except](https://github.com/astral-sh/ruff/issues/21518)
- [Python asyncio exceptions documentation](https://docs.python.org/3/library/asyncio-exceptions.html)
- [Python asyncio tasks documentation](https://docs.python.org/3/library/asyncio-task.html)
- [Python asyncio dev documentation](https://docs.python.org/3/library/asyncio-dev.html)
- [PEP 789: Preventing task-cancellation bugs](https://peps.python.org/pep-0789/)
- [flake8-bugbear (B036 rule)](https://github.com/PyCQA/flake8-bugbear)
- [AnyIO cancellation documentation](https://anyio.readthedocs.io/en/stable/cancellation.html)
- [pylint broad-exception-caught W0718](https://pylint.readthedocs.io/en/latest/user_guide/messages/warning/broad-exception-caught.html)
- [pylint issue #2853: CancelledError + try-except-raise warning](https://github.com/pylint-dev/pylint/issues/2853)
- [BaseExceptionGroup + CancelledError + asyncio.timeout discussion](https://discuss.python.org/t/baseexceptiongroup-containing-cancellederror-catched-by-asyncio-timeout/26336)
