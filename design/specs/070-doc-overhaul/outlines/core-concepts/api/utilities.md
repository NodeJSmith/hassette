# API — Utilities

**Status:** Exists (81 lines), reference-style, voice polish needed
**Voice mode:** Reference — terse, system-as-subject

## Outline

### H2: Templates
`render_template()` — render HA Jinja2 templates. Accepts a `variables` dict for template context.

### H2: History
`get_history()` — retrieve entity history. Parameters: `significant_changes_only` (filter to meaningful changes), `minimal_response` (delta-encoded entries, smaller payload), `no_attributes` (omit attribute data). `get_histories()` for batch retrieval of multiple entities.

### H2: Logbook
`get_logbook()` — retrieve logbook entries.

### H2: Discovery
#### H3: `get_config` — retrieve HA configuration (version, location, units, components)
#### H3: `get_services` — list all available services and their fields
#### H3: `get_panels` — list HA frontend panels

### H2: Other Endpoints
#### H3: `fire_event` — fire custom HA events
#### H3: `set_state` — override entity state
#### H3: `get_calendars` — list calendars
#### H3: `get_calendar_events` — retrieve calendar events

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant files from `api/snippets/` | Review | Utility method examples |

## Cross-Links

- **Links to:** API overview
- **Linked from:** API overview
