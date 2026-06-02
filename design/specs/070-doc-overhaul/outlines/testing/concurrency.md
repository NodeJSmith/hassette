# Testing — Concurrency & pytest-xdist

**Status:** Exists (52 lines), mostly GENUINE — needs JTBD metadata and minor reorder
**Voice mode:** Concept — system-as-subject
**Page type:** Depth page (concept)
**Reader's job:** Understand why their parallel tests deadlock or flake, and fix it.

## What was cut

Nothing removed. The existing page is well-structured and covers the three
concurrency concerns clearly.

Minor reorder: `DrainFailure` exception hierarchy moved up, since readers
who land here from a test failure are most likely hitting a drain exception,
not an xdist configuration issue. The xdist section is more niche (only
relevant when running `-n`).

The `pytest-asyncio Mode` section is a one-liner that duplicates content from
the Testing index. Keep it as a brief cross-reference, not a full explanation.

## Outline

### Opening line
Two isolation mechanisms. Understanding which applies when prevents deadlocks.

### H2: DrainFailure Exception Hierarchy
What `DrainFailure` means: a simulate call did not settle cleanly. Two
subclasses:
- `DrainError` — handler tasks raised exceptions. `e.task_exceptions` list.
- `DrainTimeout` — drain did not reach quiescence. Diagnostic message with
  pending task names.

`DrainTimeout` does not inherit from `TimeoutError`. Catch `DrainTimeout` or
`DrainFailure` around `simulate_*` calls, not `TimeoutError`.

Harness startup timeouts are separate `TimeoutError` — link to Test Harness
Reference.

### H2: Same-Class Concurrency (Always Applies)
Per-App-class `asyncio.Lock` around manifest read-modify-write. Brief:
- Same class, same loop: safe (reference counter handles it).
- Different classes: no conflict.

### H2: Time-Control Concurrency (freeze_time Only)
Process-global non-reentrant lock. Only one harness can hold the time lock.
Second harness raises `RuntimeError`. Released on `async with` exit.

### H2: Parallel Test Suites (pytest-xdist)
Each worker = own process = own time lock. The concern is within a worker:
`freeze_time` tests in the same worker can interleave. Fix: `xdist_group`
marker to serialize them. Not needed without `-n`.

### H2: pytest-asyncio Mode
One sentence: `asyncio_mode = "auto"` is required. Link to Testing index
for setup and false-green warning.

### H2: Next Steps
Links to Factories, Time Control, Testing index.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `testing_drain_exceptions.py` | Keep | DrainFailure catch patterns |
| `testing_xdist_group.py` | Keep | xdist group marker |

## Cross-Links

- **Links to:** Test Harness Reference (startup failures), Time Control, Factories, Testing index
- **Linked from:** Test Harness Reference (drain link), Time Control (lock interaction)
