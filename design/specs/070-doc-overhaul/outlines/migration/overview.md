# Migration — Overview

**Page type:** Migration (landing page)
**Reader's job:** Decide whether to migrate from AppDaemon, then find the right page for each piece of their app.
**Voice mode:** Getting-started — "you" allowed, comparison-driven

## What was cut (and where it goes)

- **Migration Checklist** page removed. Its content was a thin restatement of the sub-pages. The Quick Reference Table on this page and the sub-page-per-topic structure already serve as the "what to do" checklist. The existing `checklist.md` page remains as a step-by-step per-app checklist for readers who want a linear walkthrough.
- **Guide Structure** section removed. The page's own heading order and the Quick Reference Table make the structure self-evident. A table-of-contents section about the table of contents adds no value.
- **"What Changes"** merged into the Quick Reference Table intro. Four numbered bullets restating the sub-page topics is redundant when the table already maps every operation.
- **Next Steps** section removed. Duplicated the Guide Structure table.

## Outline

### H2: Quick Reference Table
Lead with this. The reader's first job is lookup: "I use `listen_state` — what's the Hassette version?" The table maps the 10 most common AppDaemon operations to Hassette equivalents. One row per operation, three columns: Action | AppDaemon | Hassette. Each Hassette cell links to the relevant sub-page.

One-sentence intro above the table: four areas change (configuration, app structure, event handlers, API calls) and every row links to the full guide.

### H2: Is Migration Worth It?
Two-column table: "You should migrate if..." vs "You might stay with AppDaemon if..." — honest, no selling. The reader who got here from the evaluator page already wants to migrate; this section is for the reader who landed directly.

### H2: Known Gaps
Table of AppDaemon features not yet in Hassette. Each row: feature name, status (out of scope / roadmap / workaround). Tells the reader to stop before investing effort if they depend on a missing feature.

### H2: Common Pitfalls
The four most common migration breakages, each as a one-liner with the fix:
- `name=` required on all bus subscriptions (`ListenerNameRequiredError`)
- Forgetting `await` on `self.api.*` and `self.bus.on_*` calls
- `changed_to="on"` (string), not `changed_to=True`
- `AppSync` hooks use `.sync` facades, not the async API directly

### H2: Per-App Migration Checklist
One-paragraph pointer to `checklist.md` — the step-by-step checklist for migrating a single app.

## Snippet Inventory

No code snippets on this page. The Quick Reference Table uses inline code, not snippet files.

## Cross-Links

- **Links to:** All migration sub-pages, checklist.md, Is Hassette Right for You?, Getting Started
- **Linked from:** Home page, Is Hassette Right for You?
