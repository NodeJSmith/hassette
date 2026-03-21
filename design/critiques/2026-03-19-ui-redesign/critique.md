# Design Critique: UI Redesign Research Brief

**Date**: 2026-03-19
**Target**: `design/research/2026-03-19-ui-redesign/research.md`
**Method**: Three independent critics (Senior Engineer, Systems Architect, Adversarial Reviewer) with cross-reference scoring

---

## Findings

### 1. The brief solves a CSS framework problem when the user reported a design problem — CRITICAL

**What's wrong**: The user said "not intuitive, not clear, doesn't fit the vibe." The brief's central recommendation is replacing custom CSS with Tailwind — which addresses CSS *authoring* pain, not design quality. You can build an equally bad UI in Tailwind.
**Why it matters**: Phase 1 as written ("CSS-layer rewrite, not a structural change") will produce the same layouts, same interaction patterns, same hierarchy — just in utility classes. The user will open it and say "it looks different but still doesn't feel right."
**Evidence (code)**:
- `research.md:133-136` — "Custom CSS means maintaining everything from scratch" — developer complaint, not user complaint
- `research.md:212-214` — Recommendation frames the win as "addresses the root cause of CSS maintenance pain"
- `research.md:6` — User complaint quoted but never decomposed into actionable design problems
**References (external)**:
- [Task Analysis: A UX Designer's Best Friend (IxDF)](https://www.interaction-design.org/literature/article/task-analysis-a-ux-designer-s-best-friend)
**Raised by**: Adversarial + Senior + Architect
**Better approach**: Decompose each user complaint into testable design hypotheses. The CSS framework is an implementation detail that follows design decisions.
**Design challenge**: If you re-implemented the exact same page layouts in Tailwind, which of the user's five complaints would actually be resolved?

---

### 2. Two-phase approach inverts the correct order — CRITICAL

**What's wrong**: Phase 1 (visual refresh) then Phase 2 (IA restructure) is backwards. IA determines what content exists on each page. Visual design styles that content. Phase 1 will style Bus and Scheduler pages that Phase 2 deletes.
**Why it matters**: Phase 1 produces throw-away work for every page Phase 2 touches. Bus.html and scheduler.html get fully rewritten for Tailwind in Phase 1, then deleted in Phase 2.
**Evidence (code)**:
- `router.py:54-81` — Bus/Scheduler routes that Phase 1 styles and Phase 2 deletes
- `research.md:411-417` vs `research.md:234-244` — Phase 1 keeps structure that Phase 2 changes
- `app_instance_detail.html` — 139 lines rewritten for Tailwind in Phase 1, restructured into tabs in Phase 2
**References (external)**:
- [IA vs User Flow (Optimal Workshop)](https://www.optimalworkshop.com/blog/ia-vs-user-flow/)
- [UX Design Process (LogRocket)](https://blog.logrocket.com/ux-design/ux-design-process-7-steps/)
**Raised by**: Adversarial + Senior + Architect
**Better approach**: One phase: IA decisions first (wireframes, days not weeks), then visual design applied to the final page structure.
**Design challenge**: How many templates will be created in Phase 1 and then deleted or restructured in Phase 2?

---

### 3. "Phase 1 is CSS-only" is false — template rewrite is required — HIGH

**What's wrong**: Moving from `ht-card`, `ht-badge--success` to Tailwind utility classes requires changing `class=` attributes in all 56 HTML files. The icon swap (Font Awesome to Heroicons) touches every template too.
**Why it matters**: The 2-3 week estimate is scoped to "replace two CSS files" but the actual work is 56 HTML files + 34 CSS-class-based E2E selectors + icon markup.
**Evidence (code)**:
- `macros/ui.html:3-18` — hardcoded `ht-badge` classes
- `test_navigation.py` — 27 `.ht-` selectors
- `dashboard.html:5,11,22,35` — Font Awesome icons
**Raised by**: Senior + Architect
**Better approach**: Acknowledge the true scope. Add `data-testid` attributes as a Phase 0 prerequisite.
**Design challenge**: How many of the 56 HTML files can be migrated without changing a single `class=` attribute?

---

### 4. No task analysis — IA is data-model-shaped, not user-shaped — HIGH

**What's wrong**: The IA has a "Data Model Alignment" table mapping UI to backend services. It never identifies user tasks. There's a Bus page because there's a Bus service, not because users think "I want to see the bus."
**Why it matters**: Data-model-driven IA mirrors database tables. The redesign risks producing a new arrangement of the same pattern.
**Evidence (code)**:
- `research.md:266-278` — Data Model Alignment table
- `research.md:220` — "Based on the data model..."
- `router.py:54-81` — pages mirror backend services
**References (external)**:
- [Task Analysis (User Interviews)](https://www.userinterviews.com/ux-research-field-guide-chapter/task-analysis)
- [Jobs to Be Done (User Interviews)](https://www.userinterviews.com/ux-research-field-guide-chapter/jobs-to-be-done-jtbd-framework)
**Raised by**: Adversarial + Architect
**Better approach**: Enumerate 5-7 core user tasks. Trace current click paths. Design IA to minimize clicks for the top 3.
**Design challenge**: What are the three most frequent tasks a Hassette user performs?

---

### 5. Visual directions without mockups are not evaluable — HIGH

**What's wrong**: Three directions described in 42 lines of prose. None rendered. The brief admits mockups are needed as a follow-up.
**Why it matters**: The user will choose between descriptions, not designs. The decision will be made by whoever produces the first mockup.
**Evidence (code)**:
- `research.md:309-351` — 42 lines of prose with zero rendered artifacts
- `research.md:431-432` — admits mockup needed as step 2
**References (external)**:
- [Mockups in UX (UXtweak)](https://blog.uxtweak.com/mockup-ux/)
**Raised by**: Adversarial + Senior
**Better approach**: Produce one mockup per direction of the dashboard page. Let the design drive the tech stack.
**Design challenge**: If you had to commit to one direction right now, which would you choose and why?

---

### 6. Airflow scale mismatch — 4-layer hierarchy is over-architecture — HIGH

**What's wrong**: Airflow's hierarchy serves 200-10,000+ DAGs. Hassette has 3-10 apps. Adding tabs to App Detail *hides* information that is currently visible on one page.
**Evidence (code)**:
- `app_instance_detail.html:115-138` — all sections visible together without navigation
- `router.py:84-121` — already assembles everything in one response
**References (external)**:
- [Shopify: Airflow at Scale](https://shopify.engineering/lessons-learned-apache-airflow-scale) — 10,000+ DAGs
**Raised by**: Adversarial + Architect
**Better approach**: Design for actual scale. Celery Flower's three-panel pattern (everything visible, detail on demand) fits better.
**Design challenge**: At what app count does the 4-layer hierarchy provide more value than a flat layout?

---

### 7. Live-update system will break under tabs and Tailwind migration — HIGH

**What's wrong**: (a) Idiomorph morphing preserves Alpine.js state by matching nodes by structure — changing class attributes alters matching, causing expanded panels to collapse. (b) Tabs mean hidden content either wastes HTTP requests or shows stale data.
**Evidence (code)**:
- `live-updates.js:40` — `morph:innerHTML`
- `bus_listeners.html:14` — `x-data="{ open: false }"`
- `live-updates.js:60-64` — refreshes all elements regardless of visibility
**Raised by**: Senior + Architect
**Better approach**: Add `id` attributes to all Alpine.js stateful elements. Add visibility-aware refresh logic.
**Design challenge**: Have you tested what happens to Alpine.js state when a partial is morphed with different class attributes?

---

### 8. Merging Bus/Scheduler removes cross-app views with no replacement — MEDIUM

**What's wrong**: The Bus page's "All Apps" filter is the only way to compare listeners across apps. The brief handwaves a replacement.
**Evidence (code)**:
- `bus.html:9-23` — cross-app filter
- `partials.py:91-107` — supports both global and scoped views
**Raised by**: Senior + Architect
**Better approach**: Keep both: global views for cross-app operations AND per-app views in App Detail.

---

### 9. pytailwindcss is beta; Tailwind v4 standalone has ARM64/Alpine failures — MEDIUM

**What's wrong**: `pytailwindcss` is "4 - Beta", single-maintainer. Tailwind v4 standalone has documented ARM64 failures (issues #14569, #16555).
**References (external)**:
- [Issue #14569](https://github.com/tailwindlabs/tailwindcss/issues/14569)
- [Issue #16555](https://github.com/tailwindlabs/tailwindcss/issues/16555)
**Raised by**: Senior
**Better approach**: Pre-compile CSS at publish time. Ship compiled CSS. Only developers need the binary locally.

---

### 10. Dual identity model is an active bug, not a redesign concern — MEDIUM

**What's wrong**: `router.py:105` filters by `owner_id`, `partials.py:67` filters by `app_key` alone — not equivalent. Template renders `owner_id` as display value.
**Raised by**: Architect
**Better approach**: Fix now as a bug. Partial should filter on `app_key AND instance_index`.

---

### 11. Prior art studies function, not feel — TENSION

**The disagreement**: The brief surveys 6 monitoring tools for architecture (Senior/Architect find this valuable for IA). The Adversarial reviewer argues this misses the point — the user complained about feel, and the visual inspirations (Linear, Raycast, shadcn/ui) are never analyzed. Both views have merit.

---

## Overall Assessment

The brief is well-researched but solves the wrong problem first. The process should be:
1. **Task analysis** — what do users actually do?
2. **Mockups** — what should this look and feel like?
3. **IA decisions** — informed by tasks and visual direction
4. **Tech stack** — whatever best serves the design

The Tailwind recommendation may ultimately be correct, but it should follow the design, not lead it.

## Appendix: Individual Critic Reports

These files contain each critic's unfiltered findings and are available for the duration of this session:

- Senior Engineer: `/tmp/claude-mine-challenge-joVOIz/senior.md`
- Systems Architect: `/tmp/claude-mine-challenge-joVOIz/architect.md`
- Adversarial Reviewer: `/tmp/claude-mine-challenge-joVOIz/adversarial.md`
