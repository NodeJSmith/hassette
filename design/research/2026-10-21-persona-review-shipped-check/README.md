---
status: Draft
issue: "#3148"
---

# Shipped doc-persona-review check (2026-10-21)

Experiment E3 for #3148. It reruns the [2026-10-20 control](../2026-10-20-llm-doc-usability-eval/control/README.md) pages and [E1's](../2026-10-21-persona-review-seeded-recall/README.md) seeded copies through the reworked skill's own briefing template (`.claude/skills/doc-persona-review/references/briefing-template.md` at `cf02806d`), not a lab variant of it.

## Bottom line

- **The shipped skill no longer returns the same result for every page.** FastAPI and Hassette clean pages came back with 0–1 findings per run. The old briefing gave 13–25 on all four pages, and its verdict was identical everywhere.
- **It separates clean from seeded copies on every run.** Clean copies had 0 or 1 finding, and every seeded run had 2.
- **Every clean-page finding was real.** The one recurring finding on FastAPI's first-steps is a genuine inconsistency in FastAPI's own docs: the sample `openapi.json` shows an `/items/` path the page's app doesn't define.
- **Recall on the planted defects is 50%, down from 67% for E1's `p` setup.** The difference is one seed, F3. Its removed note pointed readers to the async explainer, but the page's code runs whether or not the reader understands `async def`. That makes it a "slows you down" problem, which the shipped bar leaves out on purpose. Every seed that stops a reader or makes them do the wrong thing was caught on both runs.

## Design

- **Pages:**
  - FastAPI `tutorial/first-steps` (E1's clean and seeded copies) and `tutorial/path-params` (fetched 2026-10-21).
  - Hassette `getting-started/first-automation` (E1's clean and seeded copies) and `getting-started/index` (current site).
- **Earlier pages:**
  - Hassette pages get up to three earlier pages from the built site, the same way the shipped assembler finds them.
  - FastAPI pages get the earlier pages of FastAPI's tutorial section (`FASTAPI_PRIOR` in `build.py`).
- **FastAPI wording:** the template's two Hassette-specific phrases are swapped for FastAPI ones (`FASTAPI_SWAPS`). Nothing else changes.
- **Runs:** Sonnet `standard-worker`, 6 briefings × 2 runs = 12, under shuffled opaque names.
- **Scoring:** E1's `score.py judge-input`, with one blind Sonnet judge per seeded page. Seeds are in E1's `seeds.json`.

## Results

| Page | Copy | Findings per run | Seeds matched per run |
|---|---|---|---|
| FastAPI first-steps | clean | 1, 1 | – |
| FastAPI first-steps | seeded | 2, 2 | F2 ; F2 |
| FastAPI path-params | clean | 0, 0 | – |
| Hassette first-automation | clean | 0, 0 | – |
| Hassette first-automation | seeded | 2, 2 | H1, H2 ; H1, H2 |
| Hassette getting-started index | clean | 1, 0 | – |

For comparison, the 2026-10-20 control's current briefing (A) gave 13–24 findings on the FastAPI pages and 15–22 on the Hassette pages, with `followable-with-effort` on all of them.

Seeds that are defects with the earlier pages read (E1 established that F1 and H4 aren't):

| Seed | Kind | E1 `p` | Shipped |
|---|---|---|---|
| F2 | output contradicts code | 2/2 | 2/2 |
| F3 | removed link to async explainer | 2/2 | 0/2 |
| F4 | removed definition (`main:app`) | 0/2 | 0/2 |
| H1 | missing step (replace `apps/main.py`) | 2/2 | 2/2 |
| H2 | output contradicts code | 2/2 | 2/2 |
| H3 | removed definition (handler) | 0/2 | 0/2 |

F4 and H3 leave a partial explanation behind, as E1 found, so neither setup is tested on a clean removal.

The non-seed findings:
- **FastAPI first-steps, both clean runs and both seeded runs:** the sample `openapi.json` shows an `/items/` path the page's app doesn't define. FastAPI's own page has this inconsistency.
- **Hassette getting-started index, one run:** the step 5 sample log omits the line a reader who changed `data_dir` would look for.

Raw outputs, the judge files and the manifest are in `results/`.

## Limits

- **Two runs per cell, one model, four pages.** One different run moves any cell by 50 points.
- **The definition seeds aren't clean removals.** Recall on a fully removed definition is still unmeasured.
- **The Hassette seeded copies are older than the current site.** They were built from main after #3159, while their earlier pages come from the current build. No getting-started page changed in between.
