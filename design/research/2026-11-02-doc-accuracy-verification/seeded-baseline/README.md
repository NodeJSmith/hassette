---
status: Draft
---

# doc-accuracy-review seeded baseline (2026-11-02)

The first recall measurement of `doc-accuracy-review`, using the skill's briefing unchanged. It's the control for any rewrite. See [`../prior-art.md`](../prior-art.md) for the candidate changes.

## Bottom line

- **A single run caught 78% of planted errors (42 of 54), and clean and seeded copies separated on every run.** Clean copies got 0–2 findings and seeded copies got 4–7.
- **Its findings can be trusted.** Of 53 findings, 51 were real false claims. The other 2 were true but incomplete: they noted that the page's "missing or non-numeric" wording leaves out booleans.
- **It misses claims that need tracing through the code.** Three seeds needed following a path across functions, and they were caught 2 of 9 times. The other 15 could be checked by reading one definition, and they were caught 40 of 45 times. This grouping was made after seeing the results.
- **78% overstates real-world recall.** The real glob error on `predicate-reference` was caught in 2 of 6 runs here, and 3 of 10 counting the four earlier runs. The real `C.Regex` looseness was never reported as a finding.
- **Repeating the same run helps a little, then stops.** Combining runs took recall from 78% to 85% at two passes and 89% at three. Two seeds were missed by all three runs, so repeats share blind spots.
- **`claims_checked` carries no signal.** A run reporting 78 claims caught 3 of 6 seeds, and one reporting 62 caught 5.

## Design

- **Pages:** `core-concepts/bus/predicate-reference` (long reference), `core-concepts/scheduler/methods` (signatures and options), `core-concepts/apps/lifecycle` (shorter, behavior-heavy).
- **Seeds:** 6 per page, one per kind (`seeds.json`), each a literal replacement in the extracted page. Each was checked against the code first, by running it where possible. `evidence` records how.
- **Runs:** 3 per copy of each page, so 18 in total: Sonnet `standard-worker`, using the skill's dispatch prompt and briefing template, at most 5 at once.
- **Blinding:** briefings had shuffled names (`page-01`), with the seeds kept in a separate directory. `../prior-art.md` was moved out of the repo during the runs. No run opened the page under review, based on a search of the transcripts.
- **Scoring:** `score.py` matches each finding's `doc_quote` against the wording that only the false sentence contains. Agents quote the page, so no judge was needed. Everything unmatched was checked by hand. This measures raw agent output; the skill's triage step isn't included, and it can only remove findings.

To rerun, build a briefing set with `prep.py`, dispatch it, and save each run's JSON to a results directory with `_tools` and `_tokens` added. `score.py` scores that directory. The saved results here came from these runs' transcripts, which aren't kept.

## Results

| Seed | Kind | Caught | Needs tracing? |
|---|---|---|---|
| P1, S1, L1 | default value | 3/3 each | |
| P3, S3, L3 | exception | 3/3 each | |
| P5, L5 | overclaim | 3/3 each | |
| S5 | overclaim | 2/3 | |
| P6, S6 | wrong condition | 3/3 each | |
| L6 | wrong condition (cleanup order) | 1/3 | yes |
| P4 | inversion | 3/3 | |
| S4 | inversion (next-run calculation) | 1/3 | yes |
| L4 | inversion (timed-out stop status) | 0/3 | yes |
| L2 | API name | 3/3 | |
| P2 | API name | 2/3 | |
| S2 | API name | 0/3 | |

| Page | Clean findings per run | Seeded findings per run | Seeds caught per run (of 6) |
|---|---|---|---|
| `predicate-reference` | 2, 1, 0 | 6, 7, 6 | 6, 6, 5 |
| `methods` | 1, 1, 1 | 5, 6, 4 | 4, 5, 3 |
| `lifecycle` | 0, 0, 0 | 5, 4, 4 | 5, 4, 4 |

**Combining runs**, averaged over every combination of runs per page:

| Passes | Mean seed recall |
|---|---|
| 1 | 77.8% |
| 2 | 85.2% |
| 3 | 88.9% |

Each run used about 117k subagent tokens, so the 18 runs took 2.1M.

**Real errors on the pages:**

