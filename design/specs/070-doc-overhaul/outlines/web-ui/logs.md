# Web UI — Read and Filter Logs

**Status:** Exists (119 lines), mostly GENUINE — well-structured, needs JTBD metadata and minor reorder
**Voice mode:** Concept/procedural hybrid — system-as-subject for descriptions, "you" for actions
**Page type:** Procedural (task-oriented)
**Reader's job:** Find a specific log entry or watch logs in real time to understand what their automations are doing.

## What was cut

Nothing removed. The existing page is well-written and task-oriented already.
The column table, filtering section, detail drawer, and live streaming are all
things a reader actively does.

Minor reorder: "Execution ID filtering" moved up to right after "Filtering and
search" since it's a filtering task. The column picker and detail drawer are
features the reader discovers while filtering, so they follow naturally.

Live streaming placed last — it's a passive activity (watching) vs the active
filtering tasks above.

## Outline

### Opening paragraph
Global, filterable, searchable view of all log entries. Real-time streaming.

Screenshot of logs page.

### H2: Filtering and Search
The primary task. Level filter, app filter, function text filter, search box.
Footer count and the 500-entry display limit.

### H2: Trace a Single Execution
`?execution_id=<id>` URL parameter filters to one handler/job execution.
Hassette links here from the Handlers tab. You can construct the URL manually.

### H2: Log Table Columns
Column reference table: name, sortable, filterable, description. Reference
material for when the reader wants to know what a column means.

### H2: Column Picker
Customize visible columns. Grid icon in footer. Required columns (Level,
Message). Responsive hiding behavior. Reset to defaults.

### H2: Log Detail Drawer
Click any row to see full entry: severity, timestamp, metadata grid, full
message, exception/traceback. Keyboard navigation (arrows, Escape).
Responsive layout (side panel on desktop, bottom sheet on mobile).

### H2: Live Streaming
Entries appear in real time. Auto-pause when sorted by anything other than
timestamp. Resume button in footer.

### H2: Related Pages
Links to app-detail logs tab (per-app view), app-detail handlers tab
(execution history with log links).

## Snippet Inventory

No code snippets — UI documentation.

## Cross-Links

- **Links to:** Web UI overview, Debug Handler (execution ID), Database & Telemetry
- **Linked from:** Web UI overview, Debug Handler, Operating/Log Levels
