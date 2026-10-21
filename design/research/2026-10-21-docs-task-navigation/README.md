---
status: Draft
issue: "#3148"
---

# Docs task-navigation proof of concept (2026-10-21)

Experiment E2 for #3148, Stage 1. A new-user agent gets one concrete question and can reach the docs only through a text browser (sidebar, search, open page). Stage 1 runs 10 tasks once each against the current site, to see whether the setup gives a usable signal before planting defects. It follows [E1, seeded recall](../2026-10-21-persona-review-seeded-recall/README.md).

## Bottom line

- **The harness works, but on the current site it's at ceiling.** All 10 answers were correct, all at high confidence, after 2 to 4 tool calls. Every run opened a page that holds the answer, and in every run a search result pointed there.
- **That means Stage 1 can't tell good docs from bad yet.** With no failures, there's nothing to trace to a docs cause. The setup only becomes a measure once a task can fail. That's what Stage 2's degraded site is for.
- **Search does almost all the work, and the sidebar barely matters.** Only 3 runs looked at the sidebar. Two looked after a search had already surfaced the answer page. The third (T03) looked first, then searched anyway, and opened the page from the search result. So a page missing from the sidebar would barely show up in this setup. Stage 2 should plant search-side defects, or block search on some runs, rather than relying on a nav-orphan seed.
- **Ask for the answer and read the trace, never the self-report.** In 3 runs, `found_on` names a reference page the agent only saw as a search snippet and never opened.

## Design

- **Tasks:** `tasks.json`, 10 questions in a new user's words, each with an expected answer and the pages that hold it (`sources`).
  - Each answer was checked against the code before the run.
  - `single_home` marks whether only one guide page covers it.
- **Tool:** `docsnav.py` over a frozen copy of `mkdocs build --strict` output from this branch (main after #3159).
  - `nav` prints the sidebar.
  - `search` ranks `search/search_index.json` sections with BM25, boosting titles.
  - `open` prints a page's text with links resolved to site paths.
  - Every call is appended to a per-run trace.
- **Agents:** Sonnet `standard-worker`, one per task. The briefing (`brief.py`, example in `results/stage1/briefing-example.md`) describes a generic Python developer who has finished the Quickstart and has no other Hassette knowledge. It forbids any source other than the tool. Briefings and traces have shuffled opaque names (`n01`..`n10`), and the manifest maps them back to tasks.
- **Scoring:** `score.py`.
  - `judge-input` writes each run's question, expected answer and given answer, with no trace data.
  - One blind Sonnet judge graded each answer as correct, partial, wrong or gave-up, strictly on the required details.
  - `report` joins the verdicts to trace metrics: calls, sidebar views, searches, opens, missing pages, whether a source page was opened and when, and whether any search surfaced a source.

## Results

| task | verdict | calls | nav | searches | opens | source opened at call |
|---|---|---|---|---|---|---|
| T01 weekday cron | correct | 2 | 0 | 1 | 1 | 2 |
| T02 extra loggers | correct | 4 | 1 | 2 | 1 | 4 |
| T03 cache after rename | correct | 3 | 1 | 1 | 1 | 3 |
| T04 Docker dependency | correct | 2 | 0 | 1 | 1 | 2 |
| T05 anybody home | correct | 2 | 0 | 1 | 1 | 2 |
| T06 test a 07:00 job | correct | 2 | 0 | 1 | 1 | 2 |
| T07 restart replays | correct | 2 | 0 | 1 | 1 | 2 |
| T08 forecast response | correct | 3 | 0 | 2 | 1 | 3 |
| T09 cancel_timer migration | correct | 4 | 1 | 2 | 1 | 4 |
| T10 disable an app | correct | 3 | 0 | 1 | 2 | 3 |

There were no missing-page opens, no gave-ups and no partial answers. Full table: `results/stage1/report.md`. Raw answers, traces and verdicts are in `results/stage1/`.

Notes from the traces:

- **T09** is the only real detour. The first search, "cancel timer", returned the `timer` entity's `cancel` method from the API reference, which is the wrong concept. The second search found the scheduler. A user who opened that first result could have gone wrong. That's a mild, real search-ranking finding: the reference pages outrank the migration guide for AppDaemon vocabulary.
- **T02's** second search used `extra_loggers`, a term the question doesn't contain. It came from a CHANGELOG snippet in the first search's results, not from prior knowledge. CHANGELOG sections rank high in several searches (T02, T06). Here that helped, but on the live site it would point users at release notes rather than guides.
- **T08's** agent also noticed the typed `WeatherEntity.get_forecasts` alternative in the reference results.

## Limits

- **One run per task and one model.** At 10/10, more runs would only confirm the ceiling.
- **The search is a stand-in.** The live site uses mkdocs-material's lunr search in the browser. BM25 over the same index may rank more forgivingly, so this likely overstates how easily people find answers on the real site.
- **Question wording leaks.** Some questions echo the docs' own phrasing (T03 "values it saved between restarts"; T07 "restarts"), which makes search easier than a real user's wording would.
- **The tasks are lookups.** Every task has one answer page, and none needs combining two pages or following a tutorial path. That's the docs' easy case.

## Design data for Q5 (how a navigation check should work)

- **A text tool is enough.** No run hit a limitation that a browser would have solved, and the trace is easier to score than browser actions.
- **10 lookup tasks on unchanged docs give no signal.** A useful version needs tasks that can fail:
  - planted defects (Stage 2)
  - harder tasks that combine pages or follow a tutorial path
  - runs with search disabled, to test the sidebar alone
- **Score from the trace:**
  - the judge's verdict
  - calls until a source page is opened
  - wrong-page opens before the source
  - whether search surfaced the source

  Pages opened and searches made vary too little here to separate anything.

## Found along the way

`docs/pages/core-concepts/api/methods.md` (around line 226) says `wait_for_ack` makes a misspelled entity id come back as a Home Assistant failure. Home Assistant core's `helpers/service.py` only logs a warning for referenced entities that don't exist, and the call still succeeds. Real errors come from an unknown service or invalid service data. Not yet filed.