| Error | Caught |
|---|---|
| `hassette reload` isn't a command (`methods`; filed as #3731) | 6/6 |
| Glob strings as conditions (`predicate-reference`; #3723) | 2/6: clean 2/3, seeded 0/3 |
| `C.Regex` start anchoring (`predicate-reference`; #3723) | 0/6 as a finding; one run mentioned it and declined to report it |

Before this baseline, the glob error was caught 1 of 3 times on 2026-11-02 and missed in the October pass.

**Misses take two forms.** Some runs say they skipped a claim: one reported that it did not trace the cleanup order, and missed L6. Others confirm a false claim: another run's summary said the automatic-cleanup claims were accurate, with the same seed on the page. Several runs volunteered lists of claims they hadn't verified, even though nothing asks for them.

## Caveats

- **S2 and S6 share a table cell.** The other planted error in that cell (S6) was caught every time, so S2's 0/3 may partly reflect agents stopping at one finding per cell.
- **Seeds are much denser than real errors.** Each seeded page has 6 errors. The glob error was caught 2 of 3 times on clean copies and 0 of 3 on seeded ones, which could mean planted errors crowd out real ones, but that's too few runs to say.
- **Only 3 tracing seeds.** The 2 of 9 is a clear gap but a rough number, and the grouping came after the results. Nearly all the misses of real interest are in this class, so the next experiment needs more of them.
- **Three runs per cell** gives coarse numbers per seed. Treat the aggregates as the result.
- **One author chose the seeds and the pages.** The same person wrote and scored them.

## What this means for the rewrite

- **Target tracing claims.** Prompts that encourage identical re-checks won't reach them, since repeats gain 7 points at two passes and still leave blind spots.
- **Test a focused second pass against an identical one.** A pass that traces only behavior claims is the natural candidate, and it fits the prior art's finding that varied passes do better than repeats.
- **Make skipped claims explicit.** Agents already volunteer what they didn't verify, so asking for it could expose a miss without a full per-claim ledger.
- **Add seeds before comparing variants.** Use at least 6 tracing seeds, one error per table cell, a lower seed density, and the glob and regex errors pinned as natural cases.

## Opus comparison

The same 18 briefings and prompt, on Opus 5.5 instead of Sonnet 5.5. Results are in `results-opus/`. To rescore, run `python3 score.py results-opus`.

| Measure | Sonnet | Opus |
|---|---|---|
| Seeds caught | 42/54 (78%) | **54/54 (100%)** |
| Seeds needing tracing | 2/9 | **9/9** |
| Glob error (natural) | 2/6 | **6/6** |
| `hassette reload` (natural) | 6/6 | 6/6 |
| `C.Regex` anchoring (natural) | 0/6 | 0/6 |
| Findings per clean run | 0–2 (mean 0.7) | 2–5 (mean 3.6) |
| Findings per seeded run | 4–7 | 6–9 |
| Runs that executed Python to test a claim | 1 of 18 | **16 of 18** |
| Subagent tokens per run | 117k | 178k (+52%) |
| Duration per run | about 20–45s | about 75–170s |

**The likely reason is execution.** Opus ran Python to test claims in nearly every run, where Sonnet almost never did, and it also read further across files. Both had the same instructions, and neither was asked to run anything. This is an inference from one comparison, and it hasn't been tested on its own.

**Comparing with the original page didn't produce these results.** Eight of the 18 Opus runs opened the original page, or the extracted copy next to the briefings, and some reported the mismatch. On seeded copies, those looks came late (tool call 9 or later, near the end of the run). All three `lifecycle` seeded runs had read the code behind L4 and L6 before opening the page, and the three seeded runs that never opened it still caught 6 of 6. Sonnet never looked. The extracted copy was moved partway through the runs.

**Extra findings need triage.** Opus reported real overstatements Sonnet missed, such as `A.get_context` being called a dict when it returns a `HassContext`, a swallowed cancellation not always holding a stop, and the reload rationale for `if_exists` not holding. Those three, plus the dev-mode default, were checked against the code here. The rest weren't individually verified. Many are low severity, and some are edge cases, so filing all of them would add fix-up churn.

**A real code bug surfaced.** Two runs found that `on_error` handlers registered in `on_initialize` get cleared when the app's `Bus` and `Scheduler` children initialize after the hooks return. Reproduced through `AppTestHarness`: both handlers were set during `on_initialize`, both were `None` after startup, and a raising handler ran without `on_error` firing. The documented example registers its handler this way.

**Caveats:**

- **100% is a ceiling.** These seeds can no longer separate Opus from anything better, so harder seeds are needed to measure its misses. `C.Regex` shows it still has some.
- **Three pages and one comparison.** Treat the gap as large, not as a precise figure.
- **Cost is in tokens, not price.** Opus tokens cost more per token than Sonnet's, so the real gap is wider than 52%. It hasn't been priced here.

## Updated conclusion

Moving the verifier to Opus closes the gap this work set out to fix, without any of the prompt changes in `../prior-art.md`. An untested alternative is Sonnet told to execute claims, which might get much of the benefit at lower cost. That is the one remaining comparison worth running before deciding.
