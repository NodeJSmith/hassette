---
status: Draft
issue: "#3148"
---

# doc-persona-review seeded-defect recall (2026-10-21)

Experiment E1 for #3148, plus two follow-up conditions. It asks whether any briefing setup can tell a known-good page from a copy of it with planted defects, and which setup misses the fewest defects. It follows the [2026-10-20 control run](../2026-10-20-llm-doc-usability-eval/control/README.md).

## Bottom line

- **The current briefing (A) finds nearly everything, including a lot that isn't there.** It catches 94% of seeds but averages 18 findings per run on both the clean and seeded copies. That is too many to tell which ones are real, and it gives the same verdict for both copies.
- **Neutral wording alone (C) removes the noise but costs recall.** It catches 56% of seeds with no false matches. Its finding counts overlap between clean and seeded runs, so it can't tell the two copies apart run for run.
- **Including the preceding page (P) is the best single setup.**
  - Clean copies average 0.2 findings, seeded ones 3.2, so it separates every run.
  - It ties for the best recall on the seeds that hold with that context.
  - It judged F1 and H4 the way a reader would: they aren't defects once the previous page has been read.
- **Per-step pass/fail (S) also separates every run, by number of failed steps.**
- **The two follow-ups added nothing:**
  - **Previous page + step checks (PS):** step counts no longer separate clean from seeded on FastAPI.
  - **Previous page + definition check (PD):** recall stays the same, and clean-copy findings rise tenfold over P.
- **The "removed definition" seeds were too soft to test what they were meant to.** In both cases the remaining text still half-explains the term. The definition check listed both terms and counted that leftover context as an explanation. Whether reviewers miss a truly removed definition is still untested.

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

- **Conditions:** all use the Alex persona and Sonnet. `build.py` builds them from one letter per change.
  - **a:** the current skill briefing.
  - **c:** the 2026-10-20 neutral condition (no voice guide or doc rules, no "must flag", verdict rules spelled out). Every condition below starts from c.
  - **s:** the verdict replaced by a true/false check of each step: "could Alex complete it using only this page?"
  - **p:** the preceding page in nav order, given as already read. That's FastAPI `tutorial/` and Hassette `getting-started/`.
  - **t:** a thin persona with knowledge boundaries and reading goal only.
  - **ps:** p and s together.
  - **pd:** p plus a vocabulary check. The reviewer lists every term the page uses that Alex wouldn't know, and marks whether this page or the previous one explains it at or before first use.
- **Runs:** 2 pages × 2 copies × 7 conditions × 2 runs = 56.
  - **Batches:** E1 ran conditions a, c, s, p and t; the follow-up batch ran ps and pd.
  - **Blinding:** briefings had opaque, shuffled names (`build.py`). Reviewers weren't told other copies or conditions existed.
- **Scoring:** both batches were pooled under freshly shuffled run IDs (`score.py merge`) and scored in one pass.
  - **The judge:** one blind Sonnet judge per page matched each run's findings, failed steps and unexplained terms to the seed list. It didn't know which copy or condition a run came from.
  - **Clean copies:** a match there means the reviewer flagged that spot even though no defect was planted.
  - **Spot checks:** I checked a sample of matches by hand. The judge is strict. For example, it didn't credit "unclear where to paste the combined code" as catching H1. Treat recall as a lower bound.
  - **Judge variance:** an earlier judge pass over E1 alone differed by one match in two cells. That's about one match of noise per cell.

## Results

All seeds, seeded copies (recall), and clean copies (false matches):

| Condition | Seeded recall | Clean false-match | Mean findings, clean | Mean findings, seeded | Separates every run? |
|---|---|---|---|---|---|
| a (current) | 94% | 12% | 18.0 | 18.8 | no |
| c (neutral) | 56% | 0% | 2.8 | 3.5 | no |
| s (step checks) | 56% | 6% | 3.8 | 3.8 | yes, by failed steps |
| p (previous page) | 50% | 0% | 0.2 | 3.2 | yes, by finding count |
| t (thin persona) | 50% | 0% | 3.8 | 3.0 | no |
| ps (previous page + steps) | 50% | 0% | 0.8 | 3.0 | no single measure does |
| pd (previous page + vocabulary) | 56% | 0% | 2.0 | 3.5 | no |

**What "separates" means here:**
- **s:** failed steps were FastAPI 2, 2 (clean) vs 3, 3 (seeded), and Hassette 0, 0 vs 2, 1.
- **p:** findings were FastAPI 0, 0 vs 4, 3, and Hassette 0, 1 vs 3, 3. P's verdicts nearly separate as well: 3 of 4 clean runs came back `followable`, and all 4 seeded runs `followable-with-effort`.
- **ps:** it separates FastAPI by finding count and Hassette by failed steps, but neither measure works on both pages. On FastAPI, failed steps were 1, 0 vs 1, 1.

