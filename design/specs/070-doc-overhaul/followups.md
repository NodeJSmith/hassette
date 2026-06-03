# Doc Overhaul Follow-ups

Issues, follow-ups, and items to discuss before T13 (final sweep).

## Screenshots Needed

Web UI pages reference screenshots that may not exist or may be outdated:
- `web_ui_apps.png` — referenced by overview and manage-apps
- `web_ui_logs.png` — referenced by logs page
- Handlers page screenshots — referenced by debug-handler
- Other `_static/web_ui_*` images — need inventory and freshness check

## Orphaned Pages to Delete

Old tab-mirroring pages no longer in mkdocs nav (still on disk):
- `docs/pages/web-ui/apps.md` (118 lines)
- `docs/pages/web-ui/handlers.md` (65 lines)
- `docs/pages/web-ui/config.md` (45 lines)
- `docs/pages/web-ui/layout.md` (99 lines)
- `docs/pages/web-ui/app-detail/` (entire directory — 6 files, 583 lines)
- `docs/pages/web-ui/app-detail/snippets/handler_registration.py`

## Broken Cross-Links (Old Pages Removed from Nav)

The new task-oriented pages reference UI elements (Handlers page, App Detail) that had their own doc pages in the old structure. Those old pages are no longer in mkdocs nav. Fixed the most obvious link issues:
- `debug-handler.md`: removed link to `handlers.md`, kept text description
- `manage-apps.md`: removed 3 links to `app-detail/index.md`, kept text
- `inspect-config-code.md`: fixed `--` to `:` for consistency

Decision needed for T13: should any old pages be kept as redirects, or are the inline descriptions sufficient?

## CLI Start/Stop/Reload

Reviewer caught that `hassette app start/stop/reload <key>` CLI commands don't exist. Only REST API endpoints. The manage-apps page now correctly documents this. If CLI commands are added later, the manage-apps page needs updating.

## Items to Discuss

(populated as work progresses)
