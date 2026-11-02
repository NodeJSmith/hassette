---
name: doc-coverage-review
description: "Use when the user says: 'doc coverage review', 'what's undocumented', 'is everything surfaced in the docs', or 'find documentation gaps'. Inventories the user-facing surface of src/hassette area by area and reports what the docs never mention or never explain."
user-invocable: true
---

# Doc Coverage Review

Verify that everything user-facing in the source code is surfaced in the documentation. Each verification subagent owns one source area, inventories its public surface (methods, parameters, config keys, CLI flags, exceptions, exported helpers), and searches `docs/pages/` for each item.

Sibling of `doc-accuracy-review`: that skill tests whether what the docs *say* is true; this one tests whether the docs *say enough*. The two directions miss different failures — a page can be 100% accurate while an entire feature ships undocumented.

The generative rule: **a feature a user can only discover by reading the source is undocumented, no matter how public the symbol is.**

## Arguments

The source area(s) to verify. One or more of: `bus`, `scheduler`, `api`, `states`, `app`, `config`, `cli`, `exceptions`, `test-utils`, `web`. If empty, run all ten.

## Phase 1: Dispatch Inventory Agents

For each area, dispatch an **Opus** subagent (cap at 5 concurrent) with the area prompt from `REFERENCE.md` plus these shared instructions:

```
You are auditing documentation coverage for the Hassette framework
(repo root: <repo-root>). Work in two passes.

PASS 1 — INVENTORY. Build the list of user-facing items for your area
(defined below). User-facing means: an app author or operator would
call it, configure it, catch it, or see it. Exclude internal plumbing
(modules not exported via hassette/__init__.py and not reachable from
App's handles), private helpers, and framework-only machinery. For each
item record its source location.

PASS 2 — COVERAGE. For each item, search docs/pages/ (Grep, case
insensitive). Search at least twice: once for the exact symbol, once
for how a doc would describe it in prose (synonym, behavior, the
parameter's effect). Classify:
- "covered": a concept, recipe, getting-started, or operating page
  explains it (not just lists it).
- "reference-only": it appears only via the auto-generated API
  reference (its module is in PUBLIC_MODULES in
  tools/docs/gen_ref_pages.py) or only as an unexplained table entry.
- "missing": no docs presence at all.

Severity: "high" for a missing capability a user would want and cannot
discover (a method, config key, CLI command, or behavior with zero
presence); "low" for reference-only items that deserve prose, or
parameters/variants of an otherwise-documented feature.

Report every missing/reference-only item as a gap with the searches you
ran. Do NOT pad the report: an item that is genuinely internal is not a
gap — say so by excluding it from the inventory, not by listing it as
low severity.

Return only a JSON object with this shape:

{
  "area": "<your area>",
  "items_inventoried": <integer>,
  "gaps": [
    {
      "item": "<name>",
      "source_location": "<file:line>",
      "status": "missing" | "reference-only",
      "severity": "high" | "low",
      "searches_tried": ["<search>"],
      "why_user_facing": "<who would use it and how>",
      "suggested_home": "<docs page>"
    }
  ],
  "summary": "<one or two sentences>"
}
```

Strip any code fence or surrounding text from each result and parse it as JSON. It must have `area`, `items_inventoried` (an integer), `gaps` (a list) and `summary`. Each gap must have:

- `status`: `missing` or `reference-only`
- `severity`: `high` or `low`
- `item`, `source_location`, `why_user_facing`, `suggested_home`: non-empty strings
- `searches_tried`: a non-empty list of strings

If a result fails those checks, re-dispatch that area once. If the second result also fails, list the area as not reviewed in Phase 3, with the reason.

## Phase 2: Triage

Inventory agents fail in both directions; triage before trusting.

1. **False gaps.** Agents grep for the symbol name and miss prose that documents the behavior under different words. Before accepting any `missing` gap, run one independent docs search yourself using a term the agent didn't try. If you find coverage, drop the gap.
2. **Lazy inventories.** An area reporting `items_inventoried: 8` for a module with 40 public methods got a shallow pass. Compare the count against your own quick `grep -c "def \|class "` of the area's public modules. Re-dispatch an area with a large mismatch once, and if the count is still far off, list it as not reviewed in Phase 3.
3. **Scope creep.** Agents pad reports with internals to look thorough. For each gap, check `why_user_facing` against the test: would an app author or operator ever type this name? If not, discard.

## Phase 3: Present and Fix

Group confirmed gaps by area, high severity first:

```
## bus — N gaps (M items inventoried)

- **[missing / high]** `Bus.on_attribute_change(attr=...)` glob support
  Source: src/hassette/bus/bus.py:812
  Why: app authors filtering attributes need to know globs are rejected here
  Suggested home: core-concepts/bus/methods.md
```

End with a summary table (Area | Items | Missing | Reference-only). Areas with zero gaps appear in the table only. Zero gaps means none were found, not that coverage is proven. After the table, list any areas not reviewed, each with the reason, and give them no table row.

Fixing is scoped: small gaps (a missing parameter, an unexplained exception) get edited into the suggested home directly, following `.claude/rules/voice-guide.md` and `doc-rules.md` (snippets live in tested `snippets/` files). Whole missing pages are larger work — list them as recommendations instead of writing them inline, unless the user pre-authorized full fixes.

After edits: `uv run mkdocs build --strict`, and Pyright if any snippet changed.

## Design Decisions

**Why area agents instead of page agents?** Coverage is a property of the whole doc set, not a page — only a source-side inventory can find what no page mentions. Pages are the unit for accuracy; modules are the unit for coverage.

**Why two search passes per item?** The dominant failure mode is the false gap: docs explain a feature in prose without naming the symbol. Exact-match grep alone systematically over-reports.

**Why `items_inventoried`?** The count only catches a shallow pass, which Phase 2 checks against a quick `grep`. A full count with zero gaps still doesn't prove coverage. In doc-accuracy-review's seeded baseline (`design/research/2026-11-02-doc-accuracy-verification/seeded-baseline/`), a higher `claims_checked` didn't mean more errors caught.

**Why no script to extract the public surface?** The inventory requires judgment ("is this user-facing?") that a symbol dump can't make, and the area list is stable. If inventories prove unreliable, build the extractor then — not speculatively.
