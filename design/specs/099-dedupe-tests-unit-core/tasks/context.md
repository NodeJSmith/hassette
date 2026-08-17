# Context: Deduplicate tests/unit/core infra and remaining tests

## Problem & Motivation

`tools/check_duplicate_code.py` (PMD CPD clone detection) flags code blocks repeated 3+ times
across the repo. It's non-blocking in CI (`continue-on-error: true`) but tracks real debt. This is
the third of three splits from #1561, covering the 25 `tests/unit/core/` files not already handled
by #1616/#1633 (services) or #1617 (app/lifecycle). Ground truth: 59 flagged clusters across 15 of
the 25 scoped files; the other 10 already report zero clusters.

## Key Decisions

1. Five disjoint task groups by file family: (A) loop/blocking-IO/execution-timeout, (B)
   telemetry/DB/migration, (C) logging_service, (D) main/web_api_service, (E) unified_execution.
   No cluster's fragments span two groups.
2. Two-track resolution per cluster: **extract** mechanical boilerplate into a local
   helper/fixture; **annotate** (`# dup-ignore-start: <reason>` / `# dup-ignore-end`) genuinely
   parallel structure or cross-module-boundary "duplication" (e.g. a test asserting against
   production output that coincidentally shares shape with an unrelated production function).
   Never assume — inspect the actual fragments before choosing.
3. `tests/unit/core/conftest.py` is out of scope for *new* shared helpers. Only touch it if a
   specific cluster's fragment literally lives inside it (Group B has exactly one such cluster).
4. Some clusters include a fragment in a file outside the 25-file scope (a different test tier, or
   a production source file). Every occurrence in a cluster must be resolved — including the
   out-of-scope one — or the checker keeps reporting the cluster. These out-of-scope touches are
   marker-only (comment additions), never functional edits to production logic.

## Constraints

- Do not promote a new shared fixture/helper into `tests/unit/core/conftest.py` unless the
  specific cluster's fragment is physically inside `conftest.py` already.
- Do not extract across a test-tier or module boundary (e.g. don't merge a `tests/unit/core/` test
  body with a `tests/integration/` test body, or with a `src/hassette/` production function) — use
  `dup-ignore` there instead, with a reason naming the boundary.
- Every `dup-ignore-start`/`dup-ignore-file` marker needs a specific, non-generic reason (not
  "intentional" or "duplicate" alone) — see `tools/check_duplicate_code.py`'s module docstring for
  the exact marker syntax and validation rules.
- Preserve all existing behavior coverage. Tests may be restructured (parametrized, factored into
  a helper) but nothing they verify becomes untested.
- `tests/integration/test_command_executor.py` is touched by both Group A and Group B, at disjoint
  line ranges — each task adds only its own marker pair and must not disturb the other's.
