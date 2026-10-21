---
status: Draft
issue: "#3148"
---

# doc-persona-review seeded-defect recall (2026-10-21)

Experiment E1 for #3148. It asks whether any briefing setup can tell a known-good page from a copy of it with planted defects, and which setup misses the fewest defects. It follows the [2026-10-20 control run](../2026-10-20-llm-doc-usability-eval/control/README.md).

## Bottom line

- **The current briefing (A) finds nearly everything, including a lot that isn't there.** It catches 94% of seeds but averages 18 findings per run on both the clean and seeded copies. That is too many to tell which ones are real, and it gives the same verdict for both copies.
- **Neutral wording alone (C) removes the noise but halves recall.** It catches 50% of seeds with no false matches. Its finding counts overlap between clean and seeded runs, so it can't tell the two copies apart run for run.
- **Two variants separate clean from seeded on every run:**
  - **P (preceding page included):** about 0 findings on clean copies against about 3 on seeded ones.
  - **S (per-step pass/fail):** more failed steps on every seeded run than on its clean counterpart.
  - **P also judged seeds the way a reader would.** F1 and H4 aren't defects once the reader has seen the previous page, and P didn't flag them.
- **None of the neutral variants catches a removed definition or a removed prerequisite.** These are F4, H3 and H4. Under neutral wording, the reviewer fills in the missing explanation itself and moves on.

## Design

- **Pages:**
  - FastAPI `tutorial/first-steps` (fetched 2026-10-21).
  - Hassette `getting-started/first-automation`, built from main after #3159.
  - Each page has a clean copy and a seeded copy with four defects (`seeds.json`).
- **Seeds, one per kind:**

  | Kind | FastAPI | Hassette |
  |---|---|---|
  | Missing step | F1: drop "copy that to a file main.py" | H1: drop "replace your apps/main.py with the complete app" |
  | Output contradicts code | F2: response says `Hello FastAPI` | H2: log says `Tick` |
  | Removed link or prerequisite | F3: drop the async "In a hurry?" note | H4: drop "the app from the Quickstart" and its link |
  | Removed definition | F4: drop the explanation of `main:app` | H3: drop the definition of a handler |

- **Conditions:** all of them use the Alex persona and Sonnet.
  - **a:** the current skill briefing.
  - **c:** the 2026-10-20 neutral condition (no voice guide or doc rules, no "must flag", verdict rules spelled out).
  - **s:** c, with the verdict replaced by a true/false check of each step: "could Alex complete it using only this page?"
  - **p:** c, plus the preceding page in nav order, given as already read. That's FastAPI `tutorial/` and Hassette `getting-started/`.
  - **t:** c, with a thin persona: knowledge boundaries and reading goal only.
- **Runs:** 2 pages × 2 copies × 5 conditions × 2 runs = 40.
  - **Blinding:** briefings had opaque, shuffled names (`build.py`). Reviewers weren't told other copies or conditions existed.
- **Scoring:** one blind Sonnet judge per page matched each run's findings, and failed steps, to the seed list (`score.py`). The judge didn't know which copy or condition a run came from. A match on a clean copy means the reviewer flagged that spot even though no defect was planted there.
  - **Spot checks:** I checked a sample of matches by hand. The judge is strict. For example, it didn't credit "unclear where to paste the combined code" as catching H1. Treat recall as a lower bound.

## Results

All seeds, seeded copies (recall), and clean copies (false matches):

| Condition | Seeded recall | Clean false-match | Mean findings, clean | Mean findings, seeded | Separates every run? |
|---|---|---|---|---|---|
| a (current) | 94% | 19% | 18.0 | 18.8 | no |
| c (neutral) | 50% | 0% | 2.8 | 3.5 | no |
| s (step checks) | 56% | 6% | 3.8 | 3.8 | yes, by failed steps |
| p (previous page) | 50% | 0% | 0.2 | 3.2 | yes, by finding count |
| t (thin persona) | 50% | 0% | 3.8 | 3.0 | no |

**What "separates" means here:**
- **s:** failed steps were FastAPI 2, 2 (clean) vs 3, 3 (seeded), and Hassette 0, 0 vs 1, 2.
- **p:** findings were FastAPI 0, 0 vs 3, 4, and Hassette 0, 1 vs 3, 3. P's verdicts nearly separate as well: 3 of 4 clean runs came back `followable`, and all 4 seeded runs `followable-with-effort`.

