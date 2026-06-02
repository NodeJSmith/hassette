# Testing — Write Your First Test

**Status:** New page (split from testing/overview.md). Section index at `pages/testing/index.md`.
**Voice mode:** Getting-started — "you" allowed, step-by-step
**Page type:** Getting-started
**Reader's job:** Write and run their first test for a Hassette app, proving it works without a live HA instance.

## What was cut

The existing index page mixes getting-started content (installation, quick
start) with full reference content (constructor tables, all simulate methods,
all assert methods). A reader writing their first test doesn't need the
`DrainFailure` hierarchy or `simulate_hassette_service_status()`.

This page keeps: installation, quick start example, and enough explanation
to get the reader to a passing test. Everything else lives on the Test
Harness Reference page.

## Outline

### Opening paragraph
One sentence: Hassette ships a test harness that runs your app without a live
HA instance — simulate events, assert API calls, control time.

### H2: What You'll Learn
Bulleted list: set up the harness, seed entity state, simulate a state change,
assert your app called the right service.

### H2: Install
`pip install hassette pytest pytest-asyncio` (or `uv add`). `asyncio_mode =
"auto"` in `pyproject.toml` — with the false-green warning.

### H2: Write the Test
Complete test file for a motion-lights-style app. Four pieces, walked through
in order:

1. Import and construct `AppTestHarness` with your app class and config dict.
2. `async with` — the app is fully initialized inside the block.
3. `set_state()` to seed the motion sensor as off.
4. `simulate_state_change()` to trigger motion on.
5. `api_recorder.assert_called("turn_on", ...)` to verify the light turned on.

Show the complete file first, then walk through each piece.

### H2: Run It
`pytest test_my_app.py -v` — expected output showing the test pass.

### H2: Next Steps
- Test Harness Reference — the full API (all simulate methods, all assert
  methods, error handling).
- Time Control — test scheduler-driven behavior.
- Recipes — copy a recipe and write a test for it.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `testing_install_pip.sh` | Keep | pip install command |
| `testing_install_uv.sh` | Keep | uv install command |
| `testing_asyncio_mode.toml` | Keep | pytest-asyncio config |
| `testing_quick_start.py` | Keep | Complete first-test example |

## Cross-Links

- **Links to:** Test Harness Reference, Time Control, Concurrency, Factories, Recipes
- **Linked from:** Getting Started/First Automation (next steps), Recipes (see also)
