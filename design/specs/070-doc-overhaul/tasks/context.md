# Context: Documentation Overhaul

## Problem & Motivation

The 76 hand-written documentation pages grew organically over months. Voice-guide.md and doc-rules.md define mature standards, but adherence varies widely: recipes and getting-started are closest to the target voice, core-concepts and advanced are furthest. Dependency injection is explained in three places at contradictory depth. Web UI docs organized by tab names mean readers searching "how do I debug a handler?" can't find it. State customization is buried in "Advanced" instead of next to the States concept page. The Architecture page mixes app-author and contributor audiences. A blank-slate rewrite with a planned structure is the faster path to consistent, reader-serving documentation.

## Visual Artifacts

None.

## Key Decisions

1. **Blank-slate rewrite over incremental patching.** Structural problems (scattered DI, tab-mirroring Web UI, Advanced grab-bag) compound across pages. Incremental fixes can't address cross-section structure. Trade-off: higher risk of regression on already-good pages, mitigated by exemplar anchoring.
2. **Three-phase process (outline → content outlines → writing).** Optimizes for structural consistency and voice coherence — everything is planned before anything is written. Trade-off: delays visible progress and increases scope fatigue risk.
3. **Three exemplar pages before bulk writing.** Concept, getting-started/recipe, and reference exemplars anchor voice. Written first, reviewed, then used as reference for all remaining pages.
4. **Section PRs to a long-lived docs branch.** Users see an atomic swap when the docs branch merges to main. Review happens incrementally per section. Rebase docs onto main after each section PR.
5. **`mkdocs build --strict` enforced from the start.** Phase 1 creates stub files for every page in the new tree. Stubs satisfy the strict checker even before content is written. Section PRs replace stubs with real content.
6. **Muffet for post-build HTML link checking.** Complements the existing lychee check (which runs on markdown source). Muffet checks built HTML and catches broken anchor fragments that `--strict` and lychee miss.
7. **Migration section stays.** Hassette has no existing users who've completed the migration, so AD migration content is still a primary inflow path. May condense from 8 pages to fewer.
8. **PUBLIC_MODULES review included in Phase 1.** Quick check during site outline to see if the auto-generated API reference module list is stale.

## Constraints & Anti-Patterns

- **Voice-guide.md (22 rules) and doc-rules.md are authoritative.** The rewrite conforms to them; it does not revise them (except: doc-rules.md recipe template updated to include "Verify it's working" step per FR#4).
- **`pymdownx.snippets` with `check_paths: true`** — any `--8<--` reference to a non-existent snippet file fails the build. Pages and snippets must be created together. Create snippet stubs first to satisfy the checker.
- **No "Advanced" section.** Content rehomed to core-concepts/states/ (custom states, state registry, type registry), troubleshooting (log level tuning), and the new Operating Hassette section.
- **DI has one canonical page** at `core-concepts/bus/dependency-injection.md`. All other pages that reference DI compress to one sentence with a link.
- **Web UI pages organized by user task, not UI element.** No tab-mirroring. Maximum 6 pages, each justified as a discrete user task.
- **"You" only in getting-started and recipe procedure sections.** Concept and API reference pages use system-as-subject voice.
- **No inline code examples.** Every code block for a Hassette example comes from a CI-tested snippet file via `--8<--` includes.
- **Non-goals:** API reference auto-generation changes, source code docstrings, design documents, frontend/CSS changes, new feature documentation, CI improvements beyond rewrite needs.

## Design Doc References

- `## Problem` — what's broken, reader costs, why patching won't work
- `## Goals` — concrete reader outcomes per section (install, explain, adapt, find, debug, migrate)
- `## User Scenarios` — three actors (Evaluator, New User, Active Developer) with task flows
- `## Functional Requirements` — FR#1–FR#18, covering voice, structure, snippets, knowledge preservation
- `## Edge Cases` — snippet sequencing, cross-link breakage, knowledge loss, voice drift, regression risk
- `## Acceptance Criteria` — AC#1–AC#20, mapped to FRs
- `## Architecture` — three-phase process, branch strategy, exemplars, voice audit checklist, link validation
- `## Replacement Targets` — nav structure, all 76 pages, advanced/ directory, unclaimed snippets, managing-helpers location
- `## Test Strategy` — existing CI (mkdocs build --strict, Pyright), new CI (muffet link checker, snippet orphan check)

## Convention Examples

### Voice: System-as-subject (concept pages)

**Source:** `.claude/rules/voice-guide.md`, "After" example in Concept Page section

```markdown
The event bus delivers Home Assistant events — state changes, service calls,
component loads — to any app handler that subscribes. It also delivers
Hassette-internal events.

`self.bus` is available on every `App` instance. Hassette creates it at startup.
```

### Voice: Code-first with "you" (getting-started pages)

**Source:** `.claude/rules/voice-guide.md`, "After" example in Getting-Started Page section

```markdown
## Step 3: Subscribe to a state change

Call `self.bus.on_state_change()` to subscribe. The `"sun.*"` pattern matches
any entity in the `sun` domain — in practice, `sun.sun`.
```

### Voice: Prose "How It Works" (recipe pages)

**Source:** `.claude/rules/voice-guide.md`, "After" example in Recipe Page section

```markdown
`on_state_change` subscribes to every state transition on the motion sensor.
`D.StateNew[states.BinarySensorState]` delivers the new state as a typed
object — the handler covers both `"on"` and `"off"` transitions in one place
rather than two separate subscriptions.
```

### Snippet inclusion pattern

**Source:** `.claude/rules/doc-rules.md`, Examples section

```markdown
Full file:
  --8<-- "pages/core-concepts/bus/snippets/subscribe_example.py"

Fragment via section markers:
  --8<-- "pages/core-concepts/bus/snippets/bus_subscribe.py:subscribe"
```

### DO/DON'T: "How It Works" formatting

**Source:** `.claude/rules/voice-guide.md`, Recipe Page before/after

DON'T — bullet list with bolded lead-ins:
```markdown
- **`on_state_change`** subscribes to every state transition on the motion
  sensor. The handler uses **dependency injection** ...
- When state is `"on"`, any pending off job is cancelled...
```

DO — flowing prose paragraphs:
```markdown
`on_state_change` subscribes to every state transition on the motion sensor.
`D.StateNew[states.BinarySensorState]` delivers the new state as a typed
object — the handler covers both transitions in one place.

When motion turns on, any pending off job is cancelled before the light
turns on. This resets the timer...
```
