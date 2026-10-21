# doc-persona-review control run (2026-10-20)

Alex persona, Sonnet subagents, 4 pages x 3 briefing conditions x 2 runs = 24 results in `results/`.

- Pages: FastAPI `tutorial/first-steps`, `tutorial/path-params` (rendered HTML from fastapi.tiangolo.com); Hassette `getting-started/index`, `getting-started/first-automation` (local `mkdocs build`, main @ e0b1a490).
- Conditions: **a** = the skill briefing as it was at the time of the run; **b** = a minus voice guide + doc rules; **c** = b with neutral task wording (no "must flag", empty findings allowed, verdict rules spelled out).
- Alex's reading goal was swapped per product; everything else in the persona is unchanged.

Rerun: `extract.py <html_dir> <pages_dir>` (run from repo root; uses `tools/docs/extract_doc_page.py`), strip termynal HTML from the FastAPI first-steps line starting `$ <`, then `build.py <dir>` (expects `<dir>/pages/`, writes `<dir>/briefings/`; reads the briefing template, persona, voice guide and doc rules from `skill-snapshot/`, a verbatim copy of those files at `cf02806d^`, before the skill was reworked), dispatch one Sonnet subagent per briefing, `summ.py <results_dir>`.