Seeds detected, out of 2 seeded runs:

| Seed | a | c | s | p | t | ps | pd |
|---|---|---|---|---|---|---|---|
| F1 missing step | 2 | 2 | 2 | 0* | 2 | 1* | 1* |
| F2 contradicting output | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| F3 removed link | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| F4 removed definition | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| H1 missing step | 2 | 1 | 1 | 2 | 0 | 1 | 2 |
| H2 contradicting output | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| H3 removed definition | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| H4 removed prerequisite | 1 | 0 | 0 | 0* | 0 | 0* | 0* |

\* These seeds aren't defects for a reader who has read the previous page. FastAPI's tutorial index says "copy the code to a file main.py", and the Quickstart is the app H4 refers to. Misses on these by p, ps and pd are correct.

The six seeds that hold with or without the previous page are F2, F3, F4, H1, H2 and H3. On those, recall is:
- a: 100%
- p and pd: 67%
- c, s and ps: 58%
- t: 50%

### Why the definition seeds went undetected

The `pd` term lists show the reviewer did list both terms. It then counted what the page still says as an explanation:

- **H3:** the seeded sentence still reads "registers a handler that fires whenever an entity's state changes", and reviewers marked "handler" as explained by that. That's a defensible reading: the sentence describes what a handler does.
- **F4:** a later snippet still shows `entrypoint = "backend.main:app"` is "equivalent to `from backend.main import app`". One reviewer marked `main:app` as explained, noting it is "only implied by that comparison".

A's apparent advantage on these two seeds comes from flagging every term on the page, not from noticing that anything was removed. The data doesn't show that neutral reviewers miss removed definitions. It shows these two seeds weren't clean removals.

## What this says about the open questions

- **Q2 (what replaces the verdict):**
  - **The current verdict carries no information.** A and C gave the same verdict for clean and seeded copies.
  - **P's verdict separated clean from seeded in 7 of 8 runs.** The difference is surrounding context, not new verdict wording.
  - **Per-step pass/fail (S) separated every run.** Combining it with P (PS) lost that on FastAPI, so the two aren't complementary as written.
- **Q3 (reader context):** including the previous page is the strongest single change.
  - It cut clean-copy findings from about 3 to 0.2.
  - It raised H1 detection to 2/2.
  - It judged F1 and H4 the way a real reader would.
- **Q4 (recall check):** it catches missing steps, contradicting output and removed pointers. Removed definitions are still untested, because these seeds left a working explanation behind. The vocabulary check (PD) didn't help, and it added clean-copy noise.
- **Q7 (persona thinness):** the thin persona changed nothing measurable compared with C.

## Caveats

- **Small sample:** two runs per cell, one model, and one seed of each kind per page. A single different run changes any cell by 50 points.
- **Self-consistency isn't validity:** repeated runs of one prompt and model understate the true variance (arXiv 2604.11581).
- **Judge noise:** about one match per cell between judge passes.
- **Unclean context page:** in the p-family, the FastAPI previous page still contains termynal HTML that `prep.py` only cleans from first-steps.

## Next

- **E2 (task-based navigation) and E3 (control rerun)** come next, in that order. Use P as the per-page setup to rerun in E3.
- **Hard definition seed:** to test the definition question properly, remove a definition that leaves nothing behind. On the Hassette page, that means dropping the two bullets that explain `D` and `states`, which leaves `D.StateNew[states.SunState]` unexplained. That is on Alex's "does not know" list.

## Rerun

From the repo root:

1. Extract the pages. Fetch the FastAPI HTML for `tutorial/first-steps/` and `tutorial/` into one directory, run `uv run mkdocs build`, and copy `site/pages/getting-started/{index,first-automation}/index.html` into the same directory, named `<product>--<path>.html`. Then run:
   `uv run --with beautifulsoup4 python design/research/2026-10-20-llm-doc-usability-eval/control/extract.py <html_dir> design/research/2026-10-21-persona-review-seeded-recall/pages`
2. Build the variants and briefings:
   - `uv run python .../prep.py`
   - `uv run python .../build.py <queue>` (conditions a, c, s, p, t)
   - `uv run python .../build.py <queue2> ps pd`
3. Run the reviewers: for each `oNN` in a queue's `manifest.json`, dispatch one Sonnet subagent on its briefing, writing its JSON to `<queue>/out/oNN.json`.
4. Score the runs:
   - `uv run python .../score.py merge <merged> <queue> <queue2>`
   - `score.py judge-input <merged>`
   - Dispatch one Sonnet judge per `<merged>/judge/*.md`.
   - Then run `score.py report <merged>` and `score.py collect <merged>`.

Raw outputs, judge matches and the merged manifest are in `results/`.
