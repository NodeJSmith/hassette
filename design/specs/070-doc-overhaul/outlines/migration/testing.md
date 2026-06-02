# Migration — Testing

**Page type:** Migration (feature comparison)
**Reader's job:** Understand that Hassette has built-in testing support (unlike AppDaemon) and get oriented enough to write their first test.
**Voice mode:** Comparison — "you" allowed

## What was cut (and where it goes)

- Nothing cut. This page is intentionally short. AppDaemon has no real testing story, so there is no feature-to-feature mapping. The job is to show the reader that testing exists, give them enough to try it, and link to the full guide.

## Outline

### H2: The Shift
One paragraph: AppDaemon has no official test harness. Third-party tools exist but are fragile and community-maintained. Hassette ships `hassette.test_utils` with `AppTestHarness` — a first-class async test harness that wires your app into a real (but test-grade) environment with `RecordingApi` instead of a live HA connection.

### H2: Setup
Two things the reader must do before tests work:
1. `asyncio_mode = "auto"` in `pyproject.toml` — without it, async tests silently pass without running. Warning admonition: this is the most common setup mistake.
2. `set_state()` before `simulate_state_change()` for the same entity — calling it afterward overwrites the simulated state.

### H2: What a Test Looks Like
One minimal snippet: `AppTestHarness` context manager, seed state, simulate event, assert API call. Enough for the reader to copy-paste and adapt.

### H2: Full Reference
One-sentence pointer to the Testing section. List capabilities without explaining them: state seeding, event simulation, API call assertions, time control (`freeze_time`, `advance_time`), concurrency helpers.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `testing_seed_order.py` | Keep | Demonstrates set_state/simulate ordering |

One new snippet needed: minimal test example showing `AppTestHarness` usage.

## Cross-Links

- **Links to:** Testing overview, Time Control, Concurrency & pytest-xdist
- **Linked from:** Migration overview, Migration checklist
