# Migration — Testing

**Status:** Exists (41 lines), needs reframing — AD doesn't have a real testing story
**Voice mode:** Comparison — "you" allowed

## Outline

### H2: The Shift
AppDaemon has no built-in testing support. Third-party tools exist (appdaemontestframework, etc.) but they're limited and community-maintained. Hassette ships a full test harness.

### H2: What Hassette Provides
Brief summary — not a tutorial, just enough to show the migrator what's available:
- `AppTestHarness` for isolated app testing
- State seeding, event simulation, API call assertions
- Time control (`freeze_time`, `advance_time`)
- Concurrency helpers (drain)

### H2: Getting Started with Tests
Link to the Testing section for the full guide.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| ~1 migration/testing snippet | Keep | Minimal "here's what a test looks like" example |

## Cross-Links

- **Links to:** Testing overview
- **Linked from:** Migration overview
