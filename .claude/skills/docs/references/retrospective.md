# What Made This Process Work

Lessons from the PR #970 execution (76 pages, 267 snippets, 13 task files across ~10 sessions).

## Key Lessons

1. **Phase 1 is load-bearing.** The site outline determines everything downstream. Spending disproportionate time here pays off across all writing sessions.

2. **Exemplars anchor voice.** Three reviewed pages set the voice before bulk writing begins. Without them, drift accumulates across sessions.

3. **The calibration artifact prevents session amnesia.** A single `docs-context.md` file read at session start keeps voice consistent across compactions and session boundaries.

4. **Per-page outlines prevent scope drift.** Writers with an outline produce pages that fit the site structure. Writers without outlines produce standalone pages that don't compose.

5. **Stubs from day one.** Creating stub files for every page before writing any of them means `mkdocs build --strict` stays green throughout. No broken cross-link periods.

6. **Knowledge inventory for operational pages.** Log signatures, timing values, and error messages exist only in docs. Blank-slate rewrites lose them without an explicit extraction step.

7. **Writer + reviewer subagent pairs.** The writer subagent follows the outline and voice rules. A separate reviewer subagent catches violations the writer missed. Separation of concerns matters.

8. **Mechanical checks script the quality gate.** mkdocs strict, Pyright, snippet orphans, link checker, xref coverage, bare symbols. Each is a CI-ready script, not a subjective scan.

9. **Symbol verification is non-negotiable.** Pages that reference non-existent methods or parameters are worse than pages that omit them. Verify every symbol against the actual source.
