## Visual QA — 2026-03-23

### 1. Handler descriptions truncate the most important information — HIGH
App detail handler rows show full dotted-path strings that bury entity IDs mid-string. Ellipsis cuts off the most critical info. Extract entity ID as a separate visible field.

### 2. No way to enable a disabled app from the UI — HIGH
Disabled apps have no Enable button on detail page or apps list. Users must edit config files. Add Enable/Start button for disabled apps.

### 3. App detail sections lack visual rhythm — same spacing inside and between — HIGH
Inter-section gap (~16px) matches intra-section padding. Section boundaries are ambiguous. Double inter-section spacing to ~32px.

### 4. Action buttons dominate the apps list table — MEDIUM
Stop/Reload stacked vertically make rows ~80-90px. 12+ outlined colored buttons compete for attention. Side-by-side, ghost style, or overflow menu.

### 5. "Connected" bar wastes prime vertical real estate — MEDIUM
40px full-width bar communicates one bit (connected/not) that's true 99.9% of the time. Collapse to status dot in sidebar; reserve full bar for disconnected.

### 6. Empty sections waste space on app detail — MEDIUM
"Event Handlers (0 registered)" and "Scheduled Jobs (0 active)" take ~80px each for zero content. Collapse or make compact single line.

### 7. Stop button lacks visible hover feedback — MEDIUM
Destructive action shows no visible change on hover. No confirmation dialog either. Add hover state.

### 8. Status badge uses three different treatments for "running" — LOW
Dashboard cards: green text + dot. Apps list: green pill badge. App detail KPI: large green text. Unify to one treatment.
