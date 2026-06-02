# Testing — Write Your First Test

**Status:** New page (split from testing/overview.md)
**Voice mode:** Getting-started — "you" allowed, step-by-step

## Outline

### H2: What You'll Learn
Write a test for a Hassette app using AppTestHarness. Seed state, simulate events, assert API calls.

### H2: Prerequisites
pytest + hassette test extras installation. One-liner: `pip install hassette[test]` or `uv add hassette[test]`.

### H2: Step 1: Create a Test File
Minimal test file structure, naming convention (`test_<app>.py`).

### H2: Step 2: Set Up the Harness
`AppTestHarness(YourApp, config)` — construct and initialize. Show the `async with` pattern.

### H2: Step 3: Seed State and Simulate
Seed an entity state, simulate a state change, verify the handler ran.

### H2: Step 4: Assert the Result
`harness.api_recorder.assert_called("light/turn_on", ...)` to verify the app called the right service.

### H2: Next Steps
→ Testing overview (full API reference), → Time Control, → Recipes (write tests for recipe patterns)

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| New: `first_test.py` | New | Complete minimal test example |

## Cross-Links

- **Links to:** Testing overview (reference), Time Control, Concurrency, Factories
- **Linked from:** Getting Started/First Automation (next steps), Recipes (see also)
