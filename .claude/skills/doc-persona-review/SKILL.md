# Doc Persona Review

Walk through documentation pages as a reader new to Hassette, and report only the problems that would stop them or make them do something wrong. Each reader gets the page under review plus a few pages before it in nav order (within its top-level section), treated as already read.

The findings list is meant to be short. A well-written page normally comes back with none, so every finding is worth fixing or explicitly dismissing. This setup comes from the #3148 experiments in `design/research/2026-10-21-persona-review-seeded-recall/`.

## Arguments

The page or section to review. Examples:
- `getting-started/first-automation`
- `recipes/motion-lights`
- `core-concepts/bus` (reviews all pages in the section)

If empty, ask what to review.

## Phase 1: Resolve Pages

Build the site, then resolve the argument to page paths:

```bash
uv run mkdocs build --strict
uv run tools/docs/extract_doc_page.py --list | grep -E '^<section>(/|$)'   # for a section
```

A single page is used as given; the assembler reports it if the path doesn't exist. Don't read `references/briefing-template.md` yourself; the assembler fills it in.

## Phase 2: Assemble Briefings

```bash
get-skill-tmpdir doc-persona-review
```

This prints a path like `/tmp/claude-doc-persona-review-a8Kx3Q`. Substitute that literal path for `<tmpdir>` below. A shell variable won't survive to the next command. Then, once per page:

```bash
uv run tools/docs/assemble_persona_briefing.py <page> <tmpdir>/briefings
```

Each call writes `<tmpdir>/briefings/<page-slug>.md`. It contains the reader, the instructions, and the page under review with numbered lines. It also includes the earlier pages: the assembler walks back through the built site's footer "Previous" links, up to `MAX_PRIOR_PAGES` and stopping at the edge of the page's top-level section. Chain the calls with `&&` for a section.

## Phase 3: Dispatch Readers

For each briefing file, dispatch a **Sonnet** subagent with this prompt:

```
Read the file at {briefing_path} and follow the instructions inside. Return only the JSON object it asks for.
```

Cap at 5 concurrent subagents.

Strip any code fence around each result and parse it as JSON. It must have `page`, `findings` (a list) and `summary`. Each finding's `type` must be one of `missing-step`, `missing-prerequisite`, `undefined-term`, `contradiction`, `no-verification` or `unclear-next-step`. If a result fails those checks, re-dispatch that page once. If the second result also fails, list the page under "not reviewed" in Phase 4 with the reason.

## Phase 4: Verify and Present

Before passing a finding on, check it against the briefing file. Read the cited `LINE N` and the text around it, and search the earlier pages in that file for the term or step the finding says is missing. The reader can miss something a page does say. Drop a finding the pages already answer, and say why.

List pages with findings first. Then name the pages that came back clean in one line, and any pages not reviewed. For each finding:

```
## page-name

- **[type]** L{line} ({section}): "{quote}"
  Problem: {problem}
  Fix: {suggestion}
```

## Changing This Skill

Before changing the briefing or the reader, check that the change still separates a good page from a broken copy of it. Don't commit seeded copies: they go stale as the pages change. Seed fresh ones from the current site each time:

1. Pick a page and save two copies of its extracted text: one untouched, and one with four planted defects. Plant a missing step, output that contradicts the code, a removed link or prerequisite, and a removed definition. Remove the whole definition: leaving text that half-explains the term is not a removal.
2. Build a briefing for each copy with the page's real earlier pages, and run each twice. The assembler only reads the built site, so fill the template yourself for the seeded copy (the research directory's `build.py` shows how).
3. The clean copy should come back with zero or one finding per run. Every seeded run should report more findings than every clean run. At least half the planted defects should be caught in at least one of the two runs; the current baseline is about two-thirds.

`design/research/2026-10-21-persona-review-seeded-recall/` is a worked example (`prep.py` for seeding, `build.py` for briefings, `score.py` for a blind judge). The baseline is the `p` condition there: clean copies averaged 0.2 findings, seeded copies 3.2, and the reviewer caught about two-thirds of the seeds that were real defects.

## Design Decisions

**Why no verdict?** The old four-level verdict (`followable` to `lost`) came back `followable-with-effort` on every page in the 2026-10-20 control run (`design/research/2026-10-20-llm-doc-usability-eval/`), including FastAPI's tutorial. The number and kind of findings is the signal.

**Why earlier pages?** Reading a page alone made the reader flag terms and steps the preceding page already covers. Including the previous page cut clean-page findings from about 3 to 0.2 per page in the seeded-recall experiment, more than any other change. That experiment tested a single previous page. The skill takes several (`MAX_PRIOR_PAGES` in the assembler) because the page a reader builds on isn't always the one right before it: `first-automation` follows the token page but builds on the Quickstart, two pages back. More than one page is untested. If the reader starts treating things as explained by pages a real reader would have skipped, lower it.

**Why one reader with only knowledge boundaries?** A stripped-down persona (what the reader knows, what they don't, and their goal) performed the same as the detailed persona it replaced in the same experiment. The `getting-started/` and `migration/` lines in the template shift those boundaries for those sections instead of adding separate personas.

**Why no voice guide or doc rules?** Removing them from the briefing didn't change finding counts in the control, and style is covered elsewhere. This review asks whether a reader can follow the page, not whether it matches house style.

**Why neutral wording?** "You must flag" and a checklist for every section produced 13–25 findings per page on known-good docs. The briefing now says an empty list is normal, and only keeps problems whose fix would change whether the reader succeeds.

**Known gap:** the experiment's definition seeds left a partial explanation behind, so how well this catches a cleanly removed definition hasn't been measured.

**Why Sonnet?** Its findings are precise enough to act on with a quick check against the page, and Haiku's suggestions were vaguer in earlier testing.

**Why briefing files?** The main agent handles page names and returned findings, and opens a briefing only to check a specific finding. Page text is assembled into files the subagents read, so a large section review doesn't fill the main context.
