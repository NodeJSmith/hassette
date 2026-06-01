# Testing — Concurrency & pytest-xdist

**Status:** Exists (52 lines), concise, voice polish needed
**Voice mode:** Concept — system-as-subject

## Outline

### H2: Same-Class Concurrency (Always Applies)
Why tests of the same app class can interfere; harness isolation.

### H2: Time-Control Concurrency (`freeze_time` Only)
Global time state means parallel time-control tests conflict.

### H2: Parallel Test Suites (pytest-xdist)
`--dist loadscope` requirement, why `-n auto` alone causes flakes.

### H2: pytest-asyncio Mode
`auto` mode setting.

### H2: `DrainFailure` Exception Hierarchy
What DrainFailure means and how to handle it in tests.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant files from `testing/snippets/` | Review | Concurrency examples |

## Cross-Links

- **Links to:** Testing overview, Time Control
- **Linked from:** Testing overview
