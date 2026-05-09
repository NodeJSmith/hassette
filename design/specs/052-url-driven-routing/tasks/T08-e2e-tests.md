---
task_id: "T08"
title: "Update and add e2e tests for URL-driven routing"
status: "done"
depends_on: ["T02", "T03", "T04", "T05", "T06", "T07"]
implements: ["AC#1", "AC#2", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7", "AC#8", "AC#9", "AC#10", "AC#11", "AC#12", "AC#13", "AC#14"]
---

## Summary
Update existing e2e tests to use the new URL patterns and add new e2e tests covering tab deep-links, handler deep-links, filter persistence across refresh, browser back/forward for tab changes, time window override, view-in-code line param, URL correction for invalid handler IDs, and default param omission.

## Prompt
Update existing and create new e2e test files:

1. **Update `tests/e2e/test_navigation.py`**:
   - Line 246: change `/apps/multi_app/0` to `/apps/multi_app?instance=0`
   - Review all other URL assertions for old patterns

2. **Update `tests/e2e/test_app_detail.py`**:
   - Line 287: change `/apps/multi_app/0` to `/apps/multi_app?instance=0`
   - Review all `?focus=` assertions — replace with handler deep-link assertions
   - Review all instance-index path assertions

3. **Review and update other e2e test files** that may reference old URL patterns:
   - `tests/e2e/test_apps.py` — check for `/apps/` URL patterns
   - `tests/e2e/test_apps_list.py` — check for navigation URL assertions
   - `tests/e2e/test_cmd_k.py` — check command palette navigation assertions
   - `tests/e2e/test_logs.py` — check log page URL assertions

4. **Add new e2e tests** (can be in a new `tests/e2e/test_url_routing.py` or distributed across existing files):
   - **Tab deep-links:** Navigate directly to `/apps/:key/logs` — verify logs tab is active
   - **Handler deep-links:** Navigate to `/apps/:key/handlers/h-{id}` — verify handler is selected in detail pane
   - **Filter persistence:** Set a filter on `/apps?filter=failed`, refresh the page, verify the filter is still "failed"
   - **Sort persistence:** Set a sort on `/handlers?sort=runs&dir=desc`, refresh, verify sort is preserved
   - **Browser back for tabs:** Navigate handlers → logs, press back, verify handlers tab
   - **Default omission:** Navigate to `/apps`, verify URL has no query params
   - **Time window override:** Navigate to `/handlers?window=24h`, verify data uses 24h window (check the time preset display)
   - **Invalid handler correction:** Navigate to `/apps/:key/handlers/h-99999`, verify handlers tab with no selection and URL corrected
   - **Instance via query param:** Navigate to `/apps/multi_app?instance=1`, verify instance 1 is loaded
   - **Parent overview:** Navigate to `/apps/multi_app` (no instance), verify parent overview grid is shown
   - **View in code:** Click "view in code" from a handler, verify URL includes `?line=N`, refresh and verify scroll position

## Focus
- E2e tests run via `uv run nox -s e2e` using Playwright
- The `conftest.py` has `mock_hassette` fixture that creates a test hassette instance with known apps — use this for predictable handler IDs
- Test the `live_server` fixture provides `base_url` — all URL navigation uses `page.goto(base_url + "/path")`
- For browser back/forward tests, use `page.go_back()` and `page.go_forward()`
- For URL assertion, use `expect(page).to_have_url(re.compile(r"pattern"))` or check `page.url`
- For filter persistence across refresh, use `page.reload()` after setting the filter
- Time window tests may need to verify the API call includes the correct `since` parameter — use `page.route()` to intercept or check the displayed time preset label

## Verify
- [ ] AC#1: Refreshing any page restores the exact view state
- [ ] AC#2: `/apps/:key/handlers/h-{id}` selects the handler
- [ ] AC#3: `/apps/:key/logs?level=ERROR&search=timeout` shows filtered logs
- [ ] AC#4: "View in code" produces `?line=N`; refresh restores scroll
- [ ] AC#5: Browser back after tab switch returns to previous tab
- [ ] AC#6: Sort column change does NOT create history entry
- [ ] AC#7: Bookmarked `?window=24h` shows 24h data; no-param page shows global preference
- [ ] AC#8: Time preset button updates URL and persisted preference
- [ ] AC#9: Default params are omitted from URL
- [ ] AC#10: Invalid handler ID shows no selection and corrects URL
- [ ] AC#11: All navigation sources produce new-format URLs
- [ ] AC#12: `?instance=1` loads instance 1; no instance param shows parent overview
- [ ] AC#13: Default apps page URL has no query params
- [ ] AC#14: `?instance=99` corrects to `?instance=0`