Seeds detected, out of 2 seeded runs:

| Seed | a | c | s | p | t |
|---|---|---|---|---|---|
| F1 missing step | 2 | 2 | 2 | 0* | 2 |
| F2 contradicting output | 2 | 2 | 2 | 2 | 2 |
| F3 removed link | 2 | 2 | 2 | 2 | 2 |
| F4 removed definition | 2 | 0 | 0 | 0 | 0 |
| H1 missing step | 2 | 0 | 1 | 2 | 0 |
| H2 contradicting output | 2 | 2 | 2 | 2 | 2 |
| H3 removed definition | 2 | 0 | 0 | 0 | 0 |
| H4 removed prerequisite | 1 | 0 | 0 | 0* | 0 |

\* These seeds aren't defects for a reader who has read the previous page. FastAPI's tutorial index says "copy the code to a file main.py", and the Quickstart is the app H4 refers to. P's misses on these are correct.

The six seeds that hold with or without the previous page are F2, F3, F4, H1, H2 and H3. On those, recall is:
- a: 100%
- p: 67%
- s: 58%
- c: 50%
- t: 50%

## What this says about the open questions

- **Q2 (what replaces the verdict):**
  - **The current verdict carries no information.** A and C gave the same verdict for clean and seeded copies.
  - **P's verdict separated clean from seeded in 7 of 8 runs.** The difference is surrounding context, not new verdict wording.
  - **Per-step pass/fail (S) separated every run.** It's the only option tested whose output is a count you can compare.
- **Q3 (reader context):** including the previous page is the strongest single change.
  - It cut clean-copy findings from about 3 to 0.2.
  - It raised H1 detection from 0/2 to 2/2.
  - It judged F1 and H4 the way a real reader would.
  - The 2026-10-20 control's guess that single-page isolation inflates findings holds.
- **Q4 (recall check):** neutral wording costs recall in a specific place: removed definitions and removed prerequisites (F4, H3, H4).
  - **Why they go unflagged:** the reviewer knows the concept itself and doesn't notice the page never explains it, even when the persona lists it as unknown, as with "handler".
  - **What A's recall actually costs:** A catches these only by flagging every term on the page. Its 18-finding baseline is that cost.
  - **Gap for any new setup:** none of the variants tested here closes it.
- **Q7 (persona thinness):** the thin persona changed nothing measurable compared with C.

## Caveats

- **Small sample:** two runs per cell, one model, and one seed of each kind per page. A single different run changes any cell by 50 points.
- **Self-consistency isn't validity:** repeated runs of one prompt and model understate the true variance (arXiv 2604.11581).
- **Seed difficulty varies:** F4 is subtle (a later snippet half-explains `main:app`), while H3 removes a term the persona explicitly doesn't know. They aren't equally hard to find.
- **Unclean context page:** in P, the FastAPI previous page still contains termynal HTML that `prep.py` only cleans from first-steps.
- **One judge:** a single judge pass; matches weren't double-scored.

## Next

- **E2 (task-based navigation) and E3 (control rerun)** come next, in that order.
- **Variant to try:** P plus S together.
- **Separate experiment:** the definition-recall gap needs its own probe. One option is a pass that lists each term the page uses that falls inside the persona's "does not know" list, then checks whether the page defines it.

## Rerun

From the repo root:

1. Extract the pages. Fetch the FastAPI HTML for `tutorial/first-steps/` and `tutorial/` into one directory, run `uv run mkdocs build`, and copy `site/pages/getting-started/{index,first-automation}/index.html` into the same directory, named `<product>--<path>.html`. Then run:
   `uv run --with beautifulsoup4 python design/research/2026-10-20-llm-doc-usability-eval/control/extract.py <html_dir> design/research/2026-10-21-persona-review-seeded-recall/pages`
2. Build the variants and briefings:
   - `uv run python .../prep.py`
   - `uv run python .../build.py <queue>`
3. Run the reviewers: for each `oNN` in `<queue>/manifest.json`, dispatch one Sonnet subagent on its briefing, writing its JSON to `<queue>/out/oNN.json`.
4. Score the runs:
   - `uv run python .../score.py judge-input <queue>`
   - Dispatch one Sonnet judge per `<queue>/judge/*.md`.
   - Then run `score.py report <queue>` and `score.py collect <queue>`.

Raw outputs, judge matches and the manifest are in `results/`.
