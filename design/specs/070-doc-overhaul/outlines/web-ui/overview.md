# Web UI — Overview

**Status:** Exists (56 lines), needs JTBD redesign — currently feature-oriented, should orient the reader toward tasks
**Voice mode:** Concept — system-as-subject for descriptions, "you" for actions
**Page type:** Concept (landing page)
**Reader's job:** Figure out what the web UI can do for them and get to the right page for their task.

## What was cut (and where it goes)

The existing page has good content (enabling, accessing, config reference) but
ends with "Related pages" that link to old feature-oriented pages (layout.md,
apps.md) instead of the new task-oriented pages.

Old `layout.md` (sidebar, status bar, command palette, alerts) is absorbed
into this page as a brief "Layout" section — it doesn't warrant its own page
since it's orientation material, not a task.

The config quick-reference collapsible section stays — it's useful lookup
material for an overview page.

## Outline

### Opening paragraph
What the web UI shows: app health, handler invocation history, structured
logs, system configuration. Runs in the same process as the REST API — nothing
extra to start.

Screenshot of apps page.

### H2: Enabling and Accessing
Default URL, default bind address, how to change host/port. Security warning
(no auth, bind to 127.0.0.1 or use reverse proxy). Disabling UI while keeping
REST API. First-run note (empty tables until automations run).

Collapsible config quick reference table.

### H2: Layout
Brief orientation: sidebar navigation, status bar, command palette, alert
banners. Enough to navigate, not a feature tour. Absorbed from old layout.md.

### H2: What Can I Do Here?
Task-oriented link list — each links to its page with a one-sentence
description of the task:

- **[Manage Apps](manage-apps.md)** — start, stop, reload apps; check health
  and status
- **[Debug a Failing Handler](debug-handler.md)** — find why a handler isn't
  firing or is throwing errors
- **[Read and Filter Logs](logs.md)** — search, filter, and stream logs in
  real time
- **[Inspect Configuration and Code](inspect-config-code.md)** — view global
  and per-app config, read app source

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `disable-ui.toml` | Keep | TOML config for disabling UI |

## Cross-Links

- **Links to:** Manage Apps, Debug Handler, Logs, Inspect Config & Code, Configuration/Global (web settings)
- **Linked from:** Architecture, Docker Setup, Home page
